import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from batch_scan_demo import iter_scan_targets, output_name_for_target


class BatchScanDemoTests(unittest.TestCase):
    def test_iter_scan_targets_includes_flat_sol_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Flat.sol").write_text("pragma solidity 0.8.0; contract Flat {}", encoding="utf-8")
            (root / "Nested").mkdir()
            (root / "README.md").write_text("ignore", encoding="utf-8")

            targets = list(iter_scan_targets(root))

            self.assertEqual([root / "Flat.sol", root / "Nested"], targets)

    def test_iter_scan_targets_skips_hidden_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gptscan").mkdir()
            (root / ".hidden.sol").write_text("pragma solidity 0.8.0; contract Hidden {}", encoding="utf-8")
            (root / "Visible.sol").write_text("pragma solidity 0.8.0; contract Visible {}", encoding="utf-8")

            targets = list(iter_scan_targets(root))

            self.assertEqual([root / "Visible.sol"], targets)

    def test_output_name_uses_stem_for_flat_file(self) -> None:
        file_target = Path("/tmp/Flat.sol")
        dir_target = Path("/tmp/Nested")

        self.assertEqual("Flat", output_name_for_target(file_target))
        self.assertEqual("Nested", output_name_for_target(dir_target))


if __name__ == "__main__":
    unittest.main()
