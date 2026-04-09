from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SRC_DIR.parent
RULES_DIR = SRC_DIR / "rules"
TASKS_DIR = SRC_DIR / "tasks"
JARS_DIR = SRC_DIR / "jars"
ANTLR4HELPER_DIR = SRC_DIR / "antlr4helper"
WHITELIST_PATH = SRC_DIR / "whitelist.json"
MODIFIER_WHITELIST_PATH = SRC_DIR / "modifier_whitelist.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output"


def ensure_parent_dir(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_project_work_dir(project_root: str | Path) -> Path:
    base = Path(project_root).expanduser().resolve()
    if base.is_file():
        base = base.parent
    work_dir = base / ".gptscan"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def project_work_file(project_root: str | Path, filename: str) -> Path:
    return ensure_project_work_dir(project_root) / filename
