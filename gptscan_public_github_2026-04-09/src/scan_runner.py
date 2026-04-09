from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from chatgpt_api import LLMAPIError
from project_dependencies import ensure_project_dependencies
from scan_exceptions import CompileFailure, ParseFailure
from solidity_version import detect_project_pragma, prepare_solc_for_project


class _TasksProxy:
    def run_scan(self, *args: Any, **kwargs: Any):
        import tasks as tasks_module

        return tasks_module.run_scan(*args, **kwargs)


tasks = _TasksProxy()

STATUS_LABELS = {
    "success": "Scan Completed",
    "llm_api_failed": "LLM Request Failed",
    "compile_failed": "Compilation Failed",
    "parse_failed": "Parse Failed",
    "skipped_unsupported_version": "Skipped: Unsupported Solidity Version",
}

STATUS_TONES = {
    "success": "success",
    "llm_api_failed": "error",
    "compile_failed": "error",
    "parse_failed": "warning",
    "skipped_unsupported_version": "muted",
}


def _metadata_path(output_path: Path) -> Path:
    return Path(str(output_path) + ".metadata.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")


def _display_path(file_path: str, project_dir: Path) -> str:
    path = Path(file_path).expanduser().resolve()
    base_dir = project_dir.parent if project_dir.is_file() else project_dir
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _build_findings(result_payload: dict, project_dir: Path) -> list[dict]:
    findings = []
    for index, result in enumerate(result_payload.get("results", []), start=1):
        locations = []
        for affected in result.get("affectedFiles", []):
            start_line = affected.get("range", {}).get("start", {}).get("line")
            end_line = affected.get("range", {}).get("end", {}).get("line")
            file_path = affected.get("filePath", "")
            display_path = _display_path(file_path, project_dir) if file_path else ""
            locations.append(
                {
                    "path": display_path,
                    "absolutePath": file_path,
                    "startLine": start_line,
                    "endLine": end_line,
                    "label": f"{display_path}:{start_line}-{end_line}" if display_path and start_line else display_path,
                }
            )

        severity = str(result.get("severity", "info")).lower()
        findings.append(
            {
                "id": f"finding-{index}",
                "code": result.get("code"),
                "severity": severity,
                "severityLabel": severity.upper(),
                "title": result.get("title"),
                "displayTitle": result.get("title"),
                "description": result.get("description"),
                "recommendation": result.get("recommendation"),
                "fileCount": len(locations),
                "primaryLocation": locations[0] if locations else None,
                "locations": locations,
                "badges": [severity.upper(), str(result.get("code", "")).replace("-", " ").title()],
            }
        )
    return findings


def _build_ui_payload(
    *,
    status: str,
    result_count: int,
    project_name: str,
    detected_pragma: str,
    solc_version: str | None,
) -> dict:
    if status == "success":
        headline = f"{result_count} finding{'s' if result_count != 1 else ''} detected" if result_count else "No findings detected"
    elif status == "skipped_unsupported_version":
        headline = "Project skipped"
    else:
        headline = "Scan failed"

    subheadline_parts = [project_name]
    if detected_pragma:
        subheadline_parts.append(f"pragma {detected_pragma}")
    if solc_version:
        subheadline_parts.append(f"solc {solc_version}")

    empty_state = None
    if status == "success" and result_count == 0:
        empty_state = {
            "title": "No confirmed findings",
            "description": "The scan finished successfully, but no findings passed the final filtering and static checks.",
        }

    return {
        "headline": headline,
        "subheadline": " | ".join(subheadline_parts),
        "statusLabel": STATUS_LABELS.get(status, status.replace("_", " ").title()),
        "statusTone": STATUS_TONES.get(status, "info"),
        "emptyState": empty_state,
    }


def _decorate_output_payload(result_payload: dict, metadata: dict, project_dir: Path) -> dict:
    status = metadata.get("status", "success")
    result_count = int(metadata.get("result_count", len(result_payload.get("results", []))) or 0)
    findings = _build_findings(result_payload, project_dir)
    project_name = project_dir.stem if project_dir.is_file() else project_dir.name
    detected_pragma = metadata.get("detected_pragma", "")
    solc_version = metadata.get("solc_version")

    result_payload["project"] = {
        "name": project_name,
        "path": project_dir.as_posix(),
        "detectedPragma": detected_pragma,
        "solcVersion": solc_version,
    }
    result_payload["summary"] = {
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status.replace("_", " ").title()),
        "statusTone": STATUS_TONES.get(status, "info"),
        "resultCount": result_count,
        "tokenSent": metadata.get("token_sent", 0),
        "tokenReceived": metadata.get("token_received", 0),
        "tokenSentGpt4": metadata.get("token_sent_gpt4", 0),
        "tokenReceivedGpt4": metadata.get("token_received_gpt4", 0),
        "totalTokens": (
            float(metadata.get("token_sent", 0) or 0)
            + float(metadata.get("token_received", 0) or 0)
            + float(metadata.get("token_sent_gpt4", 0) or 0)
            + float(metadata.get("token_received_gpt4", 0) or 0)
        ),
        "estimatedCost": metadata.get("estimated_cost", 0),
        "usedTimeSeconds": metadata.get("used_time", 0),
    }
    result_payload["findings"] = findings
    result_payload["ui"] = _build_ui_payload(
        status=status,
        result_count=result_count,
        project_name=project_name,
        detected_pragma=detected_pragma,
        solc_version=solc_version,
    )
    return result_payload


def _write_failure_output(
    project_dir: Path,
    output_path: Path,
    *,
    status: str,
    detected_pragma: str,
    used_time: float,
    message: str,
    solc_version: str | None = None,
) -> dict:
    result_payload = {
        "version": "1.1.0",
        "success": False,
        "message": status,
        "results": [],
    }
    metadata = {
        "status": status,
        "detected_pragma": detected_pragma,
        "solc_version": solc_version,
        "result_count": 0,
        "token_sent": 0,
        "token_received": 0,
        "token_sent_gpt4": 0,
        "token_received_gpt4": 0,
        "used_time": used_time,
        "error_message": message,
    }
    _decorate_output_payload(result_payload, metadata, project_dir)
    _write_json(output_path, result_payload)
    _write_json(_metadata_path(output_path), metadata)
    return {"status": status, "result": result_payload, "metadata": metadata}


def scan_project_to_file(project_dir: str | Path, output_path: str | Path, api_key: str | None):
    started_at = time.time()
    project_dir = Path(project_dir).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    pragma_info = detect_project_pragma(project_dir)

    if not pragma_info.found or not pragma_info.supported:
        return _write_failure_output(
            project_dir,
            output_path,
            status="skipped_unsupported_version",
            detected_pragma=pragma_info.detected_pragma,
            used_time=time.time() - started_at,
            message="Project pragma is not supported for the 0.7.x / 0.8.x demo flow.",
        )

    selected_solc_version: str | None = None
    try:
        selected_solc_version = prepare_solc_for_project(project_dir, pragma_info)
        if project_dir.is_dir():
            ensure_project_dependencies(project_dir, selected_solc_version)
        result_payload, metadata = tasks.run_scan(
            project_dir,
            output_path,
            api_key,
            solc_version=selected_solc_version,
        )
    except LLMAPIError as exc:
        return _write_failure_output(
            project_dir,
            output_path,
            status=exc.error_code,
            detected_pragma=pragma_info.detected_pragma,
            used_time=time.time() - started_at,
            message=str(exc),
            solc_version=selected_solc_version,
        )
    except CompileFailure as exc:
        return _write_failure_output(
            project_dir,
            output_path,
            status=exc.error_code,
            detected_pragma=pragma_info.detected_pragma,
            used_time=time.time() - started_at,
            message=str(exc),
            solc_version=selected_solc_version,
        )
    except ParseFailure as exc:
        return _write_failure_output(
            project_dir,
            output_path,
            status=exc.error_code,
            detected_pragma=pragma_info.detected_pragma,
            used_time=time.time() - started_at,
            message=str(exc),
            solc_version=selected_solc_version,
        )
    except Exception as exc:
        return _write_failure_output(
            project_dir,
            output_path,
            status="parse_failed",
            detected_pragma=pragma_info.detected_pragma,
            used_time=time.time() - started_at,
            message=str(exc),
            solc_version=selected_solc_version,
        )

    metadata["status"] = metadata.get("status", "success")
    metadata["detected_pragma"] = pragma_info.detected_pragma
    metadata["solc_version"] = selected_solc_version
    metadata["result_count"] = len(result_payload.get("results", []))
    _decorate_output_payload(result_payload, metadata, project_dir)
    _write_json(output_path, result_payload)
    _write_json(_metadata_path(output_path), metadata)
    return {"status": metadata["status"], "result": result_payload, "metadata": metadata}
