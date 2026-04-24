from __future__ import annotations

from collections.abc import Callable
from typing import Any

from donegate_mcp.config import SCHEMA_VERSION
from donegate_mcp.domain.dashboard import build_dashboard
from donegate_mcp.domain.lifecycle import normalize_task
from donegate_mcp.models import Task, utc_now
from donegate_mcp.storage.state_store import StateStore
from donegate_mcp.storage.task_store import TaskStore


class ReadModelProjector:
    def __init__(
        self,
        states: StateStore,
        tasks: TaskStore,
        project_name: Callable[[], str],
        advisory_summary: Callable[[str], dict[str, Any]],
    ) -> None:
        self.states = states
        self.tasks = tasks
        self.project_name = project_name
        self.advisory_summary = advisory_summary

    def sync(self) -> list[Task]:
        tasks = []
        for task in self.tasks.list():
            normalized = normalize_task(task)
            self.tasks.save(normalized)
            tasks.append(normalized)
        self._save_plan(tasks)
        self._save_progress(tasks)
        return tasks

    def _save_plan(self, tasks: list[Task]) -> None:
        plan = self.states.load_plan() if self.states.plan_exists() else {"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "nodes": [], "specs": []}
        nodes = []
        spec_map: dict[str, dict[str, Any]] = {}
        for task in tasks:
            node_id = task.plan_node_id or task.task_id.lower()
            nodes.append({
                "node_id": node_id,
                "task_id": task.task_id,
                "title": task.title,
                "spec_ref": task.spec_ref,
                "status": task.status.value,
                "verification_status": task.verification_status.value,
                "doc_sync_status": task.doc_sync_status.value,
                "needs_revalidation": task.needs_revalidation,
                "stale_reason": task.stale_reason,
            })
            spec_map[task.spec_ref] = {"spec_ref": task.spec_ref, "spec_version": task.spec_version, "spec_hash": task.spec_hash}
        plan["updated_at"] = utc_now()
        plan["nodes"] = nodes
        plan["specs"] = list(spec_map.values())
        self.states.save_plan(plan)

    def _save_progress(self, tasks: list[Task]) -> None:
        advisory_summaries = {task.task_id: self.advisory_summary(task.task_id) for task in tasks}
        summary = build_dashboard(self.project_name(), tasks, advisory_summaries=advisory_summaries).to_dict()
        stale_tasks = [
            {"task_id": task.task_id, "title": task.title, "stale_reason": task.stale_reason, "spec_ref": task.spec_ref}
            for task in tasks if task.needs_revalidation
        ]
        progress = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                    "plan_node_id": task.plan_node_id or task.task_id.lower(),
                    "needs_revalidation": task.needs_revalidation,
                    "advisory_summary": advisory_summaries.get(task.task_id),
                }
                for task in tasks
            ],
            "summary": summary,
            "stale_tasks": stale_tasks,
        }
        self.states.save_progress(progress)
