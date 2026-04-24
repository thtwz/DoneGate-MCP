from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    hooks = repo / ".git" / "hooks"
    custom_hook = hooks / "pre-commit"
    custom_hook.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")

    service = DoneGateService(repo / ".donegate-mcp")
    bootstrapped = service.bootstrap_repository("demo", repo_root=repo)

    assert bootstrapped["project"]["project_name"] == "demo"
    assert bootstrapped["hooks"]["installed"] == ["pre-push"]
    assert bootstrapped["hooks"]["skipped"] == ["pre-commit"]
    assert custom_hook.read_text(encoding="utf-8") == "#!/bin/sh\necho custom\n"
    assert (hooks / "pre-push").exists()


def test_bootstrap_repository_supports_git_worktree_and_generates_onboarding_assets(tmp_path) -> None:
    main_repo = tmp_path / "main-repo"
    worktree_repo = tmp_path / "feature-repo"
    main_repo.mkdir()
    subprocess.run(["git", "init"], cwd=main_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=main_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=main_repo, check=True, capture_output=True, text=True)
    (main_repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=main_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=main_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "worktree", "add", "-b", "feature/demo", str(worktree_repo)], cwd=main_repo, check=True, capture_output=True, text=True)

    service = DoneGateService(worktree_repo / ".donegate-mcp")
    bootstrapped = service.bootstrap_repository("demo", repo_root=worktree_repo)
    hooks_dir = Path(
        subprocess.run(
            ["git", "-C", str(worktree_repo), "rev-parse", "--git-path", "hooks"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    assert bootstrapped["hooks"]["installed"] == ["pre-commit", "pre-push"]
    assert (hooks_dir / "pre-commit").exists()
    assert (hooks_dir / "pre-push").exists()
    assert (worktree_repo / ".donegate-mcp" / "env.sh").exists()
    assert (worktree_repo / ".donegate-mcp" / "onboarding" / "codex.md").exists()
    assert (worktree_repo / ".donegate-mcp" / "onboarding" / "hermes-mcp.yaml").exists()


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
    assert covered["supervision"]["status"] == "stale_verification"
    assert covered["supervision"]["active_task"]["task_id"] == task_id


def test_branch_scoped_active_task_prefers_current_branch(tmp_path) -> None:
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
    service.init_project("demo", repo_root=str(repo))
    task_main = service.create_task("main task", "docs/spec-main.md")["task"]["task_id"]
    service.activate_task(task_main, repo_root=repo)

    subprocess.run(["git", "checkout", "-b", "feature/demo"], cwd=repo, check=True, capture_output=True, text=True)
    task_feature = service.create_task("feature task", "docs/spec-feature.md")["task"]["task_id"]
    service.activate_task(task_feature, repo_root=repo)

    feature_active = service.get_active_task(repo_root=repo)
    assert feature_active["active_task"]["task_id"] == task_feature

    subprocess.run(["git", "checkout", "-"], cwd=repo, check=True, capture_output=True, text=True)
    main_active = service.get_active_task(repo_root=repo)
    assert main_active["active_task"]["task_id"] == task_main


def test_repo_root_relative_paths_are_normalized_for_task_creation(tmp_path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    reports = repo / "reports"
    docs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (docs / "spec.md").write_text("v1\n", encoding="utf-8")
    (docs / "plan.md").write_text("ok\n", encoding="utf-8")
    (reports / "pytest.txt").write_text("ok\n", encoding="utf-8")

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo", repo_root=str(repo))
    created = service.create_task(
        "Gate task",
        "docs/spec.md",
        required_doc_refs=["docs/plan.md"],
        required_artifacts=["reports/pytest.txt"],
    )

    task = created["task"]
    assert task["spec_ref"] == str((repo / "docs" / "spec.md").resolve())
    assert task["required_doc_refs"] == [str((repo / "docs" / "plan.md").resolve())]
    assert task["required_artifacts"] == [str((repo / "reports" / "pytest.txt").resolve())]


def test_task_scope_normalizes_to_repo_relative_owned_paths(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "donegate_mcp").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo", repo_root=str(repo))
    created = service.create_task(
        "Scoped task",
        "docs/spec.md",
        owned_paths=["./src/donegate_mcp", str((repo / "tests").resolve())],
    )

    assert created["task"]["owned_paths"] == ["src/donegate_mcp", "tests"]


def test_supervision_reports_task_mismatch_for_uncovered_changed_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = repo / "src"
    tests_dir = repo / "tests"
    repo.mkdir()
    src.mkdir()
    tests_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    (src / "tracked.py").write_text("print('v1')\n", encoding="utf-8")
    (tests_dir / "test_tracked.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/tracked.py", "tests/test_tracked.py"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo", repo_root=str(repo))
    created = service.create_task("Scoped task", "docs/spec.md", owned_paths=["src"])
    task_id = created["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)

    (src / "tracked.py").write_text("print('v2')\n", encoding="utf-8")
    (tests_dir / "test_tracked.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")

    reported = service.get_supervision(repo_root=repo)

    assert reported["supervision"]["status"] == "task_mismatch"
    assert reported["supervision"]["covered_files"] == ["src/tracked.py"]
    assert reported["supervision"]["uncovered_files"] == ["tests/test_tracked.py"]
    assert reported["supervision"]["active_task"]["owned_paths"] == ["src"]


def test_supervision_reports_needs_revalidation_for_active_task_with_spec_drift(tmp_path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    repo.mkdir()
    docs.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    spec = docs / "spec.md"
    spec.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/spec.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo", repo_root=str(repo))
    task_id = service.create_task("Scoped task", "docs/spec.md")["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)

    spec.write_text("v2\n", encoding="utf-8")
    service.refresh_spec("docs/spec.md", reason="spec updated")

    reported = service.get_supervision(repo_root=repo)

    assert reported["supervision"]["status"] == "needs_revalidation"
    assert reported["supervision"]["policy"]["pre_commit"]["action"] == "block"
    assert reported["supervision"]["policy"]["pre_push"]["action"] == "block"


def test_supervision_reports_stale_verification_for_covered_changed_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    src = repo / "src"
    repo.mkdir()
    src.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    tracked = src / "tracked.py"
    tracked.write_text("print('v1')\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/tracked.py"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.init_project("demo", repo_root=str(repo))
    task_id = service.create_task("Scoped task", "docs/spec.md", owned_paths=["src"])["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)

    tracked.write_text("print('v2')\n", encoding="utf-8")

    reported = service.get_supervision(repo_root=repo)

    assert reported["supervision"]["status"] == "stale_verification"
    assert reported["supervision"]["policy"]["pre_commit"]["action"] == "warn"
    assert reported["supervision"]["policy"]["pre_push"]["action"] == "block"


def test_supervision_reports_stale_docs_for_verified_active_task(tmp_path) -> None:
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
    service.init_project("demo", repo_root=str(repo))
    task_id = service.create_task("Scoped task", "docs/spec.md")["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)
    service.record_verification(task_id, "passed", ref="reports/pytest.txt")

    reported = service.get_supervision(repo_root=repo)

    assert reported["supervision"]["status"] == "stale_docs"
    assert reported["supervision"]["policy"]["pre_commit"]["action"] == "warn"
    assert reported["supervision"]["policy"]["pre_push"]["action"] == "block"


def test_onboarding_reports_branch_active_task_and_repo_assets(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    service = DoneGateService(repo / ".donegate-mcp")
    service.bootstrap_repository("demo", repo_root=repo)
    task_id = service.create_task("Gate task", "docs/spec.md")["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)

    payload = service.get_onboarding(agent="codex", repo_root=repo)

    assert payload["onboarding"]["branch"] == "master" or payload["onboarding"]["branch"] == "main"
    assert payload["onboarding"]["active_task"]["task_id"] == task_id
    assert payload["onboarding"]["files"]["env"] == str((repo / ".donegate-mcp" / "env.sh").resolve())
    assert payload["onboarding"]["files"]["codex"] == str((repo / ".donegate-mcp" / "onboarding" / "codex.md").resolve())
    assert "task active --repo-root" in payload["onboarding"]["recommended_next_step"]


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


def test_list_tasks_projects_stale_legacy_status_without_repersisting_status(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Stale task", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload.pop("workflow_intent", None)
    payload["status"] = "awaiting_verification"
    payload["verification_status"] = "passed"
    payload["doc_sync_status"] = "synced"
    payload["started_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    listed = service.list_tasks()
    assert listed["tasks"][0]["status"] == "documented"

    reloaded = json.loads(task_file.read_text(encoding="utf-8"))
    assert "status" not in reloaded
    assert reloaded["workflow_intent"] == "awaiting_verification"


def test_dashboard_is_fact_driven_even_when_task_file_is_stale(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Needs docs", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload.pop("workflow_intent", None)
    payload["status"] = "awaiting_verification"
    payload["verification_status"] = "passed"
    payload["started_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    dashboard = service.dashboard()
    assert dashboard["dashboard"]["missing_verification"] == []
    assert [task["task_id"] for task in dashboard["dashboard"]["missing_docs"]] == [task_id]
    assert dashboard["dashboard"]["counts_by_status"]["verified"] == 1
