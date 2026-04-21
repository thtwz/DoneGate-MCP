from __future__ import annotations

import json

from donegate_mcp.domain.lifecycle import apply_doc_sync, apply_transition, apply_verification, project_status
from donegate_mcp.errors import TransitionError
from donegate_mcp.models import DocSyncStatus, Task, TaskStatus, VerificationStatus


def make_task(status: TaskStatus = TaskStatus.DRAFT) -> Task:
    return Task(task_id="TASK-0001", title="demo", spec_ref="docs/spec.md", status=status)


def test_done_requires_verification_and_docs() -> None:
    task = make_task(TaskStatus.DOCUMENTED)
    task.verification_status = VerificationStatus.UNKNOWN
    task.doc_sync_status = DocSyncStatus.UNKNOWN
    try:
        apply_transition(task, TaskStatus.DONE)
    except TransitionError as exc:
        assert "passed verification" in str(exc)
    else:
        raise AssertionError("expected gate violation")


def test_failed_verification_rewinds_to_in_progress() -> None:
    task = make_task(TaskStatus.DOCUMENTED)
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    updated = apply_verification(task, VerificationStatus.FAILED)
    assert updated.status == TaskStatus.IN_PROGRESS
    assert updated.verification_status == VerificationStatus.FAILED


def test_synced_docs_promotes_verified_to_documented() -> None:
    task = make_task(TaskStatus.VERIFIED)
    task.verification_status = VerificationStatus.PASSED
    updated = apply_doc_sync(task, DocSyncStatus.SYNCED)
    assert updated.status == TaskStatus.DOCUMENTED


def test_passed_verification_promotes_awaiting_verification_to_documented_when_docs_already_synced() -> None:
    task = make_task(TaskStatus.AWAITING_VERIFICATION)
    task.doc_sync_status = DocSyncStatus.SYNCED
    updated = apply_verification(task, VerificationStatus.PASSED)
    assert updated.status == TaskStatus.DOCUMENTED


def test_synced_docs_promotes_awaiting_verification_to_documented_when_verification_already_passed() -> None:
    task = make_task(TaskStatus.AWAITING_VERIFICATION)
    task.verification_status = VerificationStatus.PASSED
    updated = apply_doc_sync(task, DocSyncStatus.SYNCED)
    assert updated.status == TaskStatus.DOCUMENTED


def test_done_succeeds_after_gates() -> None:
    task = make_task(TaskStatus.DOCUMENTED)
    task.started_at = "2026-01-01T00:00:00+00:00"
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    updated = apply_transition(task, TaskStatus.DONE)
    assert updated.status == TaskStatus.DONE
    assert updated.done_at is not None


def test_project_status_is_fact_derived() -> None:
    task = make_task(TaskStatus.IN_PROGRESS)
    task.started_at = "2026-01-01T00:00:00+00:00"
    assert project_status(task) == TaskStatus.IN_PROGRESS
    task.status = TaskStatus.AWAITING_VERIFICATION
    assert project_status(task) == TaskStatus.AWAITING_VERIFICATION
    task.verification_status = VerificationStatus.PASSED
    assert project_status(task) == TaskStatus.VERIFIED
    task.doc_sync_status = DocSyncStatus.SYNCED
    assert project_status(task) == TaskStatus.DOCUMENTED
    task.done_at = "2026-01-02T00:00:00+00:00"
    assert project_status(task) == TaskStatus.DONE


def test_done_transition_can_close_directly_from_ready_when_gates_are_satisfied() -> None:
    task = make_task(TaskStatus.READY)
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    updated = apply_transition(task, TaskStatus.DONE)
    assert updated.status == TaskStatus.DONE
    assert updated.done_at is not None


def test_done_task_can_reopen_to_in_progress() -> None:
    task = make_task(TaskStatus.DONE)
    task.started_at = "2026-01-01T00:00:00+00:00"
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    task.verified_at = "2026-01-01T00:00:00+00:00"
    task.documented_at = "2026-01-01T00:00:00+00:00"
    task.done_at = "2026-01-02T00:00:00+00:00"

    updated = apply_transition(task, TaskStatus.IN_PROGRESS)

    assert updated.status == TaskStatus.DOCUMENTED
    assert updated.done_at is None


def test_done_task_can_reopen_to_ready() -> None:
    task = make_task(TaskStatus.DONE)
    task.started_at = "2026-01-01T00:00:00+00:00"
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    task.done_at = "2026-01-02T00:00:00+00:00"

    updated = apply_transition(task, TaskStatus.READY)

    assert updated.status == TaskStatus.DOCUMENTED
    assert updated.done_at is None


def test_documented_transition_from_ready_normalizes_from_facts() -> None:
    task = make_task(TaskStatus.READY)
    task.verification_status = VerificationStatus.PASSED
    task.doc_sync_status = DocSyncStatus.SYNCED
    updated = apply_transition(task, TaskStatus.DOCUMENTED)
    assert updated.status == TaskStatus.DOCUMENTED


def test_verified_transition_from_ready_marks_work_as_started() -> None:
    task = make_task(TaskStatus.READY)
    task.verification_status = VerificationStatus.PASSED
    updated = apply_transition(task, TaskStatus.VERIFIED)
    assert updated.status == TaskStatus.VERIFIED
    assert updated.started_at is not None
