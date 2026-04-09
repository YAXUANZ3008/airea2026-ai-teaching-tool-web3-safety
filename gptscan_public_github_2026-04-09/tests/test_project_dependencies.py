import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from project_dependencies import (
    BOOTSTRAP_STAMP,
    INFERRED_VENDOR_DIR,
    _detect_missing_known_packages,
    _resolve_package_manager_commands,
    detect_package_manager,
    ensure_project_dependencies,
    find_project_root,
)


class ProjectDependenciesTests(unittest.TestCase):
    def test_find_project_root_descends_to_nested_contract_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "dataset-project"
            workspace = project / "contracts"
            (workspace / "contracts").mkdir(parents=True, exist_ok=True)
            (workspace / "package.json").write_text("{}", encoding="utf-8")
            (workspace / "contracts" / "Main.sol").write_text("pragma solidity 0.7.6; contract Main {}", encoding="utf-8")

            self.assertEqual(workspace.resolve(), find_project_root(project))

    def test_detect_package_manager_prefers_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")

            self.assertEqual("yarn", detect_package_manager(root))

    @patch("project_dependencies.subprocess.run")
    def test_ensure_project_dependencies_installs_without_scripts_and_writes_stamp(self, mock_run) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "installed"
        mock_run.return_value.stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")

            result = ensure_project_dependencies(root)

            self.assertTrue(result.installed)
            self.assertFalse(result.skipped)
            command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
            self.assertIn("--ignore-scripts", command)
            self.assertTrue((root / BOOTSTRAP_STAMP).exists())

    @patch("project_dependencies.subprocess.run")
    def test_ensure_project_dependencies_retries_npm_with_legacy_peer_deps(self, mock_run) -> None:
        first = type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "ERESOLVE"})()
        second = type("Completed", (), {"returncode": 0, "stdout": "installed", "stderr": ""})()
        mock_run.side_effect = [first, second]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")

            result = ensure_project_dependencies(root)

            self.assertTrue(result.installed)
            self.assertEqual(2, mock_run.call_count)
            second_command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
            self.assertIn("--legacy-peer-deps", second_command)

    def test_yarn_commands_include_ignore_engines_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands = _resolve_package_manager_commands(root, "yarn")
            flattened = [" ".join(command) for command in commands]
            self.assertTrue(any("--ignore-engines" in command for command in flattened))

    @patch("project_dependencies.subprocess.run")
    def test_ensure_project_dependencies_installs_missing_known_packages_into_vendor_workspace(self, mock_run) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "installed"
        mock_run.return_value.stderr = ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "contracts").mkdir(parents=True, exist_ok=True)
            (root / "contracts" / "Main.sol").write_text(
                'pragma solidity 0.8.4;\nimport "@openzeppelin/contracts/token/ERC20/ERC20.sol";\ncontract Main {}',
                encoding="utf-8",
            )

            ensure_project_dependencies(root, "0.8.4")

            self.assertEqual(2, mock_run.call_count)
            vendor_package_json = root / INFERRED_VENDOR_DIR / "package.json"
            self.assertTrue(vendor_package_json.exists())
            second_cwd = Path(mock_run.call_args_list[1].kwargs["cwd"])
            self.assertEqual((root / INFERRED_VENDOR_DIR).resolve(), second_cwd.resolve())

    @patch("project_dependencies.subprocess.run")
    def test_ensure_project_dependencies_skips_when_stamp_exists(self, mock_run) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "node_modules").mkdir(parents=True, exist_ok=True)
            stamp = root / BOOTSTRAP_STAMP
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text("ready\n", encoding="utf-8")

            result = ensure_project_dependencies(root)

            self.assertTrue(result.skipped)
            self.assertFalse(result.installed)
            mock_run.assert_not_called()

    def test_detect_missing_known_packages_skips_foundry_libs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "foundry.toml").write_text("[default]\nlibs=['lib']\n", encoding="utf-8")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "lib" / "ds-test" / "src").mkdir(parents=True, exist_ok=True)
            (root / "lib" / "forge-std" / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "Main.sol").write_text(
                'pragma solidity 0.8.10;\nimport "ds-test/test.sol";\nimport "forge-std/Test.sol";\ncontract Main {}',
                encoding="utf-8",
            )

            packages = _detect_missing_known_packages(root, "0.8.10")

            self.assertEqual([], packages)

    @patch("project_dependencies.subprocess.run")
    def test_ensure_project_dependencies_skips_when_node_modules_already_exists(self, mock_run) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "node_modules").mkdir(parents=True, exist_ok=True)

            result = ensure_project_dependencies(root)

            self.assertTrue(result.skipped)
            self.assertFalse(result.installed)
            mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
