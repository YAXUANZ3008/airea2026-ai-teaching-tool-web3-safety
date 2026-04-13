import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatgpt_api import LLMAPIError
from scan_runner import scan_project_to_file


class ScanRunnerTests(unittest.TestCase):
    def write_sol(self, directory: Path, relative_path: str, content: str) -> None:
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_unsupported_version_short_circuits_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "Legacy.sol", "pragma solidity ^0.6.12; contract Legacy {}")
            output_path = root / "result.json"

            result = scan_project_to_file(root, output_path, api_key="sk-demo")

            self.assertEqual("skipped_unsupported_version", result["status"])
            self.assertTrue(output_path.exists())
            metadata_path = Path(str(output_path) + ".metadata.json")
            self.assertTrue(metadata_path.exists())

            output = json.loads(output_path.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual("skipped_unsupported_version", metadata["status"])
            self.assertEqual("Skipped: Unsupported Solidity Version", output["summary"]["statusLabel"])
            self.assertEqual("Project skipped", output["ui"]["headline"])
            self.assertEqual([], output["findings"])

    @patch("scan_runner.tasks.run_scan")
    @patch("scan_runner.prepare_solc_for_project")
    def test_supported_project_switches_solc_before_scan(self, mock_prepare_solc, mock_run_scan) -> None:
        mock_prepare_solc.return_value = "0.8.17"
        mock_run_scan.return_value = (
            {
                "success": True,
                "results": [
                    {
                        "code": "demo",
                        "severity": "HIGH",
                        "title": "Demo: Example issue",
                        "description": "Example description",
                        "recommendation": "Example recommendation",
                        "affectedFiles": [
                            {
                                "filePath": "/tmp/project/Demo.sol",
                                "range": {"start": {"line": 5}, "end": {"line": 8}},
                                "highlights": [],
                            }
                        ],
                    }
                ],
            },
            {"status": "success", "token_sent": 10, "token_received": 20},
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "Demo.sol", "pragma solidity ^0.8.17; contract Demo {}")
            output_path = root / "result.json"

            result = scan_project_to_file(root, output_path, api_key="sk-demo")

            self.assertEqual("success", result["status"])
            self.assertEqual(1, len(result["result"]["results"]))
            self.assertEqual("0.8.17", result["metadata"]["solc_version"])
            self.assertEqual("Scan Completed", result["result"]["summary"]["statusLabel"])
            self.assertEqual(1, len(result["result"]["findings"]))
            self.assertTrue(result["result"]["findings"][0]["primaryLocation"]["label"].endswith("/Demo.sol:5-8"))
            self.assertEqual(1, mock_prepare_solc.call_count)
            self.assertEqual(1, mock_run_scan.call_count)

    @patch("scan_runner.tasks.run_scan")
    @patch("scan_runner.prepare_solc_for_project")
    def test_failure_metadata_keeps_selected_solc_version(self, mock_prepare_solc, mock_run_scan) -> None:
        mock_prepare_solc.return_value = "0.8.9"
        mock_run_scan.side_effect = LLMAPIError("request failed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "Demo.sol", "pragma solidity ^0.8.0; contract Demo {}")
            output_path = root / "result.json"

            result = scan_project_to_file(root, output_path, api_key="sk-demo")

            self.assertEqual("llm_api_failed", result["status"])
            self.assertEqual("0.8.9", result["metadata"]["solc_version"])
            self.assertEqual("Scan failed", result["result"]["ui"]["headline"])
            self.assertEqual("LLM Request Failed", result["result"]["summary"]["statusLabel"])


if __name__ == "__main__":
    unittest.main()
