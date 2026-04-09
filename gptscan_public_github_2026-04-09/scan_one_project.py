#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from scan_runner import scan_project_to_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a single Solidity project with the GPTScan demo flow.")
    parser.add_argument("project_dir", help="Path to the Solidity project directory")
    parser.add_argument("output_json", help="Path to write the result JSON")
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="OpenRouter API key. Defaults to OPENAI_API_KEY.",
    )
    args = parser.parse_args()

    result = scan_project_to_file(args.project_dir, args.output_json, args.api_key)
    print(f"status={result['status']}")
    print(f"output_json={Path(args.output_json).expanduser().resolve()}")
    print(f"metadata_json={Path(str(Path(args.output_json).expanduser().resolve()) + '.metadata.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
