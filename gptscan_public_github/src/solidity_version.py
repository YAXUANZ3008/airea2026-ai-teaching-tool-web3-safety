from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from scan_exceptions import CompileFailure


PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
IGNORED_PRAGMA_PARTS = {
    ".git",
    ".github",
    ".gptscan",
    "artifacts",
    "broadcast",
    "cache",
    "discord-export",
    "docs",
    "echidna",
    "lib",
    "mock",
    "mocks",
    "node_modules",
    "out",
    "outside-scope",
    "report",
    "reports",
    "resource",
    "resources",
    "script",
    "scripts",
    "test",
    "tests",
}


@dataclass
class PragmaDetection:
    found: bool
    supported: bool
    detected_pragma: str
    files_scanned: int
    expressions: tuple[str, ...] = ()


def normalize_pragma_expression(expression: str) -> str:
    return " ".join(expression.strip().split())


def _version_key(version: str) -> tuple[int, int, int]:
    return tuple(map(int, version.split(".")))


def _parse_version_token(token: str) -> tuple[int, int, int] | None:
    cleaned = token.strip()
    if not cleaned:
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", cleaned)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def _token_to_string(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _caret_upper_bound(version: tuple[int, int, int]) -> tuple[int, int, int]:
    major, minor, patch = version
    if major > 0:
        return (major + 1, 0, 0)
    if minor > 0:
        return (0, minor + 1, 0)
    return (0, 0, patch + 1)


def _split_version_clauses(expression: str) -> list[tuple[str, tuple[int, int, int]]]:
    normalized = normalize_pragma_expression(expression)
    clauses: list[tuple[str, tuple[int, int, int]]] = []

    if normalized.startswith("^"):
        version = _parse_version_token(normalized[1:])
        if version is None:
            return []
        return [("^", version)]

    bare_version = _parse_version_token(normalized.lstrip("="))
    if bare_version is not None and not any(
        symbol in normalized for symbol in (">", "<", "^", "~", "||")
    ):
        return [("=", bare_version)]

    for operator, version_text in re.findall(r"(>=|<=|>|<|=)\s*(\d+\.\d+(?:\.\d+)?)", normalized):
        version = _parse_version_token(version_text)
        if version is None:
            return []
        clauses.append((operator, version))

    return clauses


def is_supported_solidity_demo(expression: str) -> bool:
    demo_candidates = [f"0.7.{patch}" for patch in range(7)] + [f"0.8.{patch}" for patch in range(35)]
    return resolve_solc_version([expression], demo_candidates) is not None


def _expression_allows_version(expression: str, version: str) -> bool:
    normalized = normalize_pragma_expression(expression)
    candidate = _version_key(version)

    clauses = _split_version_clauses(normalized)
    if not clauses:
        return False

    for operator, value in clauses:
        if operator == "^":
            if not (value <= candidate < _caret_upper_bound(value)):
                return False
        elif operator == "=":
            if candidate != value:
                return False
        elif operator == ">":
            if not (candidate > value):
                return False
        elif operator == ">=":
            if not (candidate >= value):
                return False
        elif operator == "<":
            if not (candidate < value):
                return False
        elif operator == "<=":
            if not (candidate <= value):
                return False
        else:
            return False
    return True


def resolve_solc_version(expressions: list[str] | tuple[str, ...], available_versions: list[str]) -> str | None:
    candidates = sorted(
        [
            normalize_pragma_expression(version)
            for version in available_versions
            if version.startswith("0.7.") or version.startswith("0.8.")
        ],
        key=_version_key,
        reverse=True,
    )
    normalized_expressions = [normalize_pragma_expression(expression) for expression in expressions]
    for candidate in candidates:
        if all(_expression_allows_version(expression, candidate) for expression in normalized_expressions):
            return candidate
    return None


def list_installed_solc_versions() -> list[str]:
    base = Path.home() / ".solc-select" / "artifacts"
    if not base.exists():
        return []
    versions = [
        path.name.replace("solc-", "")
        for path in base.iterdir()
        if path.is_dir() and path.name.startswith("solc-")
    ]
    return sorted(versions, key=_version_key)


def prepare_solc_for_project(project_dir: str | Path, pragma_info: PragmaDetection | None = None) -> str:
    pragma_info = pragma_info or detect_project_pragma(project_dir)
    installed_versions = list_installed_solc_versions()
    selected = resolve_solc_version(pragma_info.expressions, installed_versions)
    if not selected:
        raise CompileFailure(
            f"No installed solc version satisfies project pragmas: {pragma_info.detected_pragma}"
        )
    return selected


def detect_project_pragma(project_dir: str | Path) -> PragmaDetection:
    project_path = Path(project_dir).expanduser().resolve()
    expressions: list[str] = []
    files_scanned = 0

    if project_path.is_file():
        candidate_files = [project_path] if project_path.suffix.lower() == ".sol" else []
    else:
        candidate_files = sorted(project_path.rglob("*.sol"))

    for sol_file in candidate_files:
        if not sol_file.is_file():
            continue
        if any(part.lower() in IGNORED_PRAGMA_PARTS for part in sol_file.parts):
            continue
        files_scanned += 1
        try:
            text = sol_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in PRAGMA_RE.finditer(text):
            expressions.append(normalize_pragma_expression(match.group(1)))

    unique_expressions = sorted(set(expressions))
    detected = " | ".join(unique_expressions)
    installed_versions = list_installed_solc_versions()
    if not installed_versions:
        installed_versions = [f"0.7.{patch}" for patch in range(7)] + [f"0.8.{patch}" for patch in range(35)]
    supported = bool(unique_expressions) and resolve_solc_version(unique_expressions, installed_versions) is not None

    return PragmaDetection(
        found=bool(unique_expressions),
        supported=supported,
        detected_pragma=detected,
        files_scanned=files_scanned,
        expressions=tuple(unique_expressions),
    )
