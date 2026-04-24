from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    DOCUMENTED = "documented"
    DONE = "done"
    BLOCKED = "blocked"


class WorkflowIntent(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"


class VerificationStatus(str, Enum):
    UNKNOWN = "unknown"
    FAILED = "failed"
    PASSED = "passed"


class DocSyncStatus(str, Enum):
    UNKNOWN = "unknown"
    OUTDATED = "outdated"
    SYNCED = "synced"


class ReviewCheckpoint(str, Enum):
    SUBMIT = "submit"
    PRE_DONE = "pre_done"
    MANUAL = "manual"


class ReviewRunStatus(str, Enum):
    REQUESTED = "requested"
    COMPLETED = "completed"


class ReviewRecommendation(str, Enum):
    PROCEED = "proceed"
    PROCEED_WITH_FOLLOWUPS = "proceed_with_followups"
    NEEDS_HUMAN_ATTENTION = "needs_human_attention"


class ReviewFindingSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewFindingDisposition(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    SPAWNED_FOLLOWUP = "spawned_followup"
    WAIVED = "waived"
    RESOLVED = "resolved"


@dataclass(slots=True)
class ProjectState:
    schema_version: int
    project_id: str
    project_name: str
    created_at: str
    updated_at: str
    default_branch: str | None = None
    repo_root: str | None = None
    task_counter: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectState":
        payload = dict(data)
        payload.setdefault("repo_root", None)
        return cls(**payload)


@dataclass(slots=True)
class Task:
    task_id: str
    title: str
    spec_ref: str
    summary: str = ""
    workflow_intent: WorkflowIntent = WorkflowIntent.DRAFT
    blocked_reason: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    verified_at: str | None = None
    documented_at: str | None = None
    done_at: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    doc_sync_status: DocSyncStatus = DocSyncStatus.UNKNOWN
    last_verification_ref: str | None = None
    last_doc_sync_ref: str | None = None
    verification_mode: str = "manual"
    test_commands: list[str] = field(default_factory=list)
    required_doc_refs: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    owned_paths: list[str] = field(default_factory=list)
    last_self_test_at: str | None = None
    last_self_test_exit_code: int | None = None
    last_self_test_ref: str | None = None
    plan_node_id: str | None = None
    spec_version: int | None = None
    spec_hash: str | None = None
    stale_reason: str | None = None
    needs_revalidation: bool = False
    parent_task_id: str | None = None
    source_task_id: str | None = None
    source_finding_id: str | None = None

    @property
    def status(self) -> TaskStatus:
        from donegate_mcp.domain.lifecycle import project_status

        return project_status(self)

    def to_dict(self) -> dict[str, Any]:
        projected_status = self.status
        data = asdict(self)
        data["workflow_intent"] = self.workflow_intent.value
        data["verification_status"] = self.verification_status.value
        data["doc_sync_status"] = self.doc_sync_status.value
        data["status"] = projected_status.value
        data["projected_status"] = projected_status.value
        data["status_source"] = "projected"
        return data

    def to_storage_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["workflow_intent"] = self.workflow_intent.value
        data["verification_status"] = self.verification_status.value
        data["doc_sync_status"] = self.doc_sync_status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        payload = dict(data)
        payload["workflow_intent"] = cls._workflow_intent_from_payload(payload)
        payload["verification_status"] = VerificationStatus(payload["verification_status"])
        payload["doc_sync_status"] = DocSyncStatus(payload["doc_sync_status"])
        payload.setdefault("verification_mode", "manual")
        payload.setdefault("test_commands", [])
        payload.setdefault("required_doc_refs", [])
        payload.setdefault("required_artifacts", [])
        payload.setdefault("owned_paths", [])
        payload.setdefault("last_self_test_at", None)
        payload.setdefault("last_self_test_exit_code", None)
        payload.setdefault("last_self_test_ref", None)
        payload.setdefault("plan_node_id", None)
        payload.setdefault("spec_version", None)
        payload.setdefault("spec_hash", None)
        payload.setdefault("stale_reason", None)
        payload.setdefault("needs_revalidation", False)
        payload.setdefault("parent_task_id", None)
        payload.setdefault("source_task_id", None)
        payload.setdefault("source_finding_id", None)
        payload.pop("status", None)
        payload.pop("projected_status", None)
        payload.pop("status_source", None)
        return cls(**payload)

    @staticmethod
    def _workflow_intent_from_payload(data: dict[str, Any]) -> WorkflowIntent:
        if "workflow_intent" in data:
            return WorkflowIntent(data["workflow_intent"])
        old_status = TaskStatus(data.get("status", TaskStatus.DRAFT.value))
        if old_status == TaskStatus.DRAFT:
            return WorkflowIntent.DRAFT
        if old_status == TaskStatus.READY:
            return WorkflowIntent.READY
        if old_status == TaskStatus.IN_PROGRESS:
            return WorkflowIntent.IN_PROGRESS
        if old_status == TaskStatus.AWAITING_VERIFICATION:
            return WorkflowIntent.AWAITING_VERIFICATION
        if old_status in {TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE}:
            return WorkflowIntent.AWAITING_VERIFICATION
        if old_status == TaskStatus.BLOCKED:
            return WorkflowIntent.IN_PROGRESS
        return WorkflowIntent.DRAFT


@dataclass(slots=True)
class VerificationRecord:
    task_id: str
    result: VerificationStatus
    recorded_at: str
    ref: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["result"] = self.result.value
        return data


@dataclass(slots=True)
class SelfTestRecord:
    task_id: str
    recorded_at: str
    command_count: int
    exit_code: int
    ref: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DocSyncRecord:
    task_id: str
    result: DocSyncStatus
    recorded_at: str
    ref: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["result"] = self.result.value
        return data


@dataclass(slots=True)
class TaskEvent:
    type: str
    timestamp: str
    actor: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DashboardSummary:
    project_name: str
    total_tasks: int
    counts_by_status: dict[str, int]
    blocked_tasks: list[dict[str, Any]]
    missing_verification: list[dict[str, Any]]
    missing_docs: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    open_advisories: int = 0
    high_severity_advisories: int = 0
    pending_advisory_reviews: int = 0
    tasks_with_open_advisories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReviewFinding:
    finding_id: str
    review_run_id: str
    task_id: str
    checkpoint: ReviewCheckpoint
    provider_id: str
    dimension: str
    severity: ReviewFindingSeverity
    title: str
    details: str
    recommended_action: str | None = None
    suggested_task_title: str | None = None
    suggested_task_summary: str | None = None
    suggested_owned_paths: list[str] = field(default_factory=list)
    disposition: ReviewFindingDisposition = ReviewFindingDisposition.OPEN
    followup_task_id: str | None = None
    notes: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checkpoint"] = self.checkpoint.value
        data["severity"] = self.severity.value
        data["disposition"] = self.disposition.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewFinding":
        payload = dict(data)
        payload["checkpoint"] = ReviewCheckpoint(payload["checkpoint"])
        payload["severity"] = ReviewFindingSeverity(payload["severity"])
        payload["disposition"] = ReviewFindingDisposition(payload["disposition"])
        payload.setdefault("recommended_action", None)
        payload.setdefault("suggested_task_title", None)
        payload.setdefault("suggested_task_summary", None)
        payload.setdefault("suggested_owned_paths", [])
        payload.setdefault("followup_task_id", None)
        payload.setdefault("notes", None)
        return cls(**payload)


@dataclass(slots=True)
class ReviewRun:
    review_run_id: str
    task_id: str
    checkpoint: ReviewCheckpoint
    provider_id: str
    status: ReviewRunStatus
    source_task_updated_at: str
    summary: str = ""
    overall_recommendation: ReviewRecommendation = ReviewRecommendation.PROCEED
    request_hint: str | None = None
    finding_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checkpoint"] = self.checkpoint.value
        data["status"] = self.status.value
        data["overall_recommendation"] = self.overall_recommendation.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewRun":
        payload = dict(data)
        payload["checkpoint"] = ReviewCheckpoint(payload["checkpoint"])
        payload["status"] = ReviewRunStatus(payload["status"])
        payload["overall_recommendation"] = ReviewRecommendation(payload["overall_recommendation"])
        payload.setdefault("summary", "")
        payload.setdefault("request_hint", None)
        payload.setdefault("finding_ids", [])
        return cls(**payload)
