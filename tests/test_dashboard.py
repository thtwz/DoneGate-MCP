from __future__ import annotations

from donegate_mcp.domain.dashboard import build_dashboard
from donegate_mcp.models import Task, TaskStatus, VerificationStatus, WorkflowIntent


def make_task(task_id: str, status: TaskStatus, title: str) -> Task:
    intent = {
        TaskStatus.READY: WorkflowIntent.READY,
        TaskStatus.AWAITING_VERIFICATION: WorkflowIntent.AWAITING_VERIFICATION,
        TaskStatus.VERIFIED: WorkflowIntent.AWAITING_VERIFICATION,
        TaskStatus.BLOCKED: WorkflowIntent.IN_PROGRESS,
    }.get(status, WorkflowIntent.DRAFT)
    task = Task(task_id=task_id, title=title, spec_ref="docs/spec.md", workflow_intent=intent)
    if status == TaskStatus.BLOCKED:
        task.blocked_reason = "waiting"
    if status == TaskStatus.VERIFIED:
        task.verification_status = VerificationStatus.PASSED
    return task


def test_dashboard_prioritizes_blocked_then_verification_then_docs_then_ready() -> None:
    tasks = [
        make_task("TASK-0004", TaskStatus.READY, "ready"),
        make_task("TASK-0003", TaskStatus.VERIFIED, "docs"),
        make_task("TASK-0002", TaskStatus.AWAITING_VERIFICATION, "verify"),
        make_task("TASK-0001", TaskStatus.BLOCKED, "blocked"),
    ]
    summary = build_dashboard("demo", tasks)
    assert [item["task_id"] for item in summary.next_actions] == [
        "TASK-0001",
        "TASK-0002",
        "TASK-0003",
        "TASK-0004",
    ]
