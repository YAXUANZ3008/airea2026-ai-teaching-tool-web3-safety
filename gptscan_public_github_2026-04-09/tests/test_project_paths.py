import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from project_paths import ensure_project_work_dir


class ProjectPathsTests(unittest.TestCase):
    def test_ensure_project_work_dir_uses_parent_for_file_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "Sample.sol"
            file_path.write_text("pragma solidity 0.8.0;", encoding="utf-8")

            work_dir = ensure_project_work_dir(file_path)

            self.assertEqual((file_path.parent / ".gptscan").resolve(), work_dir)
            self.assertTrue(work_dir.exists())


if __name__ == "__main__":
    unittest.main()
