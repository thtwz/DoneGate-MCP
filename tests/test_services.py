from __future__ import annotations

import json
import subprocess

from donegate_mcp.domain.services import DoneGateService


def test_init_and_create_task_persists_files(tmp_path) -> None:
    service = DoneGateService(tmp_path / ".donegate-mcp")
    init_payload = service.init_project("demo")
    assert init_payload["ok"] is True

    create_payload = service.create_task("Gate task", "docs/spec.md", summary="summary")
    assert create_payload["task"]["task_id"] == "TASK-0001"

    task_file = tmp_path / ".donegate-mcp" / "tasks" / "TASK-0001.json"
    event_file = tmp_path / ".donegate-mcp" / "events" / "TASK-0001.jsonl"
    plan_file = tmp_path / ".donegate-mcp" / "plan.json"
    progress_file = tmp_path / ".donegate-mcp" / "progress.json"
    assert task_file.exists()
    assert event_file.exists()
    assert plan_file.exists()
    assert progress_file.exists()


def test_bootstrap_repository_initializes_state_and_skips_unmanaged_hooks(tmp_path) -> None:
    repo = tmp_path / "repo"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True)
    custom_hook = hooks / "pre-commit"
    custom_hook.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")

    service = DoneGateService(repo / ".donegate-mcp")
    bootstrapped = service.bootstrap_repository("demo", repo_root=repo)

    assert bootstrapped["project"]["project_name"] == "demo"
    assert bootstrapped["hooks"]["installed"] == ["pre-push"]
    assert bootstrapped["hooks"]["skipped"] == ["pre-commit"]
    assert custom_hook.read_text(encoding="utf-8") == "#!/bin/sh\necho custom\n"
    assert (hooks / "pre-push").exists()


def test_active_task_context_round_trip(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md")
    task_id = created["task"]["task_id"]

    activated = service.activate_task(task_id)
    assert activated["active_task"]["task_id"] == task_id

    current = service.get_active_task()
    assert current["active_task"]["task_id"] == task_id

    cleared = service.clear_active_task()
    assert cleared["active_task"] is None
    assert service.get_active_task()["active_task"] is None


def test_supervision_reports_untracked_work_and_active_task_coverage(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo")

    clean = service.get_supervision(repo_root=repo)
    assert clean["supervision"]["status"] == "clean"
    assert clean["supervision"]["changed_files"] == []

    tracked.write_text("v2\n", encoding="utf-8")
    needs_task = service.get_supervision(repo_root=repo)
    assert needs_task["supervision"]["status"] == "needs_task"
    assert needs_task["supervision"]["changed_files"] == ["tracked.txt"]

    created = service.create_task("Gate task", "docs/spec.md")
    task_id = created["task"]["task_id"]
    service.activate_task(task_id)
    covered = service.get_supervision(repo_root=repo)
    assert covered["supervision"]["status"] == "tracked"
    assert covered["supervision"]["active_task"]["task_id"] == task_id


def test_service_gate_flow(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    docs = tmp_path / "docs"
    reports = tmp_path / "reports"
    docs.mkdir()
    reports.mkdir()
    (docs / "plan.md").write_text("ok", encoding="utf-8")
    (reports / "pytest.txt").write_text("ok", encoding="utf-8")
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md", required_doc_refs=[str(docs / 'plan.md')], required_artifacts=[str(reports / 'pytest.txt')])
    task_id = created["task"]["task_id"]

    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    service.record_verification(task_id, "passed", ref=str(reports / 'pytest.txt'))
    service.record_doc_sync(task_id, "synced", ref=str(docs / 'plan.md'))
    closed = service.transition_task(task_id, "done")

    assert closed["task"]["status"] == "done"
    assert closed["task"]["last_verification_ref"] == str(reports / 'pytest.txt')
    assert closed["task"]["last_doc_sync_ref"] == str(docs / 'plan.md')


def test_service_gate_flow_is_order_independent_for_verification_and_doc_sync(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    docs = tmp_path / "docs"
    reports = tmp_path / "reports"
    docs.mkdir()
    reports.mkdir()
    (docs / "plan.md").write_text("ok", encoding="utf-8")
    (reports / "pytest.txt").write_text("ok", encoding="utf-8")
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md", required_doc_refs=[str(docs / 'plan.md')], required_artifacts=[str(reports / 'pytest.txt')])
    task_id = created["task"]["task_id"]

    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    service.record_doc_sync(task_id, "synced", ref=str(docs / 'plan.md'))
    verified = service.record_verification(task_id, "passed", ref=str(reports / 'pytest.txt'))

    assert verified["task"]["status"] == "documented"
    closed = service.transition_task(task_id, "done")
    assert closed["task"]["status"] == "done"


def test_transition_to_verified_returns_compatibility_warning(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Compat transition", "docs/spec.md")
    task_id = created["task"]["task_id"]

    service.transition_task(task_id, "ready")
    service.record_verification(task_id, "passed")
    transitioned = service.transition_task(task_id, "verified")

    assert transitioned["task"]["status"] == "verified"
    assert transitioned["task"]["projected_status"] == "verified"
    assert transitioned["task"]["status_source"] == "projected"
    assert transitioned["warnings"] == [
        "target_status=verified is a compatibility alias; prefer intent commands plus fact recording"
    ]


def test_verification_fact_marks_ready_task_as_started_and_promotes_status(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Implicit start", "docs/spec.md")
    task_id = created["task"]["task_id"]

    service.transition_task(task_id, "ready")
    verified = service.record_verification(task_id, "passed", ref="reports/pytest.txt")

    assert verified["task"]["started_at"] is not None
    assert verified["task"]["status"] == "verified"


def test_list_tasks_normalizes_stale_persisted_status(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Stale task", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload["status"] = "awaiting_verification"
    payload["verification_status"] = "passed"
    payload["doc_sync_status"] = "synced"
    payload["started_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    listed = service.list_tasks()
    assert listed["tasks"][0]["status"] == "documented"

    reloaded = json.loads(task_file.read_text(encoding="utf-8"))
    assert reloaded["status"] == "documented"


def test_dashboard_is_fact_driven_even_when_task_file_is_stale(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Needs docs", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload["status"] = "awaiting_verification"
    payload["verification_status"] = "passed"
    payload["started_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    dashboard = service.dashboard()
    assert dashboard["dashboard"]["missing_verification"] == []
    assert [task["task_id"] for task in dashboard["dashboard"]["missing_docs"]] == [task_id]
    assert dashboard["dashboard"]["counts_by_status"]["verified"] == 1
