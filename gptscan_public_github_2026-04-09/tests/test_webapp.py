import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from webapp import _prepare_project_directory, _write_uploaded_file, analyze_contract_upload, create_app


class FakeField:
    def __init__(self, *, name: str, filename: str | None = None, chunks=None, text_value: str = "") -> None:
        self.name = name
        self.filename = filename
        self._chunks = list(chunks or [])
        self._text_value = text_value

    async def read_chunk(self) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    async def text(self) -> str:
        return self._text_value


class FakeMultipartReader:
    def __init__(self, fields) -> None:
        self._fields = iter(fields)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._fields)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeRequest:
    def __init__(self, fields, *, content_type: str = "multipart/form-data", headers=None) -> None:
        self.content_type = content_type
        self.headers = headers or {}
        self._reader = FakeMultipartReader(fields)

    async def multipart(self):
        return self._reader


class WebAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_uploaded_file_persists_all_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_path = Path(tmp) / "archive.zip"
            field = FakeField(
                name="file",
                filename="archive.zip",
                chunks=[b"PK\x03\x04", b"zip-bytes"],
            )

            written_size = await _write_uploaded_file(field, target_path)

            self.assertEqual(13, written_size)
            self.assertEqual(b"PK\x03\x04zip-bytes", target_path.read_bytes())

    def test_prepare_project_directory_ignores_macos_zip_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            upload_path = workspace_dir / "contracts.zip"

            with zipfile.ZipFile(upload_path, "w") as archive:
                archive.writestr("6/Beebots.sol", "pragma solidity ^0.8.17; contract Beebots {}")
                archive.writestr("__MACOSX/6/._Beebots.sol", "Mac OS X metadata")
                archive.writestr("__MACOSX/.DS_Store", "metadata")

            project_dir, upload_mode = _prepare_project_directory(upload_path, "contracts.zip", workspace_dir)

            self.assertEqual("zip_archive", upload_mode)
            self.assertTrue((project_dir / "6" / "Beebots.sol").exists())
            self.assertFalse((project_dir / "__MACOSX").exists())

    def test_prepare_project_directory_skips_node_modules_for_package_managed_zip_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            upload_path = workspace_dir / "contracts.zip"

            with zipfile.ZipFile(upload_path, "w") as archive:
                archive.writestr("demo/package.json", '{"name":"demo"}')
                archive.writestr("demo/contracts/Main.sol", "pragma solidity ^0.8.17; contract Main {}")
                archive.writestr(
                    "demo/node_modules/@openzeppelin/contracts/token/ERC20/ERC20.sol",
                    "pragma solidity ^0.8.17; contract ERC20 {}",
                )

            project_dir, upload_mode = _prepare_project_directory(upload_path, "contracts.zip", workspace_dir)

            self.assertEqual("zip_archive", upload_mode)
            self.assertTrue((project_dir / "demo" / "package.json").exists())
            self.assertTrue((project_dir / "demo" / "contracts" / "Main.sol").exists())
            self.assertFalse((project_dir / "demo" / "node_modules").exists())

    def test_create_app_accepts_large_local_demo_archives(self) -> None:
        app = create_app()

        self.assertGreaterEqual(app._client_max_size, 512 * 1024**2)

    async def test_analyze_endpoint_scans_uploaded_solidity_file(self) -> None:
        fake_result = {
            "status": "success",
            "result": {
                "success": True,
                "summary": {"status": "success", "resultCount": 1},
                "findings": [
                    {
                        "severity": "high",
                        "displayTitle": "Unsafe owner withdrawal",
                        "description": "Owner can drain user funds",
                        "recommendation": "Gate privileged withdrawals",
                        "locations": [{"path": "Demo.sol", "startLine": 7, "endLine": 11}],
                    }
                ],
            },
            "metadata": {"status": "success"},
        }

        request = FakeRequest(
            [
                FakeField(
                    name="file",
                    filename="Demo.sol",
                    chunks=[b"pragma solidity ^0.8.17;", b" contract Demo {}"],
                )
            ]
        )

        observed = {}

        def fake_scan(project_dir, output_path, api_key):
            project_dir = Path(project_dir)
            output_path = Path(output_path)
            observed["project_dir_exists"] = project_dir.is_dir()
            observed["uploaded_contract_exists"] = (project_dir / "Demo.sol").exists()
            observed["output_name"] = output_path.name
            observed["api_key"] = api_key
            return fake_result

        with patch("webapp.scan_project_to_file", side_effect=fake_scan) as mock_scan:
            response = await analyze_contract_upload(request)

        self.assertEqual(200, response.status)
        payload = json.loads(response.text)
        self.assertEqual("success", payload["status"])
        self.assertEqual("Demo.sol", payload["uploadedFile"]["name"])
        self.assertEqual("single_solidity_file", payload["uploadedFile"]["mode"])
        self.assertEqual(1, payload["result"]["summary"]["resultCount"])
        self.assertTrue(observed["project_dir_exists"])
        self.assertTrue(observed["uploaded_contract_exists"])
        self.assertEqual("result.json", observed["output_name"])
        self.assertIsNone(observed["api_key"])
        self.assertEqual(1, mock_scan.call_count)

    async def test_analyze_endpoint_rejects_missing_upload(self) -> None:
        response = await analyze_contract_upload(FakeRequest([]))

        self.assertEqual(400, response.status)
        payload = json.loads(response.text)
        self.assertEqual("missing_file", payload["error"])

    async def test_analyze_endpoint_uses_form_api_key_when_provided(self) -> None:
        request = FakeRequest(
            [
                FakeField(name="apiKey", text_value="sk-test-123"),
                FakeField(
                    name="file",
                    filename="Demo.sol",
                    chunks=[b"pragma solidity ^0.8.17; contract Demo {}"],
                ),
            ]
        )
        observed = {}

        def fake_scan(project_dir, output_path, api_key):
            observed["api_key"] = api_key
            return {
                "status": "success",
                "result": {"success": True, "summary": {"status": "success", "resultCount": 0}, "findings": []},
                "metadata": {"status": "success"},
            }

        with patch("webapp.scan_project_to_file", side_effect=fake_scan):
            response = await analyze_contract_upload(request)

        self.assertEqual(200, response.status)
        self.assertEqual("sk-test-123", observed["api_key"])

    async def test_analyze_endpoint_reads_api_key_even_when_file_field_comes_first(self) -> None:
        request = FakeRequest(
            [
                FakeField(
                    name="file",
                    filename="Demo.sol",
                    chunks=[b"pragma solidity ^0.8.17; contract Demo {}"],
                ),
                FakeField(name="apiKey", text_value="sk-test-after-file"),
            ]
        )
        observed = {}

        def fake_scan(project_dir, output_path, api_key):
            observed["api_key"] = api_key
            return {
                "status": "success",
                "result": {"success": True, "summary": {"status": "success", "resultCount": 0}, "findings": []},
                "metadata": {"status": "success"},
            }

        with patch("webapp.scan_project_to_file", side_effect=fake_scan):
            response = await analyze_contract_upload(request)

        self.assertEqual(200, response.status)
        self.assertEqual("sk-test-after-file", observed["api_key"])

    async def test_analyze_endpoint_returns_zip_error_details(self) -> None:
        request = FakeRequest(
            [
                FakeField(
                    name="file",
                    filename="broken.zip",
                    chunks=[b"this is not a real zip archive"],
                )
            ]
        )

        response = await analyze_contract_upload(request)

        self.assertEqual(400, response.status)
        payload = json.loads(response.text)
        self.assertEqual("invalid_archive", payload["error"])
        self.assertIn("File is not a zip file", payload["message"])


if __name__ == "__main__":
    unittest.main()
