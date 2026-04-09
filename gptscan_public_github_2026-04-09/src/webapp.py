from __future__ import annotations

import argparse
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

from aiohttp import web

from scan_runner import scan_project_to_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC_DIR = REPO_ROOT / "code_sandbox_light_f9139025_1775118386"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 1024 * 1024**2
PACKAGE_MANAGER_MARKERS = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-OpenAI-Api-Key",
    }


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=_cors_headers())

    response = await handler(request)
    response.headers.update(_cors_headers())
    return response


def _json_error(message: str, *, error: str, status: int) -> web.Response:
    return web.json_response({"error": error, "message": message}, status=status, headers=_cors_headers())


def _is_solidity_upload(filename: str) -> bool:
    return filename.lower().endswith(".sol")


def _is_zip_upload(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def _is_tar_upload(filename: str) -> bool:
    lower_name = filename.lower()
    return lower_name.endswith(".tar") or lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz")


def _ensure_within_directory(path: Path, directory: Path) -> None:
    resolved_path = path.resolve()
    resolved_directory = directory.resolve()
    if resolved_directory not in (resolved_path, *resolved_path.parents):
        raise ValueError("Archive contains files outside the destination directory.")


def _should_skip_archive_member(member_name: str) -> bool:
    parts = [part for part in Path(member_name).parts if part not in ("", ".")]
    return any(part == "__MACOSX" or part.startswith("._") or part == ".DS_Store" for part in parts)


def _archive_looks_package_managed(member_names: list[str]) -> bool:
    return any(Path(member_name).name in PACKAGE_MANAGER_MARKERS for member_name in member_names)


def _should_skip_dependency_member(member_name: str, *, skip_node_modules: bool) -> bool:
    if not skip_node_modules:
        return False
    return "node_modules" in {part.lower() for part in Path(member_name).parts}


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        skip_node_modules = _archive_looks_package_managed([member.filename for member in archive.infolist()])
        for member in archive.infolist():
            if _should_skip_archive_member(member.filename) or _should_skip_dependency_member(
                member.filename,
                skip_node_modules=skip_node_modules,
            ):
                continue
            target = destination / member.filename
            _ensure_within_directory(target, destination)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path) as archive:
        skip_node_modules = _archive_looks_package_managed([member.name for member in archive.getmembers()])
        for member in archive.getmembers():
            if _should_skip_archive_member(member.name) or _should_skip_dependency_member(
                member.name,
                skip_node_modules=skip_node_modules,
            ):
                continue
            target = destination / member.name
            _ensure_within_directory(target, destination)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with extracted as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _prepare_project_directory(upload_path: Path, filename: str, workspace_dir: Path) -> tuple[Path, str]:
    project_dir = workspace_dir / "project"
    project_dir.mkdir(parents=True, exist_ok=True)

    if _is_solidity_upload(filename):
        shutil.copy2(upload_path, project_dir / filename)
        return project_dir, "single_solidity_file"

    if _is_zip_upload(filename):
        _safe_extract_zip(upload_path, project_dir)
        return project_dir, "zip_archive"

    if _is_tar_upload(filename):
        _safe_extract_tar(upload_path, project_dir)
        return project_dir, "tar_archive"

    raise ValueError("Only .sol, .zip, .tar, .tar.gz, and .tgz uploads are supported.")


async def _write_uploaded_file(file_field, target_path: Path) -> int:
    size = 0
    with target_path.open("wb") as handle:
        while True:
            chunk = await file_field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            handle.write(chunk)
    return size


async def analyze_contract_upload(request: web.Request) -> web.Response:
    if not request.content_type.startswith("multipart/"):
        return _json_error(
            "Upload requests must use multipart/form-data.",
            error="invalid_content_type",
            status=400,
        )

    reader = await request.multipart()
    file_name = None
    api_key = request.headers.get("X-OpenAI-Api-Key") or os.environ.get("OPENAI_API_KEY")

    try:
        with tempfile.TemporaryDirectory(prefix="gptscan-web-") as temp_dir:
            workspace_dir = Path(temp_dir)
            upload_path = None
            upload_size = 0

            async for field in reader:
                if field.name == "apiKey" and not api_key:
                    api_key = (await field.text()).strip() or api_key
                    continue
                if field.name == "file" and upload_path is None and field.filename:
                    file_name = Path(field.filename).name
                    upload_path = workspace_dir / file_name
                    upload_size = await _write_uploaded_file(field, upload_path)

            if upload_path is None or file_name is None:
                return _json_error(
                    "Please upload a Solidity file or supported archive.",
                    error="missing_file",
                    status=400,
                )

            project_dir, upload_mode = _prepare_project_directory(upload_path, file_name, workspace_dir)
            output_path = workspace_dir / "result.json"
            scan_result = scan_project_to_file(project_dir, output_path, api_key=api_key)
    except ValueError as exc:
        return _json_error(str(exc), error="unsupported_upload", status=400)
    except zipfile.BadZipFile as exc:
        return _json_error(
            f"The uploaded zip archive could not be extracted: {exc}",
            error="invalid_archive",
            status=400,
        )
    except tarfile.TarError as exc:
        return _json_error(
            f"The uploaded tar archive could not be extracted: {exc}",
            error="invalid_archive",
            status=400,
        )

    response_payload = {
        **scan_result,
        "uploadedFile": {
            "name": file_name,
            "sizeBytes": upload_size,
            "mode": upload_mode,
        },
    }
    return web.json_response(response_payload, headers=_cors_headers())


async def healthcheck(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"}, headers=_cors_headers())


def _serve_html(static_dir: Path, filename: str):
    async def _handler(_request: web.Request) -> web.Response:
        return web.FileResponse(static_dir / filename)

    return _handler


def create_app(*, static_dir: str | Path | None = None) -> web.Application:
    static_path = Path(static_dir or DEFAULT_STATIC_DIR).expanduser().resolve()

    app = web.Application(middlewares=[cors_middleware], client_max_size=DEFAULT_MAX_UPLOAD_SIZE_BYTES)
    app.router.add_get("/api/health", healthcheck)
    app.router.add_post("/api/contracts/analyze", analyze_contract_upload)
    app.router.add_post("/api/contracts/parse-file", analyze_contract_upload)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", healthcheck)

    app.router.add_get("/", _serve_html(static_path, "index.html"))
    app.router.add_get("/index.html", _serve_html(static_path, "index.html"))
    app.router.add_get("/about.html", _serve_html(static_path, "about.html"))
    app.router.add_get("/education-hub.html", _serve_html(static_path, "education-hub.html"))
    app.router.add_get("/quick-start.html", _serve_html(static_path, "quick-start.html"))
    app.router.add_static("/css/", static_path / "css")
    app.router.add_static("/js/", static_path / "js")
    app.router.add_static("/images/", static_path / "images")
    app.router.add_static("/downloads/", static_path / "downloads")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the GPTScan demo web UI and upload API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR))
    args = parser.parse_args()

    web.run_app(create_app(static_dir=args.static_dir), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
