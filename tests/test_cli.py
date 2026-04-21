from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(tmp_path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "donegate_mcp.cli.main", "--data-root", str(tmp_path / ".donegate-mcp"), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_done_returns_gate_violation_exit_code(tmp_path) -> None:
    assert run_cli(tmp_path, "init", "--project-name", "demo").returncode == 0
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    assert run_cli(tmp_path, "task", "done", task_id).returncode == 3


def test_bootstrap_initializes_repo_and_installs_hooks(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    hooks_dir = repo / ".git" / "hooks"

    bootstrapped = subprocess.run(
        [
            sys.executable,
            "-m",
            "donegate_mcp.cli.main",
            "--json",
            "bootstrap",
            "--project-name",
            "demo",
            "--repo-root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(bootstrapped.stdout)
    assert bootstrapped.returncode == 0
    assert payload["ok"] is True
    assert payload["project"]["project_name"] == "demo"
    assert payload["hooks"]["installed"] == ["pre-commit", "pre-push"]
    assert (repo / ".donegate-mcp" / "project.json").exists()
    assert (hooks_dir / "pre-commit").exists()
    assert (hooks_dir / "pre-push").exists()


def test_bootstrap_generates_onboarding_assets_and_cli_reports_guidance(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    bootstrapped = subprocess.run(
        [
            sys.executable,
            "-m",
            "donegate_mcp.cli.main",
            "--json",
            "bootstrap",
            "--project-name",
            "demo",
            "--repo-root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(bootstrapped.stdout)
    assert payload["onboarding"]["files"]["env"] == str((repo / ".donegate-mcp" / "env.sh").resolve())
    assert (repo / ".donegate-mcp" / "onboarding" / "codex.md").exists()
    assert (repo / ".donegate-mcp" / "onboarding" / "hermes-mcp.yaml").exists()

    created = json.loads(run_cli(repo, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md").stdout)
    run_cli(repo, "--json", "task", "activate", created["task"]["task_id"], "--repo-root", str(repo))
    onboarding = json.loads(run_cli(repo, "--json", "onboarding", "--repo-root", str(repo), "--agent", "codex").stdout)

    assert onboarding["onboarding"]["agent"] == "codex"
    assert onboarding["onboarding"]["active_task"]["task_id"] == created["task"]["task_id"]
    assert "task active --repo-root" in onboarding["onboarding"]["recommended_next_step"]


def test_cli_active_task_commands_round_trip(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]

    activated = json.loads(run_cli(tmp_path, "--json", "task", "activate", task_id).stdout)
    assert activated["active_task"]["task_id"] == task_id

    current = json.loads(run_cli(tmp_path, "--json", "task", "active").stdout)
    assert current["active_task"]["task_id"] == task_id

    cleared = json.loads(run_cli(tmp_path, "--json", "task", "clear-active").stdout)
    assert cleared["active_task"] is None


def test_cli_supervision_reports_dirty_repo_without_active_task(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    run_cli(repo, "init", "--project-name", "demo")
    tracked.write_text("v2\n", encoding="utf-8")

    reported = run_cli(
        repo,
        "--json",
        "supervision",
        "--repo-root",
        str(repo),
    )
    payload = json.loads(reported.stdout)

    assert payload["supervision"]["status"] == "needs_task"
    assert payload["supervision"]["changed_files"] == ["tracked.txt"]


def test_cli_branch_scoped_active_task_prefers_current_branch(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    run_cli(repo, "init", "--project-name", "demo", "--repo-root", str(repo))
    main_task = json.loads(run_cli(repo, "--json", "task", "create", "--title", "main", "--spec-ref", "docs/spec-main.md").stdout)["task"]["task_id"]
    run_cli(repo, "--json", "task", "activate", main_task, "--repo-root", str(repo))

    subprocess.run(["git", "checkout", "-b", "feature/demo"], cwd=repo, check=True, capture_output=True, text=True)
    feature_task = json.loads(run_cli(repo, "--json", "task", "create", "--title", "feature", "--spec-ref", "docs/spec-feature.md").stdout)["task"]["task_id"]
    run_cli(repo, "--json", "task", "activate", feature_task, "--repo-root", str(repo))

    feature_active = json.loads(run_cli(repo, "--json", "task", "active", "--repo-root", str(repo)).stdout)
    assert feature_active["active_task"]["task_id"] == feature_task

    subprocess.run(["git", "checkout", "-"], cwd=repo, check=True, capture_output=True, text=True)
    main_active = json.loads(run_cli(repo, "--json", "task", "active", "--repo-root", str(repo)).stdout)
    assert main_active["active_task"]["task_id"] == main_task


def test_cli_repo_root_relative_task_refs_are_normalized(tmp_path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    reports = repo / "reports"
    docs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (docs / "spec.md").write_text("v1\n", encoding="utf-8")
    (docs / "plan.md").write_text("ok\n", encoding="utf-8")
    (reports / "pytest.txt").write_text("ok\n", encoding="utf-8")

    run_cli(repo, "init", "--project-name", "demo", "--repo-root", str(repo))
    created = json.loads(
        run_cli(
            repo,
            "--json",
            "task",
            "create",
            "--title",
            "t",
            "--spec-ref",
            "docs/spec.md",
            "--required-doc-ref",
            "docs/plan.md",
            "--required-artifact",
            "reports/pytest.txt",
        ).stdout
    )
    task = created["task"]

    assert task["spec_ref"] == str((repo / "docs" / "spec.md").resolve())
    assert task["required_doc_refs"] == [str((repo / "docs" / "plan.md").resolve())]
    assert task["required_artifacts"] == [str((repo / "reports" / "pytest.txt").resolve())]


def test_cli_owned_path_scope_is_normalized_for_task_creation(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "donegate_mcp").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    run_cli(repo, "init", "--project-name", "demo", "--repo-root", str(repo))
    created = json.loads(
        run_cli(
            repo,
            "--json",
            "task",
            "create",
            "--title",
            "scoped",
            "--spec-ref",
            "docs/spec.md",
            "--owned-path",
            "./src/donegate_mcp",
            "--owned-path",
            str((repo / "tests").resolve()),
        ).stdout
    )

    assert created["task"]["owned_paths"] == ["src/donegate_mcp", "tests"]


def test_cli_supervision_reports_task_mismatch_for_uncovered_owned_path_scope(tmp_path) -> None:
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

    run_cli(repo, "init", "--project-name", "demo", "--repo-root", str(repo))
    task_id = json.loads(
        run_cli(
            repo,
            "--json",
            "task",
            "create",
            "--title",
            "scoped",
            "--spec-ref",
            "docs/spec.md",
            "--owned-path",
            "src",
        ).stdout
    )["task"]["task_id"]
    run_cli(repo, "--json", "task", "activate", task_id, "--repo-root", str(repo))

    (src / "tracked.py").write_text("print('v2')\n", encoding="utf-8")
    (tests_dir / "test_tracked.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")

    payload = json.loads(run_cli(repo, "--json", "supervision", "--repo-root", str(repo)).stdout)

    assert payload["supervision"]["status"] == "task_mismatch"
    assert payload["supervision"]["covered_files"] == ["src/tracked.py"]
    assert payload["supervision"]["uncovered_files"] == ["tests/test_tracked.py"]
    assert payload["supervision"]["active_task"]["owned_paths"] == ["src"]


def test_json_dashboard_output(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    out = run_cli(tmp_path, "--json", "dashboard")
    payload = json.loads(out.stdout)
    assert payload["ok"] is True
    assert payload["dashboard"]["project_name"] == "demo"


def test_cli_self_test_command(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md", "--verification-mode", "self-test", "--test-command", "python3 -c 'print(1)'", "--plan-node-id", "node-1")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "start", task_id)
    run_cli(tmp_path, "task", "submit", task_id)
    tested = run_cli(tmp_path, "--json", "task", "self-test", task_id, "--workdir", str(tmp_path))
    payload = json.loads(tested.stdout)
    assert payload["task"]["verification_status"] == "passed"
    assert payload["exit_code"] == 0


def test_cli_plan_progress_and_spec_drift(tmp_path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("v1", encoding="utf-8")
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", str(spec), "--plan-node-id", "node-a")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    spec.write_text("v2", encoding="utf-8")
    refreshed = json.loads(run_cli(tmp_path, "--json", "spec", "refresh", "--spec-ref", str(spec), "--reason", "spec updated").stdout)
    assert task_id in refreshed["changed_tasks"]
    plan = json.loads(run_cli(tmp_path, "--json", "plan").stdout)
    progress = json.loads(run_cli(tmp_path, "--json", "progress").stdout)
    assert plan["plan"]["nodes"][0]["needs_revalidation"] is True
    assert progress["progress"]["stale_tasks"][0]["task_id"] == task_id


def test_cli_deviation_roundtrip(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "deviation", "add", task_id, "--summary", "changed behavior", "--details", "temporary divergence")
    listed = json.loads(run_cli(tmp_path, "--json", "deviation", "list").stdout)
    assert listed["deviations"][0]["task_id"] == task_id


def test_submit_intent_can_move_ready_task_into_awaiting_verification(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    submitted = json.loads(run_cli(tmp_path, "--json", "task", "submit", task_id).stdout)
    assert submitted["task"]["status"] == "awaiting_verification"
    assert submitted["task"]["started_at"] is not None


def test_transition_verified_is_compatibility_alias_for_fact_projected_state(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "verify", task_id, "--result", "passed")
    transitioned = json.loads(run_cli(tmp_path, "--json", "task", "transition", task_id, "--to", "verified").stdout)
    assert transitioned["task"]["status"] == "verified"
    assert transitioned["task"]["projected_status"] == "verified"
    assert transitioned["task"]["status_source"] == "projected"
    assert transitioned["task"]["started_at"] is not None
    assert transitioned["warnings"] == [
        "target_status=verified is a compatibility alias; prefer intent commands plus fact recording"
    ]


def test_done_intent_can_close_ready_task_once_facts_are_satisfied(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    doc = tmp_path / "plan.md"
    artifact = tmp_path / "artifact.txt"
    doc.write_text("ok", encoding="utf-8")
    artifact.write_text("ok", encoding="utf-8")
    created = run_cli(
        tmp_path,
        "--json",
        "task",
        "create",
        "--title",
        "t",
        "--spec-ref",
        "docs/spec.md",
        "--required-doc-ref",
        str(doc),
        "--required-artifact",
        str(artifact),
    )
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "verify", task_id, "--result", "passed", "--ref", str(artifact))
    run_cli(tmp_path, "task", "doc-sync", task_id, "--result", "synced", "--ref", str(doc))
    closed = json.loads(run_cli(tmp_path, "--json", "task", "done", task_id).stdout)
    assert closed["task"]["status"] == "done"


def test_cli_transition_can_reopen_done_task_to_incomplete(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    doc = tmp_path / "plan.md"
    doc.write_text("ok", encoding="utf-8")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", str(doc))
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "verify", task_id, "--result", "passed", "--ref", str(doc))
    run_cli(tmp_path, "task", "doc-sync", task_id, "--result", "synced", "--ref", str(doc))
    run_cli(tmp_path, "task", "done", task_id)

    reopened = run_cli(tmp_path, "--json", "task", "transition", task_id, "--to", "in_progress")

    assert reopened.returncode == 0
    payload = json.loads(reopened.stdout)
    assert payload["task"]["status"] != "done"
    assert payload["task"]["done_at"] is None


def test_cli_transition_can_reopen_done_task_to_ready(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    doc = tmp_path / "plan.md"
    doc.write_text("ok", encoding="utf-8")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", str(doc))
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "verify", task_id, "--result", "passed", "--ref", str(doc))
    run_cli(tmp_path, "task", "doc-sync", task_id, "--result", "synced", "--ref", str(doc))
    run_cli(tmp_path, "task", "done", task_id)

    reopened = run_cli(tmp_path, "--json", "task", "transition", task_id, "--to", "ready")

    assert reopened.returncode == 0
    payload = json.loads(reopened.stdout)
    assert payload["task"]["status"] != "done"
    assert payload["task"]["done_at"] is None


def test_cli_reopen_defaults_done_task_to_in_progress_intent(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    doc = tmp_path / "plan.md"
    doc.write_text("ok", encoding="utf-8")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", str(doc))
    task_id = json.loads(created.stdout)["task"]["task_id"]
    run_cli(tmp_path, "task", "transition", task_id, "--to", "ready")
    run_cli(tmp_path, "task", "verify", task_id, "--result", "passed", "--ref", str(doc))
    run_cli(tmp_path, "task", "doc-sync", task_id, "--result", "synced", "--ref", str(doc))
    run_cli(tmp_path, "task", "done", task_id)

    reopened = run_cli(tmp_path, "--json", "task", "reopen", task_id)

    assert reopened.returncode == 0
    payload = json.loads(reopened.stdout)
    assert payload["task"]["status"] != "done"
    assert payload["task"]["done_at"] is None


def test_cli_reopen_rejects_non_done_task(tmp_path) -> None:
    run_cli(tmp_path, "init", "--project-name", "demo")
    created = run_cli(tmp_path, "--json", "task", "create", "--title", "t", "--spec-ref", "docs/spec.md")
    task_id = json.loads(created.stdout)["task"]["task_id"]

    reopened = run_cli(tmp_path, "task", "reopen", task_id)

    assert reopened.returncode == 2
    assert "is not done" in reopened.stdout
