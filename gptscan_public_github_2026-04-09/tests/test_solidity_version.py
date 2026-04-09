import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from solidity_version import (
    detect_project_pragma,
    is_supported_solidity_demo,
    resolve_solc_version,
)


class SolidityVersionTests(unittest.TestCase):
    def write_sol(self, directory: Path, relative_path: str, content: str) -> None:
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_detects_supported_pragma_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "A.sol", "pragma solidity ^0.8.17; contract A {}")
            self.write_sol(root, "B.sol", "pragma solidity >=0.8.0 <0.9.0; contract B {}")

            info = detect_project_pragma(root)

            self.assertTrue(info.found)
            self.assertTrue(info.supported)
            self.assertIn("^0.8.17", info.detected_pragma)
            self.assertIn(">=0.8.0 <0.9.0", info.detected_pragma)

    def test_accepts_supported_07_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "Legacy.sol", "pragma solidity ^0.7.6; contract Legacy {}")

            info = detect_project_pragma(root)

            self.assertTrue(info.found)
            self.assertTrue(info.supported)
            self.assertEqual("^0.7.6", info.detected_pragma)

    def test_support_heuristics_cover_demo_patterns(self) -> None:
        self.assertTrue(is_supported_solidity_demo("^0.7.6"))
        self.assertTrue(is_supported_solidity_demo("0.7.0"))
        self.assertTrue(is_supported_solidity_demo(">=0.7.0 <0.8.0"))
        self.assertTrue(is_supported_solidity_demo("^0.8.0"))
        self.assertTrue(is_supported_solidity_demo("0.8.2"))
        self.assertTrue(is_supported_solidity_demo(">=0.8.0 <0.9.0"))
        self.assertTrue(is_supported_solidity_demo("=0.8.7"))
        self.assertTrue(is_supported_solidity_demo("^0.8"))
        self.assertTrue(is_supported_solidity_demo(">=0.4.23"))
        self.assertFalse(is_supported_solidity_demo("^0.6.12"))

    def test_resolve_solc_version_prefers_exact_match(self) -> None:
        version = resolve_solc_version(["0.8.2"], ["0.8.0", "0.8.2", "0.8.34"])
        self.assertEqual("0.8.2", version)

    def test_resolve_solc_version_picks_highest_matching_range(self) -> None:
        version = resolve_solc_version(["^0.8.0", ">=0.8.0 <0.9.0"], ["0.8.0", "0.8.24", "0.8.34"])
        self.assertEqual("0.8.34", version)

    def test_resolve_solc_version_picks_matching_07x_version(self) -> None:
        version = resolve_solc_version(["^0.7.0", ">=0.7.0 <0.8.0"], ["0.7.0", "0.7.4", "0.7.6", "0.8.34"])
        self.assertEqual("0.7.6", version)

    def test_resolve_solc_version_returns_none_for_conflicting_pragmas(self) -> None:
        version = resolve_solc_version(["0.8.0", "0.8.2"], ["0.8.0", "0.8.2", "0.8.34"])
        self.assertIsNone(version)

    def test_detects_all_pragma_expressions_in_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(
                root,
                "Multi.sol",
                "pragma solidity ^0.8.0;\ncontract A {}\npragma solidity 0.8.9;\ncontract B {}",
            )

            info = detect_project_pragma(root)

            self.assertEqual(("0.8.9", "^0.8.0"), tuple(sorted(info.expressions)))
            self.assertIn("0.8.9", info.detected_pragma)

    def test_detect_project_pragma_supports_single_file_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "Single.sol", "pragma solidity 0.8.11; contract Single {}")

            info = detect_project_pragma(root / "Single.sol")

            self.assertTrue(info.found)
            self.assertTrue(info.supported)
            self.assertEqual(1, info.files_scanned)
            self.assertEqual("0.8.11", info.detected_pragma)

    def test_detect_project_pragma_ignores_node_modules_and_test_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "src/Main.sol", "pragma solidity 0.8.7; contract Main {}")
            self.write_sol(root, "node_modules/@openzeppelin/contracts/Bad.sol", "pragma solidity ^0.8.20; contract Bad {}")
            self.write_sol(root, "test/Main.t.sol", "pragma solidity ^0.8.20; contract MainTest {}")

            info = detect_project_pragma(root)

            self.assertTrue(info.supported)
            self.assertEqual("0.8.7", info.detected_pragma)

    def test_detect_project_pragma_accepts_wide_lower_bounds_if_installed_version_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_sol(root, "A.sol", "pragma solidity >=0.4.23; contract A {}")
            self.write_sol(root, "B.sol", "pragma solidity 0.8.10; contract B {}")

            info = detect_project_pragma(root)

            self.assertTrue(info.found)
            self.assertTrue(info.supported)
            self.assertIn(">=0.4.23", info.detected_pragma)

    def test_resolve_solc_version_handles_equal_and_short_caret_forms(self) -> None:
        version = resolve_solc_version(["=0.8.7", "^0.8"], ["0.8.6", "0.8.7", "0.8.34"])
        self.assertEqual("0.8.7", version)


if __name__ == "__main__":
    unittest.main()
