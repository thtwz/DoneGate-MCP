from __future__ import annotations

from pathlib import Path

from donegate_mcp.errors import TransitionError
from donegate_mcp.models import DocSyncStatus, Task, TaskStatus, VerificationStatus, WorkflowIntent, utc_now

_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.DRAFT: {TaskStatus.READY, TaskStatus.BLOCKED},
    TaskStatus.READY: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
    TaskStatus.IN_PROGRESS: {TaskStatus.AWAITING_VERIFICATION, TaskStatus.BLOCKED},
    TaskStatus.AWAITING_VERIFICATION: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
    TaskStatus.VERIFIED: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
    TaskStatus.DOCUMENTED: {TaskStatus.DONE, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
    TaskStatus.DONE: set(),
    TaskStatus.BLOCKED: {TaskStatus.DRAFT, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION},
}

_COMPATIBILITY_TARGETS: dict[TaskStatus, str] = {
    TaskStatus.VERIFIED: "target_status=verified is a compatibility alias; prefer intent commands plus fact recording",
    TaskStatus.DOCUMENTED: "target_status=documented is a compatibility alias; prefer verification/doc-sync facts and let projection derive documented",
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def _has_work_evidence(task: Task) -> bool:
    return any(
        (
            task.started_at is not None,
            task.verified_at is not None,
            task.documented_at is not None,
            task.last_self_test_at is not None,
            task.last_verification_ref is not None,
            task.last_doc_sync_ref is not None,
            task.verification_status != VerificationStatus.UNKNOWN,
            task.doc_sync_status != DocSyncStatus.UNKNOWN,
        )
    )


def project_status(task: Task) -> TaskStatus:
    if task.done_at:
        return TaskStatus.DONE
    if task.blocked_reason:
        return TaskStatus.BLOCKED
    if task.needs_revalidation:
        return TaskStatus.IN_PROGRESS
    has_started = _has_work_evidence(task) or task.workflow_intent in {
        WorkflowIntent.IN_PROGRESS,
        WorkflowIntent.AWAITING_VERIFICATION,
    }
    if not has_started:
        return TaskStatus.DRAFT if task.workflow_intent == WorkflowIntent.DRAFT else TaskStatus.READY
    if task.verification_status == VerificationStatus.FAILED:
        return TaskStatus.IN_PROGRESS
    if task.verification_status != VerificationStatus.PASSED:
        return TaskStatus.IN_PROGRESS if task.workflow_intent == WorkflowIntent.IN_PROGRESS else TaskStatus.AWAITING_VERIFICATION
    if task.doc_sync_status != DocSyncStatus.SYNCED:
        return TaskStatus.VERIFIED
    return TaskStatus.DOCUMENTED


def normalize_task(task: Task) -> Task:
    return task


def needs_verification(task: Task) -> bool:
    task = normalize_task(task)
    return task.needs_revalidation or project_status(task) == TaskStatus.AWAITING_VERIFICATION


def needs_docs(task: Task) -> bool:
    task = normalize_task(task)
    return project_status(task) == TaskStatus.VERIFIED


def next_action_rank(task: Task) -> int:
    task = normalize_task(task)
    if task.needs_revalidation:
        return 0
    status = project_status(task)
    if status == TaskStatus.BLOCKED:
        return 1
    if needs_verification(task):
        return 2
    if needs_docs(task):
        return 3
    if status == TaskStatus.READY:
        return 4
    return 9


def compatibility_warning(target: TaskStatus) -> str | None:
    return _COMPATIBILITY_TARGETS.get(target)


def _ensure_paths_exist(paths: list[str], label: str) -> None:
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise TransitionError(f"missing required {label}: {', '.join(missing)}")


def _require_not_terminal_or_blocked(task: Task, target: TaskStatus) -> None:
    current = project_status(task)
    if current == TaskStatus.DONE:
        if target in {TaskStatus.DRAFT, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION, TaskStatus.VERIFIED, TaskStatus.DOCUMENTED}:
            return
        raise TransitionError(f"{task.task_id} is done and cannot move to {target.value}")
    if current == TaskStatus.BLOCKED:
        raise TransitionError(f"{task.task_id} is blocked and cannot move to {target.value}")


def require_transition(task: Task, target: TaskStatus) -> None:
    task = normalize_task(task)
    current = project_status(task)
    if current == target:
        return
    if target == TaskStatus.BLOCKED:
        return
    if current == TaskStatus.DONE and target != TaskStatus.DONE:
        return
    if target in {TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION, TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE}:
        _require_not_terminal_or_blocked(task, target)
    elif not can_transition(current, target):
        raise TransitionError(f"cannot move {task.task_id} from {current.value} to {target.value}")
    if target in {TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE} and task.needs_revalidation:
        raise TransitionError(f"{task.task_id} requires revalidation due to spec drift: {task.stale_reason or 'spec changed'}")
    if target == TaskStatus.VERIFIED and task.verification_status != VerificationStatus.PASSED:
        raise TransitionError(f"{task.task_id} requires passed verification before verified")
    if target == TaskStatus.DOCUMENTED:
        if task.verification_status != VerificationStatus.PASSED:
            raise TransitionError(f"{task.task_id} requires passed verification before documented")
        if task.doc_sync_status != DocSyncStatus.SYNCED:
            raise TransitionError(f"{task.task_id} requires doc sync before documented")
        _ensure_paths_exist(task.required_doc_refs, "doc refs")
    if target == TaskStatus.DONE:
        if task.verification_status != VerificationStatus.PASSED:
            raise TransitionError(f"{task.task_id} cannot be done without passed verification")
        if task.doc_sync_status != DocSyncStatus.SYNCED:
            raise TransitionError(f"{task.task_id} cannot be done without synced docs")
        _ensure_paths_exist(task.required_doc_refs, "doc refs")
        _ensure_paths_exist(task.required_artifacts, "artifacts")


def apply_transition(task: Task, target: TaskStatus) -> Task:
    require_transition(task, target)
    timestamp = utc_now()
    current = project_status(task)
    if current == target:
        if target in {TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION, TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE} and task.started_at is None:
            task.started_at = timestamp
        if target == TaskStatus.VERIFIED:
            task.verified_at = task.verified_at or timestamp
        if target == TaskStatus.DOCUMENTED:
            task.verified_at = task.verified_at or timestamp
            task.documented_at = task.documented_at or timestamp
        if target == TaskStatus.DONE:
            task.verified_at = task.verified_at or timestamp
            task.documented_at = task.documented_at or timestamp
            task.done_at = task.done_at or timestamp
        task.updated_at = timestamp
        return normalize_task(task)
    reopening_from_done = current == TaskStatus.DONE and target != TaskStatus.DONE
    if reopening_from_done:
        task.done_at = None
    if target == TaskStatus.DRAFT:
        task.workflow_intent = WorkflowIntent.DRAFT
    elif target == TaskStatus.READY:
        task.workflow_intent = WorkflowIntent.READY
    elif target == TaskStatus.IN_PROGRESS:
        task.workflow_intent = WorkflowIntent.IN_PROGRESS
    elif target in {TaskStatus.AWAITING_VERIFICATION, TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE}:
        task.workflow_intent = WorkflowIntent.AWAITING_VERIFICATION
    task.updated_at = timestamp
    if target in {TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION, TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE} and task.started_at is None:
        task.started_at = timestamp
    if target == TaskStatus.VERIFIED:
        task.verified_at = task.verified_at or timestamp
    if target == TaskStatus.DOCUMENTED:
        task.verified_at = task.verified_at or timestamp
        task.documented_at = task.documented_at or timestamp
    if target == TaskStatus.DONE:
        task.verified_at = task.verified_at or timestamp
        task.documented_at = task.documented_at or timestamp
        task.done_at = timestamp
    if target != TaskStatus.BLOCKED:
        task.blocked_reason = None
    return normalize_task(task)


def apply_verification(task: Task, result: VerificationStatus, ref: str | None = None) -> Task:
    timestamp = utc_now()
    task.verification_status = result
    task.last_verification_ref = ref
    task.updated_at = timestamp
    task.started_at = task.started_at or timestamp
    if result == VerificationStatus.PASSED:
        task.verified_at = timestamp
        task.needs_revalidation = False
        task.stale_reason = None
    else:
        task.verified_at = None
        task.done_at = None
    return normalize_task(task)


def apply_doc_sync(task: Task, result: DocSyncStatus, ref: str | None = None) -> Task:
    timestamp = utc_now()
    task.doc_sync_status = result
    task.last_doc_sync_ref = ref
    task.updated_at = timestamp
    task.started_at = task.started_at or timestamp
    if result == DocSyncStatus.SYNCED:
        task.documented_at = timestamp
    else:
        task.documented_at = None
        task.done_at = None
    return normalize_task(task)


def apply_block(task: Task, reason: str) -> Task:
    if project_status(task) == TaskStatus.DONE:
        raise TransitionError(f"{task.task_id} is done and cannot be blocked")
    task.blocked_reason = reason
    task.updated_at = utc_now()
    return normalize_task(task)
