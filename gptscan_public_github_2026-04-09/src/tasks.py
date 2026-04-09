import yaml
import os
import re
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Tuple
import config as global_config
import datetime
import json
import falcon_adapter
import traceback
import static_check
import utils
import sys
import time
import argparse
import subprocess
import rich
from rich.progress import Progress
from rich.table import Table
from rich_utils import *
import falcon
from project_dependencies import find_project_root
from project_paths import REPO_ROOT, RULES_DIR, TASKS_DIR, ensure_parent_dir, ensure_project_work_dir
from scan_exceptions import CompileFailure

logger = logging.getLogger(__name__)

console = rich.get_console()

SOURCE_DIR_NAMES = ("contracts", "src")
EXCLUDED_SOURCE_PARTS = {
    ".gptscan",
    ".git",
    ".github",
    "artifacts",
    "broadcast",
    "cache",
    "discord-export",
    "docs",
    "node_modules",
    "outside-scope",
    "out",
    "report",
    "reports",
    "resource",
    "resources",
    "mock",
    "mocks",
    "script",
    "scripts",
    "echidna",
    "test",
    "tests",
}


class _StaticValidationError(Exception):
    pass


def _normalize_validation_value(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def _validate_static_answer(vul: dict, answer: dict, raw: dict) -> None:
    if "validate_description" in vul["static"]:
        for to_validate_key, to_validate_values in vul["static"]["validate_description"].items():
            validate_flag = True
            if to_validate_key in raw and answer.get(to_validate_key) in raw[to_validate_key]:
                for v_line in to_validate_values:
                    v_line_flag = False
                    for v in v_line:
                        if v.lower() in raw[to_validate_key][answer[to_validate_key]].lower():
                            v_line_flag = True
                            break
                    validate_flag = validate_flag and v_line_flag
            if validate_flag is False:
                raise _StaticValidationError(
                    f"{vul['name']} failed validate_description for {to_validate_key}: {answer.get(to_validate_key)}"
                )

    if "exclude_variable" in vul["static"]:
        for to_exclude_key, to_exclude_values in vul["static"]["exclude_variable"].items():
            normalized_answer = _normalize_validation_value(answer.get(to_exclude_key))
            for var in to_exclude_values:
                normalized_var = _normalize_validation_value(var)
                if normalized_var and normalized_var in normalized_answer:
                    raise _StaticValidationError(
                        f"{vul['name']} excluded variable {answer.get(to_exclude_key)} for {to_exclude_key}"
                    )


def configure_solc_version(version: str | None) -> None:
    if not version:
        return
    local_solc_bin = str(Path.home() / ".local" / "bin")
    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(":") if current_path else []
    if local_solc_bin not in path_parts:
        os.environ["PATH"] = ":".join([local_solc_bin, current_path]) if current_path else local_solc_bin
    os.environ["SOLC_VERSION"] = version


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    result = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


IMPORT_RE = re.compile(r'^\s*import\s+(?:[^"\']+\s+from\s+)?["\']([^"\']+)["\'];', re.MULTILINE)


def _find_ancestor_lib_root(base: Path) -> Path | None:
    for candidate in [base, *base.parents]:
        lib_dir = candidate / "lib"
        if not lib_dir.is_dir():
            continue
        try:
            package_dirs = [child for child in lib_dir.iterdir() if child.is_dir()]
        except OSError:
            continue
        for package_dir in package_dirs:
            try:
                if any(package_dir.rglob("*.sol")):
                    return candidate
            except OSError:
                continue
    return None


def _read_import_paths_from_project(project_root: Path) -> set[str]:
    imports: set[str] = set()
    for sol_file in _collect_project_source_files(project_root):
        try:
            text = sol_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports.update(match.group(1) for match in IMPORT_RE.finditer(text))
    return imports


def _read_remappings(project_root: Path) -> dict[str, Path]:
    remappings: dict[str, Path] = {}
    remappings_file = project_root / "remappings.txt"
    if not remappings_file.exists():
        return remappings
    for raw_line in remappings_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        prefix, target = line.split("=", 1)
        resolved_target = Path(target)
        if not resolved_target.is_absolute():
            resolved_target = (project_root / target).resolve()
        remappings[prefix.rstrip("/") + "/"] = resolved_target
    return remappings


def _collect_node_module_remappings(project_root: Path) -> dict[str, Path]:
    remappings: dict[str, Path] = {}
    candidate_roots = [
        project_root / "node_modules",
        project_root / ".gptscan" / "npm_vendor" / "node_modules",
    ]

    for node_modules in candidate_roots:
        if not node_modules.exists():
            continue
        for child in sorted(node_modules.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.startswith("@"):
                remappings[f"{child.name}/"] = child.resolve()
                for package_dir in sorted(child.iterdir()):
                    if package_dir.is_dir():
                        remappings[f"{child.name}/{package_dir.name}/"] = package_dir.resolve()
            else:
                remappings[f"{child.name}/"] = child.resolve()
    return remappings


def _collect_local_alias_remappings(project_root: Path, import_paths: set[str]) -> dict[str, Path]:
    remappings: dict[str, Path] = {}
    source_roots = [
        source_root.resolve()
        for source_root in (project_root / "src", project_root / "contracts")
        if source_root.exists()
    ]
    if not source_roots:
        return remappings

    for source_root in source_roots:
        remappings[f"{source_root.name}/"] = source_root
        child_dirs = {child.name: child.resolve() for child in source_root.iterdir() if child.is_dir()}
        for import_path in import_paths:
            if import_path.startswith("."):
                continue
            parts = import_path.split("/")
            if not parts:
                continue
            first = parts[0]
            if first in child_dirs:
                remappings[f"{first}/"] = child_dirs[first]
            if first.startswith("@") and len(parts) >= 2 and parts[1] in child_dirs:
                remappings[f"{first}/{parts[1]}/"] = child_dirs[parts[1]]
    return remappings


def _collect_lib_remappings(project_root: Path) -> dict[str, Path]:
    remappings: dict[str, Path] = {}
    lib_root_base = _find_ancestor_lib_root(project_root)
    if lib_root_base is None:
        return remappings
    lib_root = lib_root_base / "lib"
    for package_dir in sorted(lib_root.iterdir()):
        if not package_dir.is_dir():
            continue
        if (package_dir / "src").exists():
            remappings[f"{package_dir.name}/"] = (package_dir / "src").resolve()
        else:
            remappings[f"{package_dir.name}/"] = package_dir.resolve()
        if package_dir.name == "openzeppelin-contracts":
            remappings["@openzeppelin/"] = package_dir.resolve()
    return remappings


def _build_solc_dependency_options(target_path: Path, compile_target_path: Path | None = None) -> tuple[list[str], str]:
    compile_target_path = compile_target_path or target_path
    project_root = find_project_root(target_path)
    import_paths = _read_import_paths_from_project(project_root)

    remap_dirs: dict[str, Path] = {}
    remap_dirs.update(_read_remappings(project_root))
    remap_dirs.update(_collect_local_alias_remappings(project_root, import_paths))
    remap_dirs.update(_collect_lib_remappings(project_root))
    remap_dirs.update(_collect_node_module_remappings(project_root))

    allow_paths = [
        project_root,
        compile_target_path.parent if compile_target_path.is_file() else compile_target_path,
    ]
    allow_paths.extend(remap_dirs.values())
    for node_modules in (
        project_root / "node_modules",
        project_root / ".gptscan" / "npm_vendor" / "node_modules",
    ):
        if node_modules.exists():
            allow_paths.append(node_modules)

    remaps = [f"{prefix}={path.resolve().as_posix().rstrip('/')}/" for prefix, path in sorted(remap_dirs.items())]
    allow_paths_text = ",".join(str(path.resolve()) for path in _dedupe_paths(allow_paths))
    return remaps, f"--allow-paths {allow_paths_text}" if allow_paths_text else ""


def _collect_local_solidity_dependencies(target_path: Path, visited: set[Path] | None = None) -> list[Path]:
    visited = visited or set()
    target_path = target_path.expanduser().resolve()
    if target_path in visited or not target_path.exists():
        return []
    visited.add(target_path)

    dependencies = [target_path]
    source_text = target_path.read_text(encoding="utf-8", errors="ignore")
    for import_path in re.findall(r'^\s*import\s+(?:[^"\']+\s+from\s+)?["\'](\.[^"\']+\.sol)["\'];', source_text, flags=re.MULTILINE):
        dependency = (target_path.parent / import_path).resolve()
        dependencies.extend(_collect_local_solidity_dependencies(dependency, visited))
    return dependencies


def _dependency_common_root(dependencies: list[Path]) -> Path:
    resolved_dirs = [str(path.expanduser().resolve().parent) for path in dependencies]
    if not resolved_dirs:
        raise ValueError("dependencies must not be empty")
    return Path(os.path.commonpath(resolved_dirs))


def _sanitize_foundry_test_source(source_text: str) -> str:
    output_lines: list[str] = []
    skipping_test_contract = False
    brace_balance = 0

    for line in source_text.splitlines():
        if not skipping_test_contract:
            if 'import "forge-std/Test.sol";' in line or "import 'forge-std/Test.sol';" in line:
                continue
            if re.match(r"\s*(?:abstract\s+)?contract\s+\w+.*\bis\b.*\bTest\b.*\{", line):
                skipping_test_contract = True
                brace_balance = line.count("{") - line.count("}")
                if brace_balance <= 0:
                    skipping_test_contract = False
                continue
            output_lines.append(line)
        else:
            brace_balance += line.count("{") - line.count("}")
            if brace_balance <= 0:
                skipping_test_contract = False

    return "\n".join(output_lines) + "\n"


def _prepare_compile_target(target_path: Path) -> Path:
    if not target_path.is_file() or target_path.suffix.lower() != ".sol":
        if target_path.is_dir():
            return _prepare_directory_compile_target(target_path)
        return target_path

    source_text = target_path.read_text(encoding="utf-8", errors="ignore")
    dependencies = _collect_local_solidity_dependencies(target_path)
    should_sanitize = any(
        "forge-std/Test.sol" in dependency.read_text(encoding="utf-8", errors="ignore")
        for dependency in dependencies
    )
    if not should_sanitize:
        return target_path

    sanitized_dir = ensure_project_work_dir(target_path) / "compile_sources"
    if sanitized_dir.exists():
        shutil.rmtree(sanitized_dir)
    sanitized_dir.mkdir(parents=True, exist_ok=True)
    common_root = _dependency_common_root(dependencies)

    for dependency in dependencies:
        dependency_text = dependency.read_text(encoding="utf-8", errors="ignore")
        sanitized_text = _sanitize_foundry_test_source(dependency_text)
        relative_path = dependency.resolve().relative_to(common_root)
        output_path = sanitized_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(sanitized_text, encoding="utf-8")

    return sanitized_dir / target_path.resolve().relative_to(common_root)


def _should_include_project_source_file(project_root: Path, sol_file: Path) -> bool:
    relative_parts = sol_file.resolve().relative_to(project_root.resolve()).parts
    lower_parts = tuple(part.lower() for part in relative_parts[:-1])
    if any(part in EXCLUDED_SOURCE_PARTS for part in lower_parts):
        return False
    lower_name = sol_file.name.lower()
    if lower_name.endswith(".t.sol") or lower_name.endswith(".test.sol"):
        return False
    return True


def _collect_project_source_files(project_root: Path) -> list[Path]:
    source_files: list[Path] = []
    for source_dir_name in SOURCE_DIR_NAMES:
        for source_root in project_root.rglob(source_dir_name):
            if not source_root.is_dir():
                continue
            if any(part.lower() in EXCLUDED_SOURCE_PARTS for part in source_root.relative_to(project_root).parts[:-1]):
                continue
            for sol_file in sorted(source_root.rglob("*.sol")):
                if _should_include_project_source_file(project_root, sol_file):
                    source_files.append(sol_file.resolve())
    if source_files:
        return _dedupe_paths(source_files)

    fallback_files = [
        sol_file.resolve()
        for sol_file in sorted(project_root.rglob("*.sol"))
        if _should_include_project_source_file(project_root, sol_file)
    ]
    return _dedupe_paths(fallback_files)


def _resolve_local_project_import(source_file: Path, import_path: str, project_root: Path) -> Path | None:
    if import_path.startswith("."):
        candidate = (source_file.parent / import_path).resolve()
        return candidate if candidate.exists() else None

    source_roots = [root for root in (project_root / "src", project_root / "contracts") if root.exists()]
    direct_candidate = (project_root / import_path).resolve()
    if direct_candidate.exists():
        return direct_candidate

    for source_root in source_roots:
        nested_candidate = (source_root / import_path).resolve()
        if nested_candidate.exists():
            return nested_candidate
        parts = import_path.split("/")
        if parts and parts[0].startswith("@") and len(parts) >= 2:
            scoped_candidate = (source_root / parts[1] / "/".join(parts[2:])).resolve()
            if scoped_candidate.exists():
                return scoped_candidate
    return None


def _select_compile_entry_files(project_root: Path, source_files: list[Path]) -> list[Path]:
    source_set = {path.resolve() for path in source_files}
    imported_files: set[Path] = set()

    for source_file in source_files:
        try:
            source_text = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for import_path in IMPORT_RE.findall(source_text):
            resolved = _resolve_local_project_import(source_file, import_path, project_root)
            if resolved and resolved in source_set:
                imported_files.add(resolved)

    entry_files = [path for path in source_files if path.resolve() not in imported_files]
    preferred_entries = [
        path
        for path in entry_files
        if "/interfaces/" not in path.as_posix().lower()
        and "/libraries/" not in path.as_posix().lower()
        and not path.name.startswith("I")
    ]
    selected_entries = preferred_entries or entry_files or source_files

    if len(selected_entries) <= 1:
        return selected_entries

    grouped_source_files: dict[str, list[Path]] = {}
    grouped_entries: dict[str, list[Path]] = {}
    basename_groups: dict[str, set[str]] = {}

    def _group_key(path: Path) -> str:
        relative_parent = path.relative_to(project_root).parent
        return relative_parent.as_posix()

    for source_file in source_files:
        key = _group_key(source_file)
        grouped_source_files.setdefault(key, []).append(source_file)
        basename_groups.setdefault(source_file.name, set()).add(key)

    for entry_file in selected_entries:
        grouped_entries.setdefault(_group_key(entry_file), []).append(entry_file)

    has_cross_group_name_collision = any(len(keys) > 1 for keys in basename_groups.values())
    if len(grouped_entries) > 1 and has_cross_group_name_collision:
        best_group = max(
            grouped_entries,
            key=lambda key: (len(grouped_source_files.get(key, [])), len(grouped_entries[key]), key),
        )
        return grouped_entries[best_group]

    return selected_entries


def _collect_workspace_source_files(project_root: Path, seed_files: list[Path]) -> list[Path]:
    project_root = project_root.expanduser().resolve()
    visited: set[Path] = set()
    collected: list[Path] = []

    def visit(source_file: Path) -> None:
        source_file = source_file.expanduser().resolve()
        if source_file in visited or not source_file.exists() or source_file.suffix.lower() != ".sol":
            return
        try:
            relative_parts = source_file.relative_to(project_root).parts[:-1]
        except ValueError:
            return
        if any(part.lower() in EXCLUDED_SOURCE_PARTS for part in relative_parts):
            return

        visited.add(source_file)
        collected.append(source_file)

        try:
            source_text = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        for import_path in IMPORT_RE.findall(source_text):
            resolved = _resolve_local_project_import(source_file, import_path, project_root)
            if resolved is not None:
                visit(resolved)

    for seed_file in seed_files:
        visit(seed_file)
    return collected


def _prepare_directory_compile_target(project_root: Path) -> Path:
    direct_files = [
        file.resolve()
        for file in sorted(project_root.glob("*.sol"))
        if file.is_file() and _should_include_project_source_file(project_root, file)
    ]
    if len(direct_files) == 1:
        return direct_files[0]
    if len(direct_files) > 1:
        return _build_directory_compile_workspace(project_root, direct_files)

    source_files = _collect_project_source_files(project_root)
    if not source_files:
        return project_root
    return _build_directory_compile_workspace(project_root, source_files)


def _build_directory_compile_workspace(project_root: Path, source_files: list[Path]) -> Path:
    project_root = project_root.expanduser().resolve()
    compile_dir = ensure_project_work_dir(project_root) / "compile_sources"
    if compile_dir.exists():
        shutil.rmtree(compile_dir)
    compile_dir.mkdir(parents=True, exist_ok=True)
    entry_files = _select_compile_entry_files(project_root, source_files)
    workspace_files = _collect_workspace_source_files(project_root, source_files)

    for source_file in workspace_files:
        relative_path = source_file.relative_to(project_root)
        output_path = compile_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(source_file.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    wrapper_lines = [
        "// Auto-generated by GPTScan to compile a project-style directory.",
    ]
    for source_file in entry_files:
        relative_path = source_file.relative_to(project_root).as_posix()
        wrapper_lines.append(f'import "./{relative_path}";')
    wrapper_lines.append("")

    wrapper_path = compile_dir / "__gptscan_entry__.sol"
    wrapper_path.write_text("\n".join(wrapper_lines), encoding="utf-8")
    return wrapper_path


def _restore_original_result_paths(result_payload: dict, sanitized_root: Path, original_root: Path) -> None:
    sanitized_root = sanitized_root.expanduser().resolve()
    original_root = original_root.expanduser().resolve()
    for result in result_payload.get("results", []):
        for affected_file in result.get("affectedFiles", []):
            file_path = affected_file.get("filePath")
            if not file_path:
                continue
            resolved = Path(file_path).expanduser().resolve()
            try:
                relative_path = resolved.relative_to(sanitized_root)
            except ValueError:
                continue
            affected_file["filePath"] = str((original_root / relative_path).resolve())

def _do_load_config(config_path: str):
    with open(TASKS_DIR / config_path, "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config


def load_config(config_name: str):
    if (TASKS_DIR / f"{config_name}.yml").exists():
        path = TASKS_DIR / f"{config_name}.yml"
    elif (TASKS_DIR / f"{config_name}.yaml").exists():
        path = TASKS_DIR / f"{config_name}.yaml"
    else:
        raise FileNotFoundError("No such file: {}".format(config_name))
    return _do_load_config(path.name)


def load_configs(config_names: list):
    configs = []
    for config_name in config_names:
        configs.append(load_config(config_name))
    return configs


def load_all_configs():
    configs = []
    if not TASKS_DIR.exists():
        return configs
    for file in os.listdir(TASKS_DIR):
        if file.endswith(".yml") or file.endswith(".yaml"):
            configs.append(_do_load_config(file))
    return configs


def load_rule(rule_indexs: List[int]):
    result = []
    for rule in rule_indexs:
        rule_path = RULES_DIR / f"{rule}.yml"
        if rule_path.exists():
            result.append(yaml.load(
                open(rule_path, "r", encoding="utf-8"), Loader=yaml.FullLoader))
        else:
            raise FileNotFoundError("No such file: {}".format(rule))
    return result


def load_all_rules():
    result = []
    for file in os.listdir(RULES_DIR):
        if file.endswith(".yml"):
            result.append(
                yaml.load(open(RULES_DIR / file, "r", encoding="utf-8"), Loader=yaml.FullLoader))
    return result


def compile_project(abs_path:str, solc_version: str | None = None):
    # with Progress(transient=True) as progress:
    #     task = progress.add_task("Compiling", total=None, start=False)
    #     data = {
    #         "version": "0.0.1",
    #         "user": {
    #             "project": {
    #                 "workspace": f"{abs_path}"
    #             },
    #             "operation": ["detection", "dependency", "compile"],
    #             "output_format": ["standard", "compatible-ast"],
    #             "output_path": f"{os.path.join(abs_path, 'ast')}"
    #         }
    #     }
    #     json.dump(data, open(os.path.join(abs_path, 'parse-config.json'), "w"))
    #     output = subprocess.check_output(['mt-parsing', 'parse-config.json'], cwd=os.path.abspath(abs_path))
    #     if len(os.listdir(os.path.join(abs_path, "ast", "standard"))) > 0:
    #         return True
    #     else:
    #         logger.error(output)
    #         return False
    target_path = Path(abs_path).expanduser().resolve()
    compile_target_path = _prepare_compile_target(target_path)
    falcon_kwargs = {}
    if solc_version:
        solc_binary = Path.home() / ".solc-select" / "artifacts" / f"solc-{solc_version}" / f"solc-{solc_version}"
        if not solc_binary.exists():
            raise CompileFailure(f"Selected solc binary is missing: {solc_binary}")
        falcon_kwargs["solc"] = str(solc_binary)
    solc_remaps, solc_args = _build_solc_dependency_options(target_path, compile_target_path)
    if solc_remaps:
        falcon_kwargs["solc_remaps"] = solc_remaps
    if solc_args:
        falcon_kwargs["solc_args"] = solc_args
    if compile_target_path.is_file():
        falcon_kwargs["solc_working_dir"] = str(compile_target_path.parent)
        return falcon.Falcon(str(compile_target_path), **falcon_kwargs)
    files = os.listdir(target_path)
    files = list(filter(lambda x: x.endswith(".sol") and os.path.isfile(os.path.join(target_path,x)), files))
    if len(files) == 1:
        falcon_kwargs["solc_working_dir"] = str(target_path)
        return falcon.Falcon(os.path.join(target_path, files[0]), **falcon_kwargs)
    falcon_kwargs["solc_working_dir"] = str(target_path)
    return falcon.Falcon(str(target_path), **falcon_kwargs)


def run_scan(source_dir: str, output_file: str, gptkey: str | None, solc_version: str | None = None):
    start_time = time.time()
    source_dir = str(Path(source_dir).expanduser().resolve())
    output_file = str(ensure_parent_dir(output_file))
    source_path = Path(source_dir)
    analysis_source_dir = source_dir
    prepared_target = None
    original_result_root = source_path.parent if source_path.is_file() else source_path
    if source_path.is_file() or source_path.is_dir():
        prepared_target = _prepare_compile_target(source_path)
        if prepared_target != source_path:
            analysis_source_dir = str(prepared_target.parent)

    if gptkey:
        os.environ["OPENAI_API_KEY"] = gptkey
    configure_solc_version(solc_version)

    scan_rules = load_all_rules()
    console.log(f"Loaded [bold green]{len(scan_rules)}[/bold green] rules")

    try:
        falcon_instance = compile_project(source_dir, solc_version=solc_version)
    except Exception as exc:
        console.log(traceback.format_exc())
        raise CompileFailure(f"Compile failed for {source_dir}: {exc}") from exc

    import analyze_pipeline
    import chatgpt_api

    chatgpt_api.reset_token_counters()
    res, cg, meta_data = analyze_pipeline.ask_whether_has_vul_with_scenario_v9(
        analysis_source_dir, scan_rules
    )
    final_result = {}
    for file in res:
        with open(file, encoding="utf-8", errors="ignore") as f:
            source = f.read().splitlines()
            for contract in res[file]:
                for function1 in res[file][contract]:
                    function1_tmp_result = {}
                    for function2 in res[file][contract][function1]:
                        confirmed_vuls = {}
                        for vul in res[file][contract][function1][function2]["data"]:
                            meta_data["rules_types_for_static"].add(vul["name"])
                            if "static" in vul:
                                if vul["name"] not in function1_tmp_result:
                                    function1_detail = cg.get_function_detail(file, contract, function1)
                                    function1_text = "\n".join(
                                        open(file, encoding="utf-8", errors="ignore")
                                        .read()
                                        .splitlines()[
                                            int(function1_detail["loc"]["start"].split(":")[0]) - 1 : int(
                                                function1_detail["loc"]["end"].split(":")[0]
                                            )
                                        ]
                                    )
                                    try:
                                        args = []
                                        checker = vul["static"]["rule"]["name"]
                                        if "multisteps" in vul["static"] and vul["static"]["multisteps"] == True:
                                            answer = analyze_pipeline.ask_for_static_multistep(
                                                vul["static"]["prompt"],
                                                function1_text,
                                                vul["static"]["output_keys"],
                                            )
                                            if "filter" in vul["static"]:
                                                for filter_variable in vul["static"]["filter"]:
                                                    if filter_variable in answer:
                                                        for var in answer[filter_variable].copy():
                                                            var_remove_flag = True
                                                            for target_feature in vul["static"]["filter"][filter_variable]:
                                                                if target_feature.lower() in var.lower():
                                                                    var_remove_flag = False
                                                                    break
                                                            if var_remove_flag == True:
                                                                answer[filter_variable].remove(var)
                                                    else:
                                                        raise Exception("Filter variable not found")
                                        else:
                                            if "format" in vul["static"] and vul["static"]["format"] == "json":
                                                answer, raw = analyze_pipeline.ask_for_static_json(
                                                    vul["static"]["prompt"],
                                                    function1_text,
                                                    vul["static"]["output_keys"],
                                                )
                                                _validate_static_answer(vul, answer, raw)
                                            elif "format" in vul["static"] and vul["static"]["format"] == "json_single":
                                                answer = analyze_pipeline.ask_for_static_json_single(
                                                    vul["static"]["prompt"],
                                                    function1_text,
                                                    vul["static"]["output_keys"][0],
                                                )
                                            elif "format" in vul["static"] and vul["static"]["format"] == "not_need":
                                                pass
                                            else:
                                                answer = analyze_pipeline.ask_for_static(
                                                    vul["static"]["prompt"],
                                                    function1_text,
                                                    vul["static"]["output_keys"],
                                                )

                                        if "multisteps" not in vul["static"] or vul["static"]["multisteps"] == False:
                                            for arg in vul["static"]["rule"]["args"]:
                                                if "CONSTANT" in arg:
                                                    args.append(arg["CONSTANT"])
                                                else:
                                                    if "format" in vul["static"] and vul["static"]["format"] == "json" or vul["static"]["format"] == "json_single":
                                                        args.append(answer[arg])
                                                    elif "format" in vul["static"] and vul["static"]["format"] == "not_need":
                                                        args = list(map(lambda x: x["constant"], vul["static"]["args"]))
                                                    else:
                                                        args.append(answer[arg].split(" ")[0])
                                        else:
                                            for arg in vul["static"]["rule"]["args"]:
                                                if "CONSTANT" in arg:
                                                    args.append(arg["CONSTANT"])
                                                else:
                                                    args.append(answer[arg])

                                        res_1 = static_check.run_static_check(
                                            checker, args, function1, falcon_instance, function1_text
                                        )
                                        function1_tmp_result[vul["name"]] = res_1
                                    except _StaticValidationError as exc:
                                        logger.info("Static validation rejected candidate: %s", exc)
                                        function1_tmp_result[vul["name"]] = False
                                    except Exception:
                                        logger.error("Static analysis failed: Invalid args")
                                        logger.error(
                                            f"Current File: {file}, current function: {function1}, current vul: {vul['name']}"
                                        )
                                        logger.error(traceback.format_exc())
                                        function1_tmp_result[vul["name"]] = False

                                res_2 = None
                                if function2 == "__ONLY_FUNCTION__":
                                    res_2 = False
                                else:
                                    try:
                                        args = []
                                        checker = vul["static"]["rule"]["name"]
                                        function2_splitted = function2.split("!!!")
                                        function2_file = function2_splitted[0]
                                        function2_contract = function2_splitted[1]
                                        function2_func = function2_splitted[2]
                                        function2_detail = cg.get_function_detail(
                                            function2_file, function2_contract, function2_func
                                        )
                                        function2_text = "\n".join(
                                            open(function2_file, encoding="utf-8", errors="ignore")
                                            .read()
                                            .splitlines()[
                                                int(function2_detail["loc"]["start"].split(":")[0]) - 1 : int(
                                                    function2_detail["loc"]["end"].split(":")[0]
                                                )
                                            ]
                                        )
                                        if "multisteps" in vul["static"] and vul["static"]["multisteps"] == True:
                                            answer = analyze_pipeline.ask_for_static_multistep(
                                                vul["static"]["prompt"],
                                                function2_text,
                                                vul["static"]["output_keys"],
                                            )
                                        else:
                                            if "format" in vul["static"] and vul["static"]["format"] == "json":
                                                answer, raw = analyze_pipeline.ask_for_static_json(
                                                    vul["static"]["prompt"],
                                                    function2_text,
                                                    vul["static"]["output_keys"],
                                                )
                                                _validate_static_answer(vul, answer, raw)
                                            elif "format" in vul["static"] and vul["static"]["format"] == "json_single":
                                                answer = analyze_pipeline.ask_for_static_json_single(
                                                    vul["static"]["prompt"],
                                                    function2_text,
                                                    vul["static"]["output_keys"][0],
                                                )
                                            elif "format" in vul["static"] and vul["static"]["format"] == "not_need":
                                                pass
                                            else:
                                                answer = analyze_pipeline.ask_for_static(
                                                    vul["static"]["prompt"],
                                                    function2_text,
                                                    vul["static"]["output_keys"],
                                                )

                                        if "multisteps" not in vul["static"] or vul["static"]["multisteps"] == False:
                                            for arg in vul["static"]["rule"]["args"]:
                                                if "CONSTANT" in arg:
                                                    args.append(arg["CONSTANT"])
                                                else:
                                                    if "format" in vul["static"] and vul["static"]["format"] == "json" or vul["static"]["format"] == "json_single":
                                                        args.append(answer[arg])
                                                    elif "format" in vul["static"] and vul["static"]["format"] == "not_need":
                                                        args = list(map(lambda x: x["constant"], vul["static"]["args"]))
                                                    else:
                                                        args.append(answer[arg].split(" ")[0])
                                        else:
                                            for arg in vul["static"]["rule"]["args"]:
                                                if "CONSTANT" in arg:
                                                    args.append(arg["CONSTANT"])
                                                else:
                                                    args.append(answer[arg])
                                        res_2 = static_check.run_static_check(
                                            checker, args, function2_func, falcon_instance, function2_text
                                        )
                                    except _StaticValidationError as exc:
                                        logger.info("Static validation rejected candidate: %s", exc)
                                        res_2 = False
                                    except Exception:
                                        logger.error("Static analysis failed: Invalid args")
                                        logger.error(
                                            f"Current File: {file}, current function: {function1}, current vul: {vul['name']}"
                                        )
                                        logger.error(traceback.format_exc())
                                        res_2 = False

                                confirmed_vuls[vul["name"]] = {
                                    "StaticAnalysis": function1_tmp_result[vul["name"]] or res_2
                                }
                            else:
                                confirmed_vuls[vul["name"]] = {"StaticAnalysis": "Not Needed"}
                        if len(confirmed_vuls) > 0:
                            if file not in final_result:
                                final_result[file] = {}
                            if contract not in final_result[file]:
                                final_result[file][contract] = {}
                            if function1 not in final_result[file][contract]:
                                final_result[file][contract][function1] = {}
                            final_result[file][contract][function1][function2] = confirmed_vuls

    num_true = 0
    num_false = 0
    for file_, file_data_ in final_result.items():
        for contract_, contract_data_ in file_data_.items():
            for function1_, function1_data_ in contract_data_.items():
                for function2_, function2_data_ in function1_data_.items():
                    for vul_, vul_data_ in function2_data_.items():
                        if "StaticAnalysis" in vul_data_:
                            if vul_data_["StaticAnalysis"] == False:
                                num_false += 1
                            else:
                                meta_data["files_after_static"].add(file_)
                                meta_data["contracts_after_static"].add(file_ + "!!!" + contract_)
                                meta_data["functions_after_static"].add(file_ + "!!!" + contract_ + "!!!" + function1_)
                                if function2_ != "__ONLY_FUNCTION__":
                                    meta_data["files_after_static"].add(function2_.split("!!!")[0])
                                    meta_data["contracts_after_static"].add(
                                        function2_.split("!!!")[0] + "!!!" + function2_.split("!!!")[1]
                                    )
                                    meta_data["functions_after_static"].add(function2_)
                                meta_data["rules_types_after_static"].add(vul_)
                                num_true += 1

    output_json = utils.convert_output(final_result, scan_rules, cg, analysis_source_dir)
    if prepared_target is not None and prepared_target != source_path:
        _restore_original_result_paths(output_json, prepared_target.parent, original_result_root)

    meta_data["used_time"] = time.time() - start_time
    meta_data["vul_before_static"] = num_true + num_false
    meta_data["vul_after_static"] = num_true
    meta_data["vul_after_merge"] = len(output_json["results"])
    meta_data["token_sent"] = chatgpt_api.tokens_sent.value
    meta_data["token_received"] = chatgpt_api.tokens_received.value
    meta_data["token_sent_gpt4"] = chatgpt_api.tokens_sent_gpt4.value
    meta_data["token_received_gpt4"] = chatgpt_api.tokens_received_gpt4.value
    meta_data["estimated_cost"] = (
        (meta_data["token_sent"] * global_config.SEND_PRICE)
        + (meta_data["token_received"] * global_config.RECEIVE_PRICE)
        + (meta_data["token_sent_gpt4"] * global_config.GPT4_SEND_PRICE)
        + (meta_data["token_received_gpt4"] * global_config.GPT4_RECEIVE_PRICE)
    )
    meta_data["status"] = "success"

    for metadata_key, metadata_value in meta_data.copy().items():
        if isinstance(metadata_value, set):
            meta_data[metadata_key] = len(metadata_value)

    summary_table = Table(title="Summary")
    summary_table.add_column("Key")
    summary_table.add_column("Value")
    summary_table.add_row("Files", str(meta_data["files"]))
    summary_table.add_row("Contracts", str(meta_data["contracts"]))
    summary_table.add_row("Functions", str(meta_data["functions"]))
    summary_table.add_row("Lines of Code", str(meta_data["loc"]))
    summary_table.add_row("Used Time", str(meta_data["used_time"]))
    summary_table.add_row("Estimated Cost (USD)", str(meta_data["estimated_cost"]))
    console.print(summary_table)

    json.dump(output_json, open(output_file, "w", encoding="utf-8"), indent=4)
    json.dump(meta_data, open(output_file + ".metadata.json", "w", encoding="utf-8"), indent=4)
    return output_json, meta_data


def simple_cli():
    parser = argparse.ArgumentParser(
                    prog='GPTScan',
                    description='GPTScan is an AI based smart contract vulnerability scanner.')
    parser.add_argument("-s", "--source", help="The source code directory", required=True)
    # not need ast, compile first
    # parser.add_argument("-a", "--ast", help="The AST directory", required=True)
    parser.add_argument("-o", "--output", help="The output file", required=True)
    parser.add_argument("-k", "--gptkey", help="The OpenAI API key", required=True)
    args = parser.parse_args()
    run_scan(args.source, args.output, args.gptkey)
