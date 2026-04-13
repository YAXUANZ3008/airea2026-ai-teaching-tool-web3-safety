#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from batch_scan_demo import SUMMARY_COLUMNS, output_name_for_target
from project_dependencies import ensure_project_dependencies
from scan_runner import scan_project_to_file
from solidity_version import detect_project_pragma, prepare_solc_for_project


def _metadata_path(output_path: Path) -> Path:
    return Path(str(output_path) + ".metadata.json")


def _load_summary_row(result_json: Path) -> dict:
    metadata_path = _metadata_path(result_json)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    result_payload = json.loads(result_json.read_text(encoding="utf-8")) if result_json.exists() else {"results": []}
    project_name = result_json.stem
    return {
        "project_name": project_name,
        "detected_pragma": metadata.get("detected_pragma", ""),
        "status": metadata.get("status", "unknown"),
        "result_count": metadata.get("result_count", len(result_payload.get("results", []))),
        "token_sent": metadata.get("token_sent", 0),
        "token_received": metadata.get("token_received", 0),
        "used_time": metadata.get("used_time", 0),
    }


def _iter_failed_project_names(results_dir: Path) -> list[str]:
    project_names: list[str] = []
    for metadata_file in sorted(results_dir.glob("*.json.metadata.json")):
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if metadata.get("status") != "success":
            project_names.append(metadata_file.name.removesuffix(".json.metadata.json"))
    return project_names


def _classify_failure(metadata: dict) -> str:
    status = metadata.get("status", "")
    message = metadata.get("error_message", "")
    if status == "llm_api_failed":
        return "llm_api_failed"
    if status == "skipped_unsupported_version" or "Project pragma is not supported" in message:
        return "unsupported_version"
    if "Stack too deep" in message:
        return "stack_too_deep"
    if "Dependency bootstrap failed" in message and ("ERESOLVE" in message or "peer" in message):
        return "peer_conflict"
    if "Dependency bootstrap failed" in message and ('engine "node" is incompatible' in message or "Found incompatible module" in message):
        return "node_engine"
    if "Dependency bootstrap failed" in message and ('Unsupported URL Type "yarn:"' in message or "EUNSUPPORTEDPROTOCOL" in message):
        return "yarn_protocol"
    if "Dependency bootstrap failed" in message and ("git ls-remote" in message or "git@github.com" in message or "git://github.com" in message):
        return "git_dependency"
    if "Dependency bootstrap failed" in message and ("ENOTFOUND" in message or "registry.yarnpkg.com" in message or "registry.npmjs.org" in message):
        return "network_registry"
    if status == "parse_failed":
        return "dependency_other"
    if "not found: File not found" in message:
        return "missing_imports"
    if status == "compile_failed":
        return "compile_other"
    return status or "unknown"


def _is_fixable_category(category: str) -> bool:
    return category in {
        "llm_api_failed",
        "peer_conflict",
        "node_engine",
        "yarn_protocol",
        "git_dependency",
        "network_registry",
        "dependency_other",
        "missing_imports",
        "compile_other",
    }


def _iter_fixable_failed_project_names(results_dir: Path) -> list[str]:
    project_names: list[str] = []
    for metadata_file in sorted(results_dir.glob("*.json.metadata.json")):
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        category = _classify_failure(metadata)
        if _is_fixable_category(category):
            project_names.append(metadata_file.name.removesuffix(".json.metadata.json"))
    return project_names


def _rewrite_csvs(results_dir: Path) -> None:
    summary_rows = []
    failed_rows = []

    for result_json in sorted(results_dir.glob("*.json")):
        if result_json.name.endswith(".metadata.json"):
            continue
        row = _load_summary_row(result_json)
        summary_rows.append(row)
        metadata = json.loads(_metadata_path(result_json).read_text(encoding="utf-8"))
        if metadata.get("status") not in {"success", "skipped_unsupported_version"}:
            failed_rows.append(
                {
                    "project_name": result_json.stem,
                    "detected_pragma": metadata.get("detected_pragma", ""),
                    "status": metadata.get("status", "unknown"),
                    "error_message": metadata.get("error_message", ""),
                }
            )

    with open(results_dir / "summary.csv", "w", encoding="utf-8", newline="") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(summary_rows)

    with open(results_dir / "failed.csv", "w", encoding="utf-8", newline="") as failed_file:
        writer = csv.DictWriter(failed_file, fieldnames=["project_name", "detected_pragma", "status", "error_message"])
        writer.writeheader()
        writer.writerows(failed_rows)


def _resolve_target(dataset_dir: Path, project_name: str) -> Path | None:
    target = dataset_dir / project_name
    if target.exists():
        return target
    sol_target = dataset_dir / f"{project_name}.sol"
    if sol_target.exists():
        return sol_target
    return None


def _prebootstrap_targets(targets: Iterable[tuple[str, Path]]) -> None:
    targets = list(targets)
    print(f"prebootstrap_count={len(targets)}")
    for index, (project_name, target) in enumerate(targets, start=1):
        pragma = detect_project_pragma(target)
        if not pragma.found or not pragma.supported or not target.is_dir():
            continue
        try:
            solc_version = prepare_solc_for_project(target, pragma)
            print(f"[pre {index}/{len(targets)}] deps={project_name} solc={solc_version}")
            ensure_project_dependencies(target, solc_version)
        except Exception as exc:  # noqa: BLE001
            print(f"[pre {index}/{len(targets)}] deps_failed={project_name} reason={str(exc)[:220]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerun only failed GPTScan results and overwrite their outputs.")
    parser.add_argument("--dataset-dir", required=True, help="Original dataset root directory")
    parser.add_argument("--results-dir", required=True, help="Existing results directory to update in place")
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="OpenRouter API key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--all-failed",
        action="store_true",
        help="Rerun every failed project, including currently unsupported or likely unfixable ones.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    results_dir = Path(args.results_dir).expanduser().resolve()
    failed_names = _iter_failed_project_names(results_dir) if args.all_failed else _iter_fixable_failed_project_names(results_dir)
    targets: list[tuple[str, Path]] = []
    skipped_missing = 0
    for project_name in failed_names:
        target = _resolve_target(dataset_dir, project_name)
        if target is None:
            skipped_missing += 1
            continue
        targets.append((project_name, target))

    _prebootstrap_targets(targets)

    print(f"rerun_count={len(targets)}")
    if skipped_missing:
        print(f"skip_missing_count={skipped_missing}")
    for index, (project_name, target) in enumerate(targets, start=1):
        output_json = results_dir / f"{output_name_for_target(target)}.json"
        pragma = detect_project_pragma(target)
        print(f"[{index}/{len(targets)}] rerun={project_name} pragma={pragma.detected_pragma}")
        scan_project_to_file(target, output_json, args.api_key)

    _rewrite_csvs(results_dir)
    print(f"summary_csv={results_dir / 'summary.csv'}")
    print(f"failed_csv={results_dir / 'failed.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
