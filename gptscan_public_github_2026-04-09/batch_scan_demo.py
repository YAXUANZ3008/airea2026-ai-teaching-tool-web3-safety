#!/usr/bin/env python3
import argparse
import csv
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scan_runner import scan_project_to_file
from solidity_version import detect_project_pragma


SUMMARY_COLUMNS = [
    "project_name",
    "detected_pragma",
    "status",
    "result_count",
    "token_sent",
    "token_received",
    "used_time",
]


def iter_scan_targets(dataset_dir: Path):
    for child in sorted(dataset_dir.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            yield child
        elif child.is_file() and child.suffix.lower() == ".sol":
            yield child


def output_name_for_target(target: Path) -> str:
    return target.stem if target.suffix.lower() == ".sol" else target.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reduced GPTScan demo batch flow on direct dataset children.")
    parser.add_argument(
        "--dataset-dir",
        default=str(REPO_ROOT / "GPTScan-Top200-dev"),
        help="Dataset root directory",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "demo_batch_results"),
        help="Directory for JSON results and CSV summaries",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="OpenRouter API key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on how many supported projects to scan.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    failed_rows = []
    scanned_supported = 0

    for project_dir in iter_scan_targets(dataset_dir):

        pragma_info = detect_project_pragma(project_dir)
        if pragma_info.supported:
            if args.limit and scanned_supported >= args.limit:
                break
            scanned_supported += 1

        output_json = output_dir / f"{output_name_for_target(project_dir)}.json"
        result = scan_project_to_file(project_dir, output_json, args.api_key)
        metadata = result["metadata"]
        project_name = output_name_for_target(project_dir)

        summary_rows.append(
            {
                "project_name": project_name,
                "detected_pragma": metadata.get("detected_pragma", pragma_info.detected_pragma),
                "status": metadata.get("status", result["status"]),
                "result_count": metadata.get("result_count", len(result["result"].get("results", []))),
                "token_sent": metadata.get("token_sent", 0),
                "token_received": metadata.get("token_received", 0),
                "used_time": metadata.get("used_time", 0),
            }
        )

        if result["status"] not in {"success", "skipped_unsupported_version"}:
            failed_rows.append(
                {
                    "project_name": project_name,
                    "detected_pragma": metadata.get("detected_pragma", pragma_info.detected_pragma),
                    "status": result["status"],
                    "error_message": metadata.get("error_message", ""),
                }
            )

    with open(output_dir / "summary.csv", "w", encoding="utf-8", newline="") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(summary_rows)

    with open(output_dir / "failed.csv", "w", encoding="utf-8", newline="") as failed_file:
        fieldnames = ["project_name", "detected_pragma", "status", "error_message"]
        writer = csv.DictWriter(failed_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(failed_rows)

    print(f"summary_csv={output_dir / 'summary.csv'}")
    print(f"failed_csv={output_dir / 'failed.csv'}")
    print(f"rows={len(summary_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
