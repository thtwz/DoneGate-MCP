from __future__ import annotations

from pathlib import Path

from donegate_mcp.config import TASKS_DIRNAME
from donegate_mcp.domain.lifecycle import normalize_task
from donegate_mcp.models import Task
from donegate_mcp.storage.fs import atomic_write_json, ensure_dir, read_json


class TaskStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.tasks_dir = ensure_dir(data_root / TASKS_DIRNAME)

    def path_for(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def load(self, task_id: str) -> Task:
        return normalize_task(Task.from_dict(read_json(self.path_for(task_id))))

    def save(self, task: Task) -> Task:
        task = normalize_task(task)
        atomic_write_json(self.path_for(task.task_id), task.to_storage_dict())
        return task

    def list(self) -> list[Task]:
        tasks: list[Task] = []
        for path in sorted(self.tasks_dir.glob("TASK-*.json")):
            tasks.append(normalize_task(Task.from_dict(read_json(path))))
        return tasks
