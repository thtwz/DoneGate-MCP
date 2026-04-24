from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import PurePosixPath
from pathlib import Path
from uuid import uuid4
from typing import Any

from donegate_mcp.config import DEVIATIONS_FILENAME, SCHEMA_VERSION, resolve_data_root
from donegate_mcp.errors import ValidationError
from donegate_mcp.domain.review_providers import get_review_provider
from donegate_mcp.models import (
    DocSyncRecord,
    DocSyncStatus,
    ProjectState,
    ReviewCheckpoint,
    ReviewFinding,
    ReviewFindingDisposition,
    ReviewFindingSeverity,
    ReviewRecommendation,
    ReviewRun,
    ReviewRunStatus,
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
from donegate_mcp.storage.review_store import ReviewFindingStore, ReviewRunStore
from donegate_mcp.storage.state_store import StateStore
from donegate_mcp.storage.task_store import TaskStore

_MANAGED_HOOK_MARKER = "# Managed by DoneGate"
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
        self.review_runs = ReviewRunStore(self.data_root)
        self.review_findings = ReviewFindingStore(self.data_root)
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
            self.states.save_supervision({
                "schema_version": SCHEMA_VERSION,
                "updated_at": utc_now(),
                "repo_root": None,
                "status": "clean",
                "changed_files": [],
                "covered_files": [],
                "uncovered_files": [],
                "active_task_id": None,
                "policy": self._supervision_policy("clean"),
            })

    def _session_payload(self) -> dict[str, Any]:
        self._init_state_files()
        session = self.states.load_session()
        session.setdefault("active_task_id", None)
        session.setdefault("active_tasks_by_branch", {})
        session.setdefault("last_repo_root", None)
        return session

    @staticmethod
    def _resolve_repo_root(repo_root: str | Path | None, project: ProjectState | None = None, data_root: Path | None = None) -> Path | None:
        if repo_root is not None:
            return Path(repo_root).resolve()
        if project and project.repo_root:
            return Path(project.repo_root).resolve()
        if data_root is not None:
            return data_root.parent.resolve()
        return None

    @staticmethod
    def _git_current_branch(repo_root: Path | None) -> str | None:
        if repo_root is None:
            return None
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        branch = completed.stdout.strip()
        return branch or None

    @staticmethod
    def _git_path(repo_root: Path, path_name: str) -> Path:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-path", path_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValidationError(f"not a git repository: {repo_root}")
        raw = completed.stdout.strip()
        path = Path(raw)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        return path

    @staticmethod
    def _normalize_repo_path(value: str | None, repo_root: Path | None) -> str | None:
        if value is None or repo_root is None:
            return value
        if "://" in value:
            return value
        path = Path(value)
        if path.is_absolute():
            return str(path.resolve())
        return str((repo_root / path).resolve())

    @staticmethod
    def _normalize_owned_path(value: str | None, repo_root: Path | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        has_glob = any(char in text for char in "*?[]")
        if repo_root is None:
            return text.replace("\\", "/").removeprefix("./").strip("/")
        if has_glob:
            if Path(text).is_absolute():
                raise ValidationError("owned_paths glob patterns must be relative to repo_root")
            return text.replace("\\", "/").removeprefix("./").strip("/")
        path = Path(text)
        resolved = path.resolve() if path.is_absolute() else (repo_root / path).resolve()
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise ValidationError(f"owned_paths entry must stay inside repo_root: {value}") from exc

    @staticmethod
    def _path_matches_owned_path(path: str, owned_path: str) -> bool:
        normalized_path = path.replace("\\", "/").strip("/")
        normalized_scope = owned_path.replace("\\", "/").strip("/")
        if not normalized_scope:
            return True
        if any(char in normalized_scope for char in "*?[]"):
            return PurePosixPath(normalized_path).match(normalized_scope)
        return normalized_path == normalized_scope or normalized_path.startswith(f"{normalized_scope}/")

    def _classify_changed_files(self, changed_files: list[str], active_task: Task | None) -> tuple[list[str], list[str]]:
        if active_task is None or not active_task.owned_paths:
            return list(changed_files), []
        covered: list[str] = []
        uncovered: list[str] = []
        for path in changed_files:
            if any(self._path_matches_owned_path(path, owned_path) for owned_path in active_task.owned_paths):
                covered.append(path)
            else:
                uncovered.append(path)
        return covered, uncovered

    @staticmethod
    def _supervision_policy(status: str) -> dict[str, dict[str, str]]:
        action_map = {
            "clean": {"pre_commit": "allow", "pre_push": "allow"},
            "tracked": {"pre_commit": "allow", "pre_push": "allow"},
            "stale_verification": {"pre_commit": "warn", "pre_push": "block"},
            "stale_docs": {"pre_commit": "warn", "pre_push": "block"},
            "needs_task": {"pre_commit": "block", "pre_push": "block"},
            "task_mismatch": {"pre_commit": "block", "pre_push": "block"},
            "needs_revalidation": {"pre_commit": "block", "pre_push": "block"},
        }
        actions = action_map.get(status, {"pre_commit": "allow", "pre_push": "allow"})
        return {
            "pre_commit": {
                "action": actions["pre_commit"],
                "reason": status,
            },
            "pre_push": {
                "action": actions["pre_push"],
                "reason": status,
            },
        }

    @staticmethod
    def _review_run_id() -> str:
        return f"REVIEW-{uuid4().hex[:8]}"

    @staticmethod
    def _review_finding_id() -> str:
        return f"FINDING-{uuid4().hex[:8]}"

    def _list_review_runs(
        self,
        *,
        task_id: str | None = None,
        checkpoint: ReviewCheckpoint | None = None,
        status: ReviewRunStatus | None = None,
    ) -> list[ReviewRun]:
        runs = self.review_runs.list()
        if task_id is not None:
            runs = [run for run in runs if run.task_id == task_id]
        if checkpoint is not None:
            runs = [run for run in runs if run.checkpoint == checkpoint]
        if status is not None:
            runs = [run for run in runs if run.status == status]
        return sorted(runs, key=lambda run: (run.created_at, run.review_run_id))

    def _list_review_findings(
        self,
        *,
        task_id: str | None = None,
        review_run_id: str | None = None,
        disposition: ReviewFindingDisposition | None = None,
    ) -> list[ReviewFinding]:
        findings = self.review_findings.list()
        if task_id is not None:
            findings = [finding for finding in findings if finding.task_id == task_id]
        if review_run_id is not None:
            findings = [finding for finding in findings if finding.review_run_id == review_run_id]
        if disposition is not None:
            findings = [finding for finding in findings if finding.disposition == disposition]
        return sorted(findings, key=lambda finding: (finding.created_at, finding.finding_id))

    def _advisory_summary(self, task_id: str) -> dict[str, Any]:
        runs = self._list_review_runs(task_id=task_id)
        findings = self._list_review_findings(task_id=task_id)
        open_findings = [finding for finding in findings if finding.disposition in {ReviewFindingDisposition.OPEN, ReviewFindingDisposition.ACCEPTED, ReviewFindingDisposition.SPAWNED_FOLLOWUP}]
        high_findings = [finding for finding in open_findings if finding.severity == ReviewFindingSeverity.HIGH]
        pending_runs = [run for run in runs if run.status == ReviewRunStatus.REQUESTED]
        completed_runs = [run for run in runs if run.status == ReviewRunStatus.COMPLETED]
        latest_completed = completed_runs[-1] if completed_runs else None
        return {
            "open_advisories": len(open_findings),
            "high_severity_advisories": len(high_findings),
            "pending_reviews": len(pending_runs),
            "last_reviewed_at": latest_completed.updated_at if latest_completed else None,
            "last_review_recommendation": latest_completed.overall_recommendation.value if latest_completed else None,
        }

    def _task_payload(self, task: Task) -> dict[str, Any]:
        payload = task.to_dict()
        payload["advisory_summary"] = self._advisory_summary(task.task_id)
        return payload

    def _normalize_checkpoint(self, checkpoint: str) -> ReviewCheckpoint:
        try:
            return ReviewCheckpoint(checkpoint)
        except ValueError as exc:
            raise ValidationError(f"unknown review checkpoint: {checkpoint}") from exc

    def _normalize_recommendation(self, recommendation: str) -> ReviewRecommendation:
        try:
            return ReviewRecommendation(recommendation)
        except ValueError as exc:
            raise ValidationError(f"unknown review recommendation: {recommendation}") from exc

    def _normalize_review_run_status(self, status: str) -> ReviewRunStatus:
        try:
            return ReviewRunStatus(status)
        except ValueError as exc:
            raise ValidationError(f"unknown review status: {status}") from exc

    def _normalize_finding_severity(self, severity: str) -> ReviewFindingSeverity:
        try:
            return ReviewFindingSeverity(severity)
        except ValueError as exc:
            raise ValidationError(f"unknown review finding severity: {severity}") from exc

    def _normalize_finding_disposition(self, disposition: str) -> ReviewFindingDisposition:
        try:
            return ReviewFindingDisposition(disposition)
        except ValueError as exc:
            raise ValidationError(f"unknown review finding disposition: {disposition}") from exc

    @staticmethod
    def _required_finding_field(finding_payload: dict[str, Any], field_name: str) -> str:
        value = finding_payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"review finding requires non-empty {field_name}")
        return value

    def _finding_payload(self, finding: ReviewFinding) -> dict[str, Any]:
        return finding.to_dict()

    def _review_run_payload(self, run: ReviewRun, *, include_findings: bool = False) -> dict[str, Any]:
        payload = run.to_dict()
        if include_findings:
            payload["findings"] = [finding.to_dict() for finding in self._list_review_findings(review_run_id=run.review_run_id)]
        return payload

    def _ensure_advisory_review_request(
        self,
        task: Task,
        checkpoint: ReviewCheckpoint,
        provider_id: str = "host_skill",
    ) -> ReviewRun | None:
        existing = [
            run
            for run in self._list_review_runs(task_id=task.task_id, checkpoint=checkpoint)
            if run.source_task_updated_at == task.updated_at
        ]
        if existing:
            return existing[-1]
        provider = get_review_provider(provider_id)
        review_run = ReviewRun(
            review_run_id=self._review_run_id(),
            task_id=task.task_id,
            checkpoint=checkpoint,
            provider_id=provider.provider_id,
            status=ReviewRunStatus.REQUESTED,
            source_task_updated_at=task.updated_at,
            request_hint=provider.build_request_hint(task, checkpoint),
            overall_recommendation=ReviewRecommendation.NEEDS_HUMAN_ATTENTION,
        )
        self.review_runs.save(review_run)
        self._emit(
            task.task_id,
            "advisory_review_requested",
            {
                "review_run_id": review_run.review_run_id,
                "checkpoint": checkpoint.value,
                "provider_id": provider.provider_id,
                "source_task_updated_at": task.updated_at,
            },
        )
        return review_run

    def _write_onboarding_assets(self, repo_root: Path, project: ProjectState) -> dict[str, str]:
        env_path = (self.data_root / "env.sh").resolve()
        onboarding_dir = ensure_dir(self.data_root / "onboarding")
        codex_path = (onboarding_dir / "codex.md").resolve()
        hermes_path = (onboarding_dir / "hermes-mcp.yaml").resolve()
        data_root = self.data_root.resolve()
        repo_root = repo_root.resolve()

        env_content = (
            f'export DONEGATE_MCP_ROOT="{data_root}"\n'
            f'export DONEGATE_MCP_WORKDIR="{repo_root}"\n'
            f'export DONEGATE_MCP_REPO_ROOT="{repo_root}"\n'
        )
        codex_content = (
            f"# DoneGate onboarding for {project.project_name}\n\n"
            f"1. Source `{env_path}` in the shell that launches Codex so shared plugins inherit `DONEGATE_MCP_ROOT` and `DONEGATE_MCP_REPO_ROOT`.\n"
            f"2. Start by checking `donegate-mcp --json onboarding --repo-root . --agent codex`.\n"
            f"3. When calling DoneGate tools from a shared Codex plugin, pass `repo_root` explicitly if the host did not inherit the repo-local environment.\n"
            f"4. If no branch task is active, create or activate one before editing code.\n"
            f"5. Use `donegate-mcp --json task active --repo-root .` to confirm branch binding.\n"
        )
        hermes_content = (
            "# Generated Hermes MCP config snippet\n"
            "mcp_servers:\n"
            "  donegate_mcp:\n"
            f'    command: "{sys.executable}"\n'
            "    args:\n"
            "      - \"-c\"\n"
            "      - |\n"
            "        from donegate_mcp.mcp.server import build_app\n"
            f"        app = build_app({str(data_root)!r})\n"
            "        server = app.server\n"
            "        if hasattr(server, 'run'):\n"
            "            server.run()\n"
            "        else:\n"
            "            print('donegate-mcp fallback server loaded; use CLI for local dev')\n"
            "    timeout: 120\n"
            "    connect_timeout: 30\n"
        )
        write_text(env_path, env_content)
        write_text(codex_path, codex_content)
        write_text(hermes_path, hermes_content)
        make_executable(env_path)
        return {
            "env": str(env_path),
            "codex": str(codex_path),
            "hermes": str(hermes_path),
        }

    def _current_active_task(self, repo_root: str | Path | None = None) -> Task | None:
        session = self._session_payload()
        project = self._require_project()
        resolved_repo = self._resolve_repo_root(repo_root, project=project, data_root=self.data_root)
        branch = self._git_current_branch(resolved_repo)
        branch_map = session.get("active_tasks_by_branch", {})
        task_id = branch_map.get(branch) if branch else None
        if not task_id:
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

        advisory_summaries = {task.task_id: self._advisory_summary(task.task_id) for task in tasks}
        summary = build_dashboard(self._require_project().project_name, tasks, advisory_summaries=advisory_summaries).to_dict()
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

    def init_project(self, project_name: str, default_branch: str | None = None, repo_root: str | Path | None = None) -> dict[str, Any]:
        now = utc_now()
        resolved_repo = self._resolve_repo_root(repo_root, data_root=self.data_root)
        project = ProjectState(schema_version=SCHEMA_VERSION, project_id=str(uuid4()), project_name=project_name, created_at=now, updated_at=now, default_branch=default_branch, repo_root=str(resolved_repo) if resolved_repo else None, task_counter=0)
        self.projects.save(project)
        self._init_state_files()
        self._sync_state_files()
        return {"ok": True, "project": project.to_dict(), "data_root": str(self.data_root)}

    def bootstrap_repository(self, project_name: str, repo_root: str | Path | None = None, default_branch: str | None = None) -> dict[str, Any]:
        repo = Path(repo_root) if repo_root is not None else Path.cwd()
        if not self.projects.exists():
            self.init_project(project_name, default_branch=default_branch, repo_root=repo)
        project = self._require_project()
        hooks_dir = ensure_dir(self._git_path(repo.resolve(), "hooks"))

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

        onboarding_files = self._write_onboarding_assets(repo.resolve(), project)
        branch = self._git_current_branch(repo.resolve())

        return {
            "ok": True,
            "project": project.to_dict(),
            "data_root": str(self.data_root),
            "repo_root": str(repo),
            "hooks": {"installed": installed, "skipped": skipped},
            "onboarding": {
                "branch": branch,
                "worktree_name": repo.resolve().name,
                "files": onboarding_files,
            },
        }

    def get_onboarding(self, agent: str = "codex", repo_root: str | Path | None = None) -> dict[str, Any]:
        project = self._require_project()
        repo = self._resolve_repo_root(repo_root, project=project, data_root=self.data_root) or Path.cwd()
        files = self._write_onboarding_assets(repo, project)
        branch = self._git_current_branch(repo)
        active_task = self._current_active_task(repo_root=repo)
        if active_task is not None:
            recommended_next_step = "donegate-mcp --data-root .donegate-mcp --json task active --repo-root ."
        else:
            recommended_next_step = "donegate-mcp --data-root .donegate-mcp --json task list --limit 10 && donegate-mcp --data-root .donegate-mcp task activate TASK-XXXX --repo-root ."
        return {
            "ok": True,
            "onboarding": {
                "agent": agent,
                "repo_root": str(repo),
                "branch": branch,
                "worktree_name": repo.name,
                "active_task": active_task.to_dict() if active_task else None,
                "files": files,
                "env_source_command": f"source {files['env']}",
                "recommended_next_step": recommended_next_step,
            },
            "errors": [],
        }

    def create_task(
        self,
        title: str,
        spec_ref: str,
        summary: str = "",
        verification_mode: str = "manual",
        test_commands: list[str] | None = None,
        required_doc_refs: list[str] | None = None,
        required_artifacts: list[str] | None = None,
        owned_paths: list[str] | None = None,
        plan_node_id: str | None = None,
        parent_task_id: str | None = None,
        source_task_id: str | None = None,
        source_finding_id: str | None = None,
    ) -> dict[str, Any]:
        project = self._require_project()
        repo_root = self._resolve_repo_root(None, project=project, data_root=self.data_root)
        normalized_spec_ref = self._normalize_repo_path(spec_ref, repo_root)
        normalized_doc_refs = [self._normalize_repo_path(path, repo_root) for path in list(required_doc_refs or [])]
        normalized_artifacts = [self._normalize_repo_path(path, repo_root) for path in list(required_artifacts or [])]
        normalized_owned_paths = [self._normalize_owned_path(path, repo_root) for path in list(owned_paths or [])]
        project.task_counter += 1
        project.updated_at = utc_now()
        task_id = f"TASK-{project.task_counter:04d}"
        spec_version, spec_hash = self._spec_snapshot(normalized_spec_ref)
        task = Task(
            task_id=task_id,
            title=title,
            spec_ref=normalized_spec_ref or spec_ref,
            summary=summary,
            status=TaskStatus.DRAFT,
            verification_mode=verification_mode,
            test_commands=list(test_commands or []),
            required_doc_refs=[path or "" for path in normalized_doc_refs],
            required_artifacts=[path or "" for path in normalized_artifacts],
            owned_paths=[path or "" for path in normalized_owned_paths],
            plan_node_id=plan_node_id or task_id.lower(),
            spec_version=spec_version,
            spec_hash=spec_hash,
            parent_task_id=parent_task_id,
            source_task_id=source_task_id,
            source_finding_id=source_finding_id,
        )
        self.projects.save(project)
        self.tasks.save(task)
        self._emit(task_id, "task_created", task.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "events_written": 1, "errors": []}

    def activate_task(self, task_id: str, repo_root: str | Path | None = None) -> dict[str, Any]:
        self._require_project()
        task = normalize_task(self.tasks.load(task_id))
        self.tasks.save(task)
        session = self._session_payload()
        resolved_repo = self._resolve_repo_root(repo_root, project=self._require_project(), data_root=self.data_root)
        branch = self._git_current_branch(resolved_repo)
        session["active_task_id"] = task.task_id
        if branch:
            branch_map = dict(session.get("active_tasks_by_branch", {}))
            branch_map[branch] = task.task_id
            session["active_tasks_by_branch"] = branch_map
        session["last_repo_root"] = str(resolved_repo) if resolved_repo else session.get("last_repo_root")
        session["updated_at"] = utc_now()
        self.states.save_session(session)
        self._emit(task.task_id, "active_task_changed", {"active_task_id": task.task_id, "branch": branch})
        return {"ok": True, "active_task": self._task_payload(task), "session": session, "errors": []}

    def get_active_task(self, repo_root: str | Path | None = None) -> dict[str, Any]:
        self._require_project()
        session = self._session_payload()
        task = self._current_active_task(repo_root=repo_root)
        return {"ok": True, "active_task": self._task_payload(task) if task else None, "session": session, "errors": []}

    def clear_active_task(self, repo_root: str | Path | None = None) -> dict[str, Any]:
        project = self._require_project()
        session = self._session_payload()
        resolved_repo = self._resolve_repo_root(repo_root, project=project, data_root=self.data_root)
        branch = self._git_current_branch(resolved_repo)
        previous_task = self._current_active_task(repo_root=repo_root)
        if branch:
            branch_map = dict(session.get("active_tasks_by_branch", {}))
            removed_task_id = branch_map.pop(branch, None)
            session["active_tasks_by_branch"] = branch_map
            if removed_task_id and session.get("active_task_id") == removed_task_id:
                session["active_task_id"] = None
        else:
            session["active_task_id"] = None
        session["updated_at"] = utc_now()
        self.states.save_session(session)
        self._emit(previous_task.task_id if previous_task else "project", "active_task_cleared", {"previous_task_id": previous_task.task_id if previous_task else None, "branch": branch})
        return {"ok": True, "active_task": None, "session": session, "errors": []}

    def get_supervision(self, repo_root: str | Path | None = None) -> dict[str, Any]:
        project = self._require_project()
        repo = self._resolve_repo_root(repo_root, project=project, data_root=self.data_root) or Path.cwd()
        changed_files = self._git_changed_files(repo)
        active_task = self._current_active_task(repo_root=repo)
        covered_files, uncovered_files = self._classify_changed_files(changed_files, active_task)
        if active_task is not None and active_task.needs_revalidation:
            status = "needs_revalidation"
        elif not changed_files:
            if (
                active_task is not None
                and active_task.verification_status == VerificationStatus.PASSED
                and active_task.doc_sync_status != DocSyncStatus.SYNCED
            ):
                status = "stale_docs"
            else:
                status = "clean"
        elif active_task is None:
            status = "needs_task"
        elif uncovered_files:
            status = "task_mismatch"
        elif active_task.verification_status != VerificationStatus.PASSED:
            status = "stale_verification"
        elif active_task.doc_sync_status != DocSyncStatus.SYNCED:
            status = "stale_docs"
        else:
            status = "clean"
            if changed_files:
                status = "tracked"
        policy = self._supervision_policy(status)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "repo_root": str(repo),
            "status": status,
            "changed_files": changed_files,
            "covered_files": covered_files,
            "uncovered_files": uncovered_files,
            "active_task_id": active_task.task_id if active_task else None,
            "active_task": self._task_payload(active_task) if active_task else None,
            "advisory_summary": self._advisory_summary(active_task.task_id) if active_task else {
                "open_advisories": 0,
                "high_severity_advisories": 0,
                "pending_reviews": 0,
                "last_reviewed_at": None,
                "last_review_recommendation": None,
            },
            "policy": policy,
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
        return {"ok": True, "tasks": [self._task_payload(task) for task in tasks], "errors": []}

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
        if target == TaskStatus.AWAITING_VERIFICATION:
            self._ensure_advisory_review_request(task, ReviewCheckpoint.SUBMIT)
        elif target == TaskStatus.DONE:
            self._ensure_advisory_review_request(task, ReviewCheckpoint.PRE_DONE)
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "events_written": 1, "errors": [], "warnings": warnings}

    def record_verification(self, task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        status = VerificationStatus(result)
        task = apply_verification(task, status, ref=ref)
        record = VerificationRecord(task_id=task_id, result=status, recorded_at=utc_now(), ref=ref, notes=notes)
        self.tasks.save(task)
        self._emit(task.task_id, "verification_recorded", record.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "record": record.to_dict(), "events_written": 1, "errors": []}

    def record_doc_sync(self, task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        status = DocSyncStatus(result)
        task = apply_doc_sync(task, status, ref=ref)
        record = DocSyncRecord(task_id=task_id, result=status, recorded_at=utc_now(), ref=ref, notes=notes)
        self.tasks.save(task)
        self._emit(task.task_id, "doc_sync_recorded", record.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "record": record.to_dict(), "events_written": 1, "errors": []}

    def update_acceptance_protocol(self, task_id: str, verification_mode: str | None = None, test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, owned_paths: list[str] | None = None, plan_node_id: str | None = None) -> dict[str, Any]:
        project = self._require_project()
        task = self.tasks.load(task_id)
        repo_root = self._resolve_repo_root(None, project=project, data_root=self.data_root)
        if verification_mode is not None:
            task.verification_mode = verification_mode
        if test_commands is not None:
            task.test_commands = list(test_commands)
        if required_doc_refs is not None:
            task.required_doc_refs = [self._normalize_repo_path(path, repo_root) or "" for path in list(required_doc_refs)]
        if required_artifacts is not None:
            task.required_artifacts = [self._normalize_repo_path(path, repo_root) or "" for path in list(required_artifacts)]
        if owned_paths is not None:
            task.owned_paths = [self._normalize_owned_path(path, repo_root) or "" for path in list(owned_paths)]
        if plan_node_id is not None:
            task.plan_node_id = plan_node_id
        task.updated_at = utc_now()
        self.tasks.save(task)
        self._emit(task.task_id, "acceptance_protocol_updated", task.to_dict())
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "events_written": 1, "errors": []}

    def record_task_review(
        self,
        task_id: str,
        checkpoint: str,
        provider_id: str = "manual",
        summary: str = "",
        overall_recommendation: str = ReviewRecommendation.PROCEED.value,
        findings: list[dict[str, Any]] | None = None,
        review_run_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        checkpoint_enum = self._normalize_checkpoint(checkpoint)
        provider = get_review_provider(provider_id)
        normalized = provider.normalize_input(task, checkpoint_enum, summary, overall_recommendation, findings)
        recommendation = self._normalize_recommendation(normalized.overall_recommendation)

        if review_run_id is not None:
            review_run = self.review_runs.load(review_run_id)
            if review_run.task_id != task_id:
                raise ValidationError(f"{review_run_id} does not belong to {task_id}")
        else:
            pending = [
                run
                for run in self._list_review_runs(task_id=task_id, checkpoint=checkpoint_enum, status=ReviewRunStatus.REQUESTED)
            ]
            same_provider_pending = [run for run in pending if run.provider_id == provider.provider_id]
            review_run = (same_provider_pending or pending)[-1] if pending else ReviewRun(
                review_run_id=self._review_run_id(),
                task_id=task_id,
                checkpoint=checkpoint_enum,
                provider_id=provider.provider_id,
                status=ReviewRunStatus.REQUESTED,
                source_task_updated_at=task.updated_at,
                request_hint=provider.build_request_hint(task, checkpoint_enum),
            )

        review_run.provider_id = provider.provider_id
        review_run.status = ReviewRunStatus.COMPLETED
        review_run.summary = normalized.summary
        review_run.overall_recommendation = recommendation
        review_run.updated_at = utc_now()

        finding_ids: list[str] = []
        serialized_findings: list[dict[str, Any]] = []
        for finding_payload in normalized.findings:
            severity = self._normalize_finding_severity(self._required_finding_field(finding_payload, "severity"))
            finding = ReviewFinding(
                finding_id=self._review_finding_id(),
                review_run_id=review_run.review_run_id,
                task_id=task_id,
                checkpoint=checkpoint_enum,
                provider_id=provider.provider_id,
                dimension=self._required_finding_field(finding_payload, "dimension"),
                severity=severity,
                title=self._required_finding_field(finding_payload, "title"),
                details=self._required_finding_field(finding_payload, "details"),
                recommended_action=finding_payload.get("recommended_action"),
                suggested_task_title=finding_payload.get("suggested_task_title"),
                suggested_task_summary=finding_payload.get("suggested_task_summary"),
                suggested_owned_paths=list(finding_payload.get("suggested_owned_paths") or []),
            )
            self.review_findings.save(finding)
            finding_ids.append(finding.finding_id)
            serialized_findings.append(finding.to_dict())

        review_run.finding_ids = finding_ids
        self.review_runs.save(review_run)
        self._emit(
            task_id,
            "advisory_review_recorded",
            {
                "review_run_id": review_run.review_run_id,
                "checkpoint": checkpoint_enum.value,
                "provider_id": provider.provider_id,
                "finding_ids": finding_ids,
                "overall_recommendation": recommendation.value,
            },
        )
        self._sync_state_files()
        return {
            "ok": True,
            "review": self._review_run_payload(review_run),
            "findings": serialized_findings,
            "task": self._task_payload(task),
            "errors": [],
        }

    def list_reviews(
        self,
        task_id: str | None = None,
        checkpoint: str | None = None,
        status: str | None = None,
        include_findings: bool = False,
    ) -> dict[str, Any]:
        self._require_project()
        checkpoint_enum = self._normalize_checkpoint(checkpoint) if checkpoint else None
        status_enum = self._normalize_review_run_status(status) if status else None
        runs = self._list_review_runs(task_id=task_id, checkpoint=checkpoint_enum, status=status_enum)
        findings = self._list_review_findings(task_id=task_id)
        payload: dict[str, Any] = {
            "ok": True,
            "reviews": [self._review_run_payload(run, include_findings=include_findings) for run in runs],
            "errors": [],
        }
        if include_findings:
            payload["findings"] = [self._finding_payload(finding) for finding in findings]
        return payload

    def set_review_finding_disposition(
        self,
        finding_id: str,
        disposition: str,
        notes: str | None = None,
        followup_task_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        finding = self.review_findings.load(finding_id)
        finding.disposition = self._normalize_finding_disposition(disposition)
        finding.notes = notes
        if followup_task_id is not None:
            finding.followup_task_id = followup_task_id
        finding.updated_at = utc_now()
        self.review_findings.save(finding)
        self._emit(
            finding.task_id,
            "advisory_finding_disposition_changed",
            {
                "finding_id": finding.finding_id,
                "disposition": finding.disposition.value,
                "followup_task_id": finding.followup_task_id,
            },
        )
        self._sync_state_files()
        return {"ok": True, "finding": self._finding_payload(finding), "errors": []}

    def create_followup_task_from_finding(
        self,
        finding_id: str,
        title: str | None = None,
        summary: str | None = None,
        plan_node_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        finding = self.review_findings.load(finding_id)
        source_task = self.tasks.load(finding.task_id)
        followup = self.create_task(
            title=title or finding.suggested_task_title or f"Follow up: {finding.title}",
            spec_ref=source_task.spec_ref,
            summary=summary or finding.suggested_task_summary or finding.details,
            verification_mode=source_task.verification_mode,
            test_commands=list(source_task.test_commands),
            required_doc_refs=list(source_task.required_doc_refs),
            required_artifacts=list(source_task.required_artifacts),
            owned_paths=list(finding.suggested_owned_paths or source_task.owned_paths),
            plan_node_id=plan_node_id or f"{source_task.plan_node_id or source_task.task_id.lower()}-followup",
            parent_task_id=source_task.task_id,
            source_task_id=source_task.task_id,
            source_finding_id=finding.finding_id,
        )
        finding.disposition = ReviewFindingDisposition.SPAWNED_FOLLOWUP
        finding.followup_task_id = followup["task"]["task_id"]
        finding.updated_at = utc_now()
        self.review_findings.save(finding)
        self._emit(
            source_task.task_id,
            "advisory_followup_task_created",
            {
                "finding_id": finding.finding_id,
                "followup_task_id": followup["task"]["task_id"],
            },
        )
        self._sync_state_files()
        return {"ok": True, "task": followup["task"], "finding": self._finding_payload(finding), "errors": []}

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
        project = self._require_project()
        repo_root = self._resolve_repo_root(None, project=project, data_root=self.data_root)
        normalized_spec_ref = self._normalize_repo_path(spec_ref, repo_root) or spec_ref
        spec_version, spec_hash = self._spec_snapshot(normalized_spec_ref)
        if spec_hash is None:
            raise ValidationError(f"spec not found: {normalized_spec_ref}")
        changed: list[str] = []
        for task in self.tasks.list():
            if task.spec_ref != normalized_spec_ref:
                continue
            if task.spec_hash != spec_hash:
                self._mark_spec_drift(task, reason or "spec hash changed")
                task.spec_version = spec_version
                task.spec_hash = spec_hash
                self.tasks.save(task)
                self._emit(task.task_id, "spec_drift_detected", {"spec_ref": normalized_spec_ref, "spec_hash": spec_hash, "reason": task.stale_reason})
                changed.append(task.task_id)
        self._sync_state_files()
        return {"ok": True, "spec_ref": normalized_spec_ref, "spec_version": spec_version, "spec_hash": spec_hash, "changed_tasks": changed, "errors": []}

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

    def reopen_task(self, task_id: str, target_status: str = TaskStatus.IN_PROGRESS.value) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        if task.status != TaskStatus.DONE:
            raise ValidationError(f"{task_id} is not done")
        target = TaskStatus(target_status)
        if target not in {TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_VERIFICATION}:
            raise ValidationError("reopen target must be one of: ready, in_progress, awaiting_verification")
        task = apply_transition(task, target)
        self.tasks.save(task)
        self._emit(task.task_id, "task_reopened", {"target_status": target.value, "resulting_status": task.status.value})
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "events_written": 1, "errors": []}

    def unblock_task(self, task_id: str, target_status: str) -> dict[str, Any]:
        self._require_project()
        task = self.tasks.load(task_id)
        if task.status != TaskStatus.BLOCKED:
            raise ValidationError(f"{task_id} is not blocked")
        task.blocked_reason = None
        task = normalize_task(task)
        task = apply_transition(task, TaskStatus(target_status))
        self.tasks.save(task)
        self._emit(task.task_id, "task_unblocked", {"target_status": task.status.value})
        self._sync_state_files()
        return {"ok": True, "task": self._task_payload(task), "events_written": 1, "errors": []}

    def dashboard(self, include_tasks: bool = False, limit: int = 10) -> dict[str, Any]:
        project = self._require_project()
        tasks = self._load_tasks(normalize=True, persist=True)
        advisory_summaries = {task.task_id: self._advisory_summary(task.task_id) for task in tasks}
        summary = build_dashboard(project.project_name, tasks, advisory_summaries=advisory_summaries, limit=limit)
        payload: dict[str, Any] = {"ok": True, "dashboard": summary.to_dict(), "errors": []}
        if include_tasks:
            payload["tasks"] = [self._task_payload(task) for task in tasks[:limit]]
        return payload
