import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import tasks


class TaskDependencyTests(unittest.TestCase):
    def test_build_solc_dependency_options_discovers_local_libs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "DeFiVulnLabs-main" / "samples" / "ApproveScam.sol"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('import "forge-std/Test.sol";', encoding="utf-8")

            (root / "DeFiVulnLabs-main" / "lib" / "forge-std" / "src").mkdir(parents=True, exist_ok=True)
            (root / "DeFiVulnLabs-main" / "lib" / "openzeppelin-contracts" / "contracts" / "access").mkdir(
                parents=True, exist_ok=True
            )
            (root / "DeFiVulnLabs-main" / "lib" / "forge-std" / "src" / "Test.sol").write_text(
                "contract Test {}",
                encoding="utf-8",
            )
            (root / "DeFiVulnLabs-main" / "lib" / "openzeppelin-contracts" / "contracts" / "access" / "Ownable.sol").write_text(
                "contract Ownable {}",
                encoding="utf-8",
            )

            remaps, solc_args = tasks._build_solc_dependency_options(target)

            self.assertGreaterEqual(len(remaps), 2)
            self.assertTrue(any(remap.startswith("forge-std/=") for remap in remaps))
            self.assertTrue(any(remap.startswith("@openzeppelin/=") for remap in remaps))
            self.assertIn("--allow-paths", solc_args)

    def test_build_solc_dependency_options_reads_project_remappings_and_local_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "src" / "core-contracts" / "interfaces").mkdir(parents=True, exist_ok=True)
            (project / "src" / "royalty-vault" / "interfaces").mkdir(parents=True, exist_ok=True)
            (project / "src" / "Example.sol").write_text(
                'pragma solidity 0.8.7;\n'
                'import "core-contracts/interfaces/ICoreCollection.sol";\n'
                'import "@chestrnft/royalty-vault/interfaces/IRoyaltyVault.sol";\n'
                'contract Example {}',
                encoding="utf-8",
            )
            (project / "src" / "core-contracts" / "interfaces" / "ICoreCollection.sol").write_text(
                "pragma solidity 0.8.7; interface ICoreCollection {}",
                encoding="utf-8",
            )
            (project / "src" / "royalty-vault" / "interfaces" / "IRoyaltyVault.sol").write_text(
                "pragma solidity 0.8.7; interface IRoyaltyVault {}",
                encoding="utf-8",
            )
            (project / "node_modules" / "@openzeppelin" / "contracts" / "token" / "ERC20").mkdir(parents=True, exist_ok=True)
            (project / "node_modules" / "@openzeppelin" / "contracts" / "token" / "ERC20" / "ERC20.sol").write_text(
                "pragma solidity 0.8.7; contract ERC20 {}",
                encoding="utf-8",
            )
            (project / "remappings.txt").write_text("@openzeppelin/=node_modules/@openzeppelin/\n", encoding="utf-8")

            remaps, solc_args = tasks._build_solc_dependency_options(project, project / "src" / "Example.sol")

            self.assertTrue(any(remap.startswith("@openzeppelin/=") for remap in remaps))
            self.assertTrue(any(remap.startswith("core-contracts/=") for remap in remaps))
            self.assertTrue(any(remap.startswith("@chestrnft/royalty-vault/=") for remap in remaps))
            self.assertIn("node_modules", solc_args)

    def test_build_solc_dependency_options_discovers_vendor_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "contracts").mkdir(parents=True, exist_ok=True)
            (project / "contracts" / "Main.sol").write_text(
                'pragma solidity 0.8.10;\nimport "@chainlink/contracts/Denominations.sol";\ncontract Main {}',
                encoding="utf-8",
            )
            (project / ".gptscan" / "npm_vendor" / "node_modules" / "@chainlink" / "contracts").mkdir(parents=True, exist_ok=True)
            (project / ".gptscan" / "npm_vendor" / "node_modules" / "@chainlink" / "contracts" / "Denominations.sol").write_text(
                "pragma solidity 0.8.10; library Denominations {}",
                encoding="utf-8",
            )

            remaps, solc_args = tasks._build_solc_dependency_options(project, project / "contracts" / "Main.sol")

            self.assertTrue(any(remap.startswith("@chainlink/contracts/=") for remap in remaps))
            self.assertIn(".gptscan/npm_vendor/node_modules", solc_args)


if __name__ == "__main__":
    unittest.main()
