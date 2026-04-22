from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4
from typing import Any

from donegate_mcp.config import DEVIATIONS_FILENAME, SCHEMA_VERSION, resolve_data_root
from donegate_mcp.errors import ValidationError
from donegate_mcp.models import (
    DocSyncRecord,
    DocSyncStatus,
    ProjectState,
    SelfTestRecord,
    Task,
    TaskEvent,
    TaskStatus,
    VerificationRecord,
    VerificationStatus,
    utc_now,
)
from donegate_mcp.domain.dashboard import build_dashboard
from donegate_mcp.domain.lifecycle import apply_block, apply_doc_sync, apply_transition, apply_verification, compatibility_warning, normalize_task
from donegate_mcp.storage.event_store import EventStore
from donegate_mcp.storage.fs import append_jsonl, ensure_dir, make_executable, write_text
from donegate_mcp.storage.project_store import ProjectStore
from donegate_mcp.storage.state_store import StateStore
from donegate_mcp.storage.task_store import TaskStore

_MANAGED_HOOK_MARKER = "# Managed by DoneGate MCP"
_BUNDLED_HOOKS = {
    "pre-commit": "pre-commit.sh",
    "pre-push": "pre-push.sh",
}


class DoneGateService:
    def __init__(self, data_root: str | Path | None = None) -> None:
        self.data_root = resolve_data_root(data_root)
        ensure_dir(self.data_root)
        self.projects = ProjectStore(self.data_root)
        self.tasks = TaskStore(self.data_root)
        self.events = EventStore(self.data_root)
        self.states = StateStore(self.data_root)
        self.artifacts_dir = ensure_dir(self.data_root / "artifacts")
        self.deviations_path = self.data_root / DEVIATIONS_FILENAME

    @staticmethod
    def _bundled_hooks_dir() -> Path:
        return Path(__file__).resolve().parents[3] / "scripts"

    def _hook_payload(self, hook_name: str) -> str:
        source = self._bundled_hooks_dir() / _BUNDLED_HOOKS[hook_name]
        return f"{_MANAGED_HOOK_MARKER}\n{source.read_text(encoding='utf-8')}"

    def _require_project(self) -> ProjectState:
        if not self.projects.exists():
            raise ValidationError(f"project not initialized at {self.data_root}")
        return self.projects.load()

    def _emit(self, task_id: str, event_type: str, payload: dict[str, Any], actor: str = "system") -> TaskEvent:
        event = TaskEvent(type=event_type, timestamp=utc_now(), actor=actor, payload=payload)
        self.events.append(task_id, event)
        return event

    def _init_state_files(self) -> None:
        if not self.states.plan_exists():
            self.states.save_plan({"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "nodes": [], "specs": []})
        if not self.states.progress_exists():
            self.states.save_progress({"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "tasks": [], "summary": {}, "stale_tasks": []})
        if not self.states.session_exists():
            self.states.save_session({"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "active_task_id": None})
        if not self.states.supervision_exists():
            self.states.save_supervision({"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "repo_root": None, "status": "clean", "changed_files": [], "active_task_id": None})

    def _session_payload(self) -> dict[str, Any]:
        self._init_state_files()
        return self.states.load_session()

    def _current_active_task(self) -> Task | None:
        session = self._session_payload()
        task_id = session.get("active_task_id")
        if not task_id:
            return None
        task = normalize_task(self.tasks.load(task_id))
        self.tasks.save(task)
        return task

    @staticmethod
    def _git_changed_files(repo_root: Path) -> list[str]:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValidationError(f"not a git repository: {repo_root}")
        changed: list[str] = []
        for raw_line in completed.stdout.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            path = line[3:] if len(line) > 3 else ""
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path == ".donegate-mcp" or path.startswith(".donegate-mcp/"):
                continue
            changed.append(path)
        return sorted(changed)

    def _spec_snapshot(self, spec_ref: str) -> tuple[int | None, str | None]:
        path = Path(spec_ref)
        if not path.exists():
            return None, None
        content = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return 1, digest

    def _load_tasks(self, *, normalize: bool = False, persist: bool = False) -> list[Task]:
        tasks = self.tasks.list()
        if not normalize:
            return tasks
        normalized: list[Task] = []
        for task in tasks:
            normalized_task = normalize_task(task)
            normalized.append(normalized_task)
            if persist:
                self.tasks.save(normalized_task)
        return normalized

    def _sync_state_files(self) -> None:
        tasks = self._load_tasks(normalize=True, persist=True)
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

        summary = build_dashboard(self._require_project().project_name, tasks).to_dict()
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
                }
                for task in tasks
            ],
            "summary": summary,
            "stale_tasks": stale_tasks,
        }
        self.states.save_progress(progress)

    def _mark_spec_drift(self, task: Task, reason: str) -> None:
        task.needs_revalidation = True
        task.stale_reason = reason
        task.verification_status = VerificationStatus.UNKNOWN
        task.doc_sync_status = DocSyncStatus.OUTDATED if task.doc_sync_status == DocSyncStatus.SYNCED else task.doc_sync_status
        if task.status in {TaskStatus.VERIFIED, TaskStatus.DOCUMENTED, TaskStatus.DONE}:
            task.status = TaskStatus.IN_PROGRESS
        task.done_at = None
        task.documented_at = None if task.doc_sync_status != DocSyncStatus.SYNCED else task.documented_at
        task.updated_at = utc_now()

    def init_project(self, project_name: str, default_branch: str | None = None) -> dict[str, Any]:
        now = utc_now()
        project = ProjectState(schema_version=SCHEMA_VERSION, project_id=str(uuid4()), project_name=project_name, created_at=now, updated_at=now, default_branch=default_branch, task_counter=0)
        self.projects.save(project)
        self._init_state_files()
        self._sync_state_files()
        return {"ok": True, "project": project.to_dict(), "data_root": str(self.data_root)}

    def bootstrap_repository(self, project_name: str, repo_root: str | Path | None = None, default_branch: str | None = None) -> dict[str, Any]:
        repo = Path(repo_root) if repo_root is not None else Path.cwd()
        hooks_dir = ensure_dir(repo / ".git" / "hooks")
        if not self.projects.exists():
            self.init_project(project_name, default_branch=default_branch)
        project = self._require_project()

        installed: list[str] = []
        skipped: list[str] = []
        for hook_name in _BUNDLED_HOOKS:
            destination = hooks_dir / hook_name
            payload = self._hook_payload(hook_name)
            if destination.exists():
                current = destination.read_text(encoding="utf-8")
                if not current.startswith(_MANAGED_HOOK_MARKER):
                    skipped.append(hook_name)
                    continue
            write_text(destination, payload)
            make_executable(destination)
            installed.append(hook_name)

        return {
            "ok": True,
            "project": project.to_dict(),
            "data_root": str(self.data_root),
            "repo_root": str(repo),
            "hooks": {"installed": installed, "skipped": skipped},
        }

    def create_task(self, title: str, spec_ref: str, summary: str = "", verification_mode: str = "manual", test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, plan_node_id: str | None = None) -> dict[str, Any]:
        project = self._require_project()
        project.task_counter += 1
        project.updated_at = utc_now()
        task_id = f"TASK-{project.task_counter:04d}"
        spec_version, spec_hash = self._spec_snapshot(spec_ref)
        task = Task(task_id=task_id, title=title, spec_ref=spec_ref, summary=summary, status=TaskStatus.DRAFT, verification_mode=verification_mode, test_commands=list(test_commands or []), required_doc_refs=list(required_doc_refs or []), required_artifacts=list(required_artifacts or []), plan_node_id=plan_node_id or task_id.lower(), spec_version=spec_version, spec_hash=spec_hash)
        self.projects.save(project)
        self.tasks.save(task)
        self._emit(task_id, "task_created", task.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "events_written": 1, "errors": []}

    def activate_task(self, task_id: str) -> dict[str, Any]:
        self._require_project()
        task = normalize_task(self.tasks.load(task_id))
        self.tasks.save(task)
        session = self._session_payload()
        session["active_task_id"] = task.task_id
        session["updated_at"] = utc_now()
        self.states.save_session(session)
        self._emit(task.task_id, "active_task_changed", {"active_task_id": task.task_id})
        return {"ok": True, "active_task": task.to_dict(), "session": session, "errors": []}

    def get_active_task(self) -> dict[str, Any]:
        self._require_project()
        session = self._session_payload()
        task = self._current_active_task()
        return {"ok": True, "active_task": task.to_dict() if task else None, "session": session, "errors": []}

    def clear_active_task(self) -> dict[str, Any]:
        self._require_project()
        session = self._session_payload()
        previous_task = self._current_active_task()
        session["active_task_id"] = None
        session["updated_at"] = utc_now()
        self.states.save_session(session)
        self._emit(previous_task.task_id if previous_task else "project", "active_task_cleared", {"previous_task_id": previous_task.task_id if previous_task else None})
        return {"ok": True, "active_task": None, "session": session, "errors": []}

    def get_supervision(self, repo_root: str | Path | None = None) -> dict[str, Any]:
        self._require_project()
        repo = Path(repo_root) if repo_root is not None else Path.cwd()
        changed_files = self._git_changed_files(repo)
        active_task = self._current_active_task()
        if not changed_files:
            status = "clean"
        elif active_task is None:
            status = "needs_task"
        else:
            status = "tracked"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "repo_root": str(repo),
            "status": status,
            "changed_files": changed_files,
            "active_task_id": active_task.task_id if active_task else None,
            "active_task": active_task.to_dict() if active_task else None,
        }
        self.states.save_supervision(payload)
        return {"ok": True, "supervision": payload, "errors": []}

    def list_tasks(self, status: str | None = None, limit: int | None = None) -> dict[str, Any]:
        self._require_project()
        tasks = self._load_tasks(normalize=True, persist=True)
        if status:
            expected = TaskStatus(status)
            tasks = [task for task in tasks if task.status == expected]
        if limit is not None:
            tasks = tasks[:limit]
        return {"ok": True, "tasks": [task.to_dict() for task in tasks], "errors": []}

    def transition_task(self, task_id: str, target_status: str, reason: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        target = TaskStatus(target_status)
        warnings: list[str] = []
        warning = compatibility_warning(target)
        if warning:
            warnings.append(warning)
        if target_status == TaskStatus.BLOCKED.value:
            if not reason:
                raise ValidationError("reason is required for block transition")
            task = apply_block(task, reason)
        else:
            task = apply_transition(task, target)
        self.tasks.save(task)
        self._emit(task.task_id, "status_changed", {"target_status": task.status.value, "reason": reason, "notes": notes})
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "events_written": 1, "errors": [], "warnings": warnings}

    def record_verification(self, task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        status = VerificationStatus(result)
        task = apply_verification(task, status, ref=ref)
        record = VerificationRecord(task_id=task_id, result=status, recorded_at=utc_now(), ref=ref, notes=notes)
        self.tasks.save(task)
        self._emit(task.task_id, "verification_recorded", record.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "record": record.to_dict(), "events_written": 1, "errors": []}

    def record_doc_sync(self, task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        status = DocSyncStatus(result)
        task = apply_doc_sync(task, status, ref=ref)
        record = DocSyncRecord(task_id=task_id, result=status, recorded_at=utc_now(), ref=ref, notes=notes)
        self.tasks.save(task)
        self._emit(task.task_id, "doc_sync_recorded", record.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "record": record.to_dict(), "events_written": 1, "errors": []}

    def update_acceptance_protocol(self, task_id: str, verification_mode: str | None = None, test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, plan_node_id: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        if verification_mode is not None:
            task.verification_mode = verification_mode
        if test_commands is not None:
            task.test_commands = list(test_commands)
        if required_doc_refs is not None:
            task.required_doc_refs = list(required_doc_refs)
        if required_artifacts is not None:
            task.required_artifacts = list(required_artifacts)
        if plan_node_id is not None:
            task.plan_node_id = plan_node_id
        task.updated_at = utc_now()
        self.tasks.save(task)
        self._emit(task.task_id, "acceptance_protocol_updated", task.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "events_written": 1, "errors": []}

    def run_self_test(self, task_id: str, workdir: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        if not task.test_commands:
            raise ValidationError(f"{task_id} has no test_commands configured")
        target_dir = Path(workdir) if workdir else Path.cwd()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        exit_code = 0
        for command in task.test_commands:
            completed = subprocess.run(command, shell=True, cwd=target_dir, capture_output=True, text=True)
            stdout_chunks.append(f"$ {command}\n{completed.stdout}")
            stderr_chunks.append(f"$ {command}\n{completed.stderr}")
            if completed.returncode != 0:
                exit_code = completed.returncode
                break
        artifact_dir = ensure_dir(self.artifacts_dir / task_id)
        timestamp = utc_now().replace(":", "-")
        stdout_path = artifact_dir / f"self-test-{timestamp}.stdout.log"
        stderr_path = artifact_dir / f"self-test-{timestamp}.stderr.log"
        stdout_path.write_text("\n".join(stdout_chunks), encoding="utf-8")
        stderr_path.write_text("\n".join(stderr_chunks), encoding="utf-8")
        record = SelfTestRecord(task_id=task_id, recorded_at=utc_now(), command_count=len(task.test_commands), exit_code=exit_code, ref=str(stdout_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path), commands=list(task.test_commands))
        task.last_self_test_at = record.recorded_at
        task.last_self_test_exit_code = exit_code
        task.last_self_test_ref = str(stdout_path)
        task.updated_at = utc_now()
        self.tasks.save(task)
        self._emit(task.task_id, "self_test_recorded", record.to_dict())
        verification = self.record_verification(task_id, "passed" if exit_code == 0 else "failed", ref=str(stdout_path), notes="self-test")
        verification["self_test"] = record.to_dict()
        verification["exit_code"] = exit_code
        return verification

    def refresh_spec(self, spec_ref: str, reason: str | None = None) -> dict[str, Any]:
        self._require_project()
        spec_version, spec_hash = self._spec_snapshot(spec_ref)
        if spec_hash is None:
            raise ValidationError(f"spec not found: {spec_ref}")
        changed: list[str] = []
        for task in self.tasks.list():
            if task.spec_ref != spec_ref:
                continue
            if task.spec_hash != spec_hash:
                self._mark_spec_drift(task, reason or "spec hash changed")
                task.spec_version = spec_version
                task.spec_hash = spec_hash
                self.tasks.save(task)
                self._emit(task.task_id, "spec_drift_detected", {"spec_ref": spec_ref, "spec_hash": spec_hash, "reason": task.stale_reason})
                changed.append(task.task_id)
        self._sync_state_files()
        return {"ok": True, "spec_ref": spec_ref, "spec_version": spec_version, "spec_hash": spec_hash, "changed_tasks": changed, "errors": []}

    def record_deviation(self, task_id: str, summary: str, details: str, spec_ref: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        row = {
            "timestamp": utc_now(),
            "task_id": task_id,
            "summary": summary,
            "details": details,
            "spec_ref": spec_ref or task.spec_ref,
            "plan_node_id": task.plan_node_id,
        }
        append_jsonl(self.deviations_path, row)
        self._emit(task_id, "deviation_recorded", row)
        return {"ok": True, "deviation": row, "errors": []}

    def list_deviations(self) -> dict[str, Any]:
        rows = []
        if self.deviations_path.exists():
            rows = [json.loads(line) for line in self.deviations_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        return {"ok": True, "deviations": rows, "errors": []}

    def get_plan(self) -> dict[str, Any]:
        self._require_project()
        self._sync_state_files()
        return {"ok": True, "plan": self.states.load_plan(), "errors": []}

    def get_progress(self) -> dict[str, Any]:
        self._require_project()
        self._sync_state_files()
        return {"ok": True, "progress": self.states.load_progress(), "errors": []}

    def block_task(self, task_id: str, reason: str) -> dict[str, Any]:
        return self.transition_task(task_id, TaskStatus.BLOCKED.value, reason=reason)

    def unblock_task(self, task_id: str, target_status: str) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        if task.status != TaskStatus.BLOCKED:
            raise ValidationError(f"{task_id} is not blocked")
        task.blocked_reason = None
        task = apply_transition(task, TaskStatus(target_status))
        self.tasks.save(task)
        self._emit(task.task_id, "task_unblocked", {"target_status": task.status.value})
        self._sync_state_files()
        return {"ok": True, "task": task.to_dict(), "events_written": 1, "errors": []}

    def dashboard(self, include_tasks: bool = False, limit: int = 10) -> dict[str, Any]:
        project = self._require_project()
        tasks = self._load_tasks(normalize=True, persist=True)
        summary = build_dashboard(project.project_name, tasks, limit=limit)
        payload: dict[str, Any] = {"ok": True, "dashboard": summary.to_dict(), "errors": []}
        if include_tasks:
            payload["tasks"] = [task.to_dict() for task in tasks[:limit]]
        return payload
