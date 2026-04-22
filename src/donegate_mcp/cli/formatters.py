from __future__ import annotations

import json
from typing import Any


def render(payload: dict[str, Any], as_json: bool) -> str:
    if as_json:
        return json.dumps(payload, indent=2, sort_keys=True)
    if not payload.get("ok", False):
        return "ERROR: " + "; ".join(payload.get("errors", ["unknown error"]))
    if "task" in payload:
        task = payload["task"]
        return f"{task['task_id']} {task['status']} {task['title']}"
    if "dashboard" in payload:
        dashboard = payload["dashboard"]
        return f"{dashboard['project_name']}: {dashboard['total_tasks']} tasks"
    if "supervision" in payload:
        supervision = payload["supervision"]
        return f"{supervision['status']}: {len(supervision['changed_files'])} changed files"
    if "tasks" in payload:
        return "\n".join(f"{task['task_id']} {task['status']} {task['title']}" for task in payload["tasks"]) or "no tasks"
    if "project" in payload:
        project = payload["project"]
        return f"initialized {project['project_name']}"
    if "active_task" in payload:
        task = payload["active_task"]
        if task is None:
            return "no active task"
        return f"active {task['task_id']} {task['status']} {task['title']}"
    return "ok"
