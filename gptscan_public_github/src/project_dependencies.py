from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


PACKAGE_MANAGER_FILES = {
    "npm": "package-lock.json",
    "yarn": "yarn.lock",
    "pnpm": "pnpm-lock.yaml",
}
PROJECT_MARKERS = (
    "package.json",
    "foundry.toml",
    "hardhat.config.js",
    "hardhat.config.ts",
    "truffle-config.js",
    "remappings.txt",
)
DESCENDANT_IGNORED_DIRS = {
    ".git",
    ".github",
    ".gptscan",
    "artifacts",
    "broadcast",
    "cache",
    "discord-export",
    "docs",
    "echidna",
    "lib",
    "mock",
    "mocks",
    "node_modules",
    "out",
    "outside-scope",
    "report",
    "reports",
    "resource",
    "resources",
    "script",
    "scripts",
    "test",
    "tests",
}
BOOTSTRAP_STAMP = ".gptscan/dependencies.ready"
INFERRED_VENDOR_DIR = ".gptscan/npm_vendor"
IMPORT_RE = re.compile(r'^\s*import\s+(?:[^"\']+\s+from\s+)?["\']([^"\']+)["\'];', re.MULTILINE)

KNOWN_IMPORT_PACKAGES = {
    "@openzeppelin/contracts-upgradeable/": "@openzeppelin/contracts-upgradeable",
    "@openzeppelin/contracts/": "@openzeppelin/contracts",
    "@uniswap/lib/": "@uniswap/lib",
    "@chainlink/": "@chainlink/contracts",
    "forge-std/": "forge-std",
    "ds-test/": "ds-test",
}

FOUNDRY_LIB_PACKAGE_DIRS = {
    "forge-std": ("forge-std",),
    "ds-test": ("ds-test",),
    "@openzeppelin/contracts": ("openzeppelin-contracts",),
    "@openzeppelin/contracts-upgradeable": ("openzeppelin-contracts-upgradeable",),
    "@chainlink/contracts": ("chainlink", "chainlink-contracts"),
    "@uniswap/lib": ("uniswap-lib", "lib"),
}


@dataclass
class DependencyBootstrapResult:
    package_manager: str | None
    installed: bool
    skipped: bool
    message: str = ""


def _has_any(path: Path, names: tuple[str, ...]) -> bool:
    return any((path / name).exists() for name in names)


def _has_source_layout(path: Path) -> bool:
    return any((path / dirname).is_dir() for dirname in ("contracts", "src"))


def _iter_descendant_project_roots(base: Path, max_depth: int = 3):
    for root, dirs, _files in os.walk(base):
        root_path = Path(root)
        try:
            rel_parts = root_path.relative_to(base).parts
        except ValueError:
            continue
        depth = len(rel_parts)
        dirs[:] = [name for name in dirs if name.lower() not in DESCENDANT_IGNORED_DIRS]
        if depth > max_depth:
            dirs[:] = []
            continue
        if _has_any(root_path, PROJECT_MARKERS):
            yield root_path


def find_project_root(project_dir: str | Path) -> Path:
    path = Path(project_dir).expanduser().resolve()
    base = path if path.is_dir() else path.parent
    for candidate in [base, *base.parents]:
        if _has_any(candidate, PROJECT_MARKERS):
            return candidate

    descendant_candidates = list(_iter_descendant_project_roots(base))
    if descendant_candidates:
        descendant_candidates.sort(
            key=lambda candidate: (
                0 if _has_source_layout(candidate) else 1,
                len(candidate.relative_to(base).parts),
            )
        )
        return descendant_candidates[0]
    return base


def detect_package_manager(project_root: str | Path) -> str | None:
    root = Path(project_root).expanduser().resolve()
    for manager, filename in PACKAGE_MANAGER_FILES.items():
        if (root / filename).exists():
            return manager
    if (root / "package.json").exists():
        return "npm"
    return None


def _resolve_package_manager_commands(project_root: Path, manager: str) -> list[list[str]]:
    if manager == "pnpm" and shutil.which("pnpm"):
        return [
            ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"],
            ["pnpm", "install", "--ignore-scripts"],
        ]
    if manager == "yarn":
        if shutil.which("yarn"):
            return [
                ["yarn", "install", "--immutable", "--ignore-scripts", "--non-interactive"],
                ["yarn", "install", "--immutable", "--ignore-scripts", "--non-interactive", "--ignore-engines"],
                ["yarn", "install", "--ignore-scripts", "--non-interactive", "--ignore-engines"],
                ["yarn", "install", "--ignore-scripts", "--non-interactive"],
            ]
        if shutil.which("corepack"):
            return [
                ["corepack", "yarn", "install", "--immutable", "--ignore-scripts", "--non-interactive"],
                ["corepack", "yarn", "install", "--immutable", "--ignore-scripts", "--non-interactive", "--ignore-engines"],
                ["corepack", "yarn", "install", "--ignore-scripts", "--non-interactive", "--ignore-engines"],
                ["corepack", "yarn", "install", "--ignore-scripts", "--non-interactive"],
            ]
    return [
        ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts"],
        ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", "--legacy-peer-deps"],
    ]


def _base_install_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    env.setdefault("npm_config_audit", "false")
    env.setdefault("npm_config_fund", "false")
    env.setdefault("npm_config_ignore_scripts", "true")
    env.setdefault("ADBLOCK", "1")
    env.setdefault("DISABLE_OPENCOLLECTIVE", "1")
    env.setdefault("HARDHAT_DISABLE_TELEMETRY_PROMPT", "true")
    env.setdefault("HARDHAT_DISABLE_TELEMETRY", "true")
    env.setdefault("YARN_ENABLE_IMMUTABLE_INSTALLS", "true")
    env.setdefault("YARN_ENABLE_SCRIPTS", "false")
    env.setdefault("YARN_IGNORE_ENGINES", "1")
    env.setdefault("npm_config_engine_strict", "false")
    env.setdefault("GIT_CONFIG_COUNT", "3")
    env.setdefault("GIT_CONFIG_KEY_0", "url.https://github.com/.insteadOf")
    env.setdefault("GIT_CONFIG_VALUE_0", "ssh://git@github.com/")
    env.setdefault("GIT_CONFIG_KEY_1", "url.https://github.com/.insteadOf")
    env.setdefault("GIT_CONFIG_VALUE_1", "git@github.com:")
    env.setdefault("GIT_CONFIG_KEY_2", "url.https://github.com/.insteadOf")
    env.setdefault("GIT_CONFIG_VALUE_2", "git://github.com/")
    return env


def _run_install(command: list[str], project_root: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=str(project_root),
        env=_base_install_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Dependency bootstrap failed in {project_root} with {' '.join(command)}: {output}"
        )
    return (completed.stdout or completed.stderr or "").strip()[:400]


def _run_install_with_fallbacks(commands: list[list[str]], project_root: Path) -> str:
    last_error: RuntimeError | None = None
    for command in commands:
        try:
            return _run_install(command, project_root)
        except RuntimeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Dependency bootstrap failed in {project_root}: no install command available")


def _iter_project_solidity_files(project_root: Path):
    ignored = {
        ".git",
        ".github",
        ".gptscan",
        "artifacts",
        "broadcast",
        "cache",
        "discord-export",
        "docs",
        "echidna",
        "mock",
        "mocks",
        "node_modules",
        "out",
        "outside-scope",
        "report",
        "reports",
        "resource",
        "resources",
        "script",
        "scripts",
        "test",
        "tests",
    }
    for sol_file in sorted(project_root.rglob("*.sol")):
        if any(part.lower() in ignored for part in sol_file.parts):
            continue
        yield sol_file


def _select_known_package_version(package_name: str, solc_version: str | None) -> str:
    if package_name == "@uniswap/lib":
        return "@uniswap/lib@4.0.1-alpha"
    if package_name == "@chainlink/contracts":
        return "@chainlink/contracts@0.2.2"
    if package_name == "forge-std":
        return "forge-std@1.9.6"
    if package_name == "ds-test":
        return "ds-test@0.0.1"
    if package_name in {"@openzeppelin/contracts", "@openzeppelin/contracts-upgradeable"}:
        if solc_version and solc_version.startswith("0.7."):
            return f"{package_name}@3.4.0-solc-0.7"
        if solc_version and solc_version.startswith("0.8."):
            patch = int(solc_version.split(".")[2])
            if patch <= 9:
                return f"{package_name}@4.3.1"
            if patch <= 19:
                return f"{package_name}@4.9.6"
        return f"{package_name}@4.9.6"
    return package_name


def _has_foundry_lib_package(project_root: Path, package_name: str) -> bool:
    lib_root = project_root / "lib"
    if not lib_root.is_dir():
        return False
    package_dirs = FOUNDRY_LIB_PACKAGE_DIRS.get(package_name, ())
    for dirname in package_dirs:
        candidate = lib_root / dirname
        if candidate.exists():
            return True
    return False


def _has_node_module_package(project_root: Path, package_name: str) -> bool:
    package_dir = project_root / "node_modules" / package_name
    if package_dir.exists():
        return True
    if package_name.startswith("@"):
        parts = package_name.split("/", 1)
        if len(parts) == 2 and (project_root / "node_modules" / parts[0] / parts[1]).exists():
            return True
    return False


def _has_vendor_package(project_root: Path, package_name: str) -> bool:
    vendor_root = project_root / INFERRED_VENDOR_DIR / "node_modules"
    package_dir = vendor_root / package_name
    if package_dir.exists():
        return True
    if package_name.startswith("@"):
        parts = package_name.split("/", 1)
        if len(parts) == 2 and (vendor_root / parts[0] / parts[1]).exists():
            return True
    return False


def _package_already_available(project_root: Path, package_name: str) -> bool:
    return (
        _has_node_module_package(project_root, package_name)
        or _has_vendor_package(project_root, package_name)
        or _has_foundry_lib_package(project_root, package_name)
    )


def _ensure_vendor_root(project_root: Path) -> Path:
    vendor_root = project_root / INFERRED_VENDOR_DIR
    vendor_root.mkdir(parents=True, exist_ok=True)
    package_json = vendor_root / "package.json"
    if not package_json.exists():
        package_json.write_text(
            '{\n  "name": "gptscan-vendor",\n  "private": true,\n  "license": "UNLICENSED"\n}\n',
            encoding="utf-8",
        )
    return vendor_root


def _detect_missing_known_packages(project_root: Path, solc_version: str | None) -> list[str]:
    imports: set[str] = set()
    for sol_file in _iter_project_solidity_files(project_root):
        try:
            text = sol_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports.update(match.group(1) for match in IMPORT_RE.finditer(text))

    packages: list[str] = []
    for prefix, package_name in KNOWN_IMPORT_PACKAGES.items():
        if not any(import_path.startswith(prefix) for import_path in imports):
            continue
        if _package_already_available(project_root, package_name):
            continue
        packages.append(_select_known_package_version(package_name, solc_version))
    return packages


def ensure_project_dependencies(project_dir: str | Path, solc_version: str | None = None) -> DependencyBootstrapResult:
    project_root = find_project_root(project_dir)
    stamp_path = project_root / BOOTSTRAP_STAMP
    has_package_json = (project_root / "package.json").exists()
    inferred_packages = _detect_missing_known_packages(project_root, solc_version)
    existing_node_modules = (project_root / "node_modules").exists()

    if not has_package_json and not inferred_packages:
        return DependencyBootstrapResult(package_manager=None, installed=False, skipped=True)
    if existing_node_modules and not inferred_packages:
        return DependencyBootstrapResult(
            package_manager=detect_package_manager(project_root),
            installed=False,
            skipped=True,
            message="node_modules already exists",
        )

    package_manager = detect_package_manager(project_root) or "npm"
    messages: list[str] = []
    if has_package_json:
        commands = _resolve_package_manager_commands(project_root, package_manager)
        messages.append(_run_install_with_fallbacks(commands, project_root))
    if inferred_packages:
        vendor_root = _ensure_vendor_root(project_root)
        install_cmds = [
            ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", *inferred_packages],
            ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", "--legacy-peer-deps", *inferred_packages],
        ]
        messages.append(_run_install_with_fallbacks(install_cmds, vendor_root))

    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text("ready\n", encoding="utf-8")

    return DependencyBootstrapResult(
        package_manager=package_manager,
        installed=True,
        skipped=False,
        message=" | ".join(message for message in messages if message)[:400],
    )
