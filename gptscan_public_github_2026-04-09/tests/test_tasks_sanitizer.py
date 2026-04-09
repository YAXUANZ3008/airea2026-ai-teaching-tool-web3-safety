import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tasks import _prepare_compile_target, _sanitize_foundry_test_source


class TaskSanitizerTests(unittest.TestCase):
    def test_sanitize_foundry_source_removes_test_import_and_contracts(self) -> None:
        source = """pragma solidity ^0.8.18;
import "forge-std/Test.sol";
contract ContractTest is Test {
    function testSomething() public {}
}
contract Vulnerable {
    function run() public {}
}
"""
        sanitized = _sanitize_foundry_test_source(source)
        self.assertNotIn('import "forge-std/Test.sol";', sanitized)
        self.assertNotIn("contract ContractTest is Test", sanitized)
        self.assertIn("contract Vulnerable", sanitized)

    def test_prepare_compile_target_writes_sanitized_workspace_for_foundry_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "Sample.sol"
            file_path.write_text(
                'pragma solidity ^0.8.18;\nimport "forge-std/Test.sol";\ncontract ContractTest is Test { function t() public {} }\ncontract Core {}',
                encoding="utf-8",
            )

            sanitized_target = _prepare_compile_target(file_path)
            sanitized_text = sanitized_target.read_text(encoding="utf-8")

            self.assertNotEqual(file_path, sanitized_target)
            self.assertIn("compile_sources", sanitized_target.as_posix())
            self.assertNotIn("ContractTest is Test", sanitized_text)
            self.assertIn("contract Core", sanitized_text)

    def test_prepare_compile_target_clears_stale_compile_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "Sample.sol"
            file_path.write_text(
                'pragma solidity ^0.8.18;\nimport "forge-std/Test.sol";\ncontract ContractTest is Test { function t() public {} }\ncontract Core {}',
                encoding="utf-8",
            )

            stale_dir = root / ".gptscan" / "compile_sources"
            stale_dir.mkdir(parents=True, exist_ok=True)
            (stale_dir / "stale.sol").write_text("pragma solidity ^0.8.18; contract Stale {}", encoding="utf-8")

            sanitized_target = _prepare_compile_target(file_path)

            self.assertTrue(sanitized_target.exists())
            self.assertFalse((stale_dir / "stale.sol").exists())

    def test_prepare_compile_target_builds_wrapper_for_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "contracts" / "interfaces").mkdir(parents=True, exist_ok=True)
            (project / "contracts" / "Pool.sol").write_text(
                'pragma solidity 0.8.3;\nimport "./interfaces/IPool.sol";\ncontract Pool {}',
                encoding="utf-8",
            )
            (project / "contracts" / "interfaces" / "IPool.sol").write_text(
                "pragma solidity 0.8.3; interface IPool {}",
                encoding="utf-8",
            )
            (project / "test").mkdir(parents=True, exist_ok=True)
            (project / "test" / "Pool.t.sol").write_text(
                "pragma solidity 0.8.3; contract PoolTest {}",
                encoding="utf-8",
            )

            compile_target = _prepare_compile_target(project)
            wrapper_text = compile_target.read_text(encoding="utf-8")

            self.assertTrue(compile_target.name.endswith(".sol"))
            self.assertIn('__gptscan_entry__', compile_target.name)
            self.assertIn('import "./contracts/Pool.sol";', wrapper_text)
            self.assertNotIn("Pool.t.sol", wrapper_text)

    def test_prepare_compile_target_excludes_direct_interface_imports_when_main_file_imports_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "contracts" / "interfaces").mkdir(parents=True, exist_ok=True)
            (project / "contracts" / "Main.sol").write_text(
                'pragma solidity 0.7.6;\nimport "./interfaces/IThing.sol";\ncontract Main is IThing {}',
                encoding="utf-8",
            )
            (project / "contracts" / "interfaces" / "IThing.sol").write_text(
                "pragma solidity 0.7.6; interface IThing {}",
                encoding="utf-8",
            )

            compile_target = _prepare_compile_target(project)
            wrapper_text = compile_target.read_text(encoding="utf-8")

            self.assertIn('import "./contracts/Main.sol";', wrapper_text)
            self.assertNotIn('import "./contracts/interfaces/IThing.sol";', wrapper_text)

    def test_prepare_compile_target_prefers_single_entry_group_when_modules_collide_on_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "build" / "marketplace").mkdir(parents=True, exist_ok=True)
            (project / "build" / "swivel").mkdir(parents=True, exist_ok=True)

            (project / "build" / "marketplace" / "Abstracts.sol").write_text(
                "pragma solidity 0.8.4; abstract contract SharedA {}",
                encoding="utf-8",
            )
            (project / "build" / "marketplace" / "MarketPlace.sol").write_text(
                'pragma solidity 0.8.4;\nimport "./Abstracts.sol";\ncontract MarketPlace is SharedA {}',
                encoding="utf-8",
            )
            (project / "build" / "marketplace" / "Helper.sol").write_text(
                "pragma solidity 0.8.4; contract Helper {}",
                encoding="utf-8",
            )

            (project / "build" / "swivel" / "Abstracts.sol").write_text(
                "pragma solidity 0.8.4; abstract contract SharedB {}",
                encoding="utf-8",
            )
            (project / "build" / "swivel" / "Swivel.sol").write_text(
                'pragma solidity 0.8.4;\nimport "./Abstracts.sol";\ncontract Swivel is SharedB {}',
                encoding="utf-8",
            )

            compile_target = _prepare_compile_target(project)
            wrapper_text = compile_target.read_text(encoding="utf-8")

            self.assertIn('import "./build/marketplace/MarketPlace.sol";', wrapper_text)
            self.assertNotIn('import "./build/swivel/Swivel.sol";', wrapper_text)

    def test_prepare_compile_target_copies_local_imports_outside_contracts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "contracts").mkdir(parents=True, exist_ok=True)
            (project / "interfaces").mkdir(parents=True, exist_ok=True)

            (project / "contracts" / "AddressProvider.sol").write_text(
                'pragma solidity 0.8.10;\nimport "../interfaces/IGasBank.sol";\ncontract AddressProvider is IGasBank {}',
                encoding="utf-8",
            )
            (project / "interfaces" / "IGasBank.sol").write_text(
                "pragma solidity 0.8.10; interface IGasBank {}",
                encoding="utf-8",
            )

            compile_target = _prepare_compile_target(project)

            self.assertTrue((compile_target.parent / "interfaces" / "IGasBank.sol").exists())


if __name__ == "__main__":
    unittest.main()
