from __future__ import annotations

from pathlib import Path

DATA_DIRNAME = ".donegate-mcp"
PROJECT_FILENAME = "project.json"
PLAN_FILENAME = "plan.json"
PROGRESS_FILENAME = "progress.json"
SESSION_FILENAME = "session.json"
SUPERVISION_FILENAME = "supervision.json"
DEVIATIONS_FILENAME = "deviations.jsonl"
TASKS_DIRNAME = "tasks"
EVENTS_DIRNAME = "events"
SCHEMA_VERSION = 1
DEFAULT_ENCODING = "utf-8"


def resolve_data_root(root: str | Path | None = None) -> Path:
    if root is None:
        return Path.cwd() / DATA_DIRNAME
    path = Path(root)
    return path if path.is_absolute() else Path.cwd() / path
