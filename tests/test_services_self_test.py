from __future__ import annotations

import os
import subprocess
from pathlib import Path

from donegate_mcp.domain.services import DoneGateService
from donegate_mcp.errors import TransitionError


def test_self_test_passes_and_records_artifacts(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md", verification_mode="self-test", test_commands=["python3 -c 'print(123)'"])
    task_id = created["task"]["task_id"]
    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    result = service.run_self_test(task_id, workdir=str(tmp_path))
    assert result["task"]["verification_status"] == "passed"
    assert result["exit_code"] == 0
    assert result["self_test"]["stdout_path"].endswith('.stdout.log')


def test_self_test_failure_marks_verification_failed(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md", verification_mode="self-test", test_commands=["python3 -c 'import sys; sys.exit(7)'"])
    task_id = created["task"]["task_id"]
    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    result = service.run_self_test(task_id, workdir=str(tmp_path))
    assert result["task"]["verification_status"] == "failed"
    assert result["task"]["status"] == "in_progress"
    assert result["exit_code"] == 7


def test_done_requires_existing_artifacts_and_doc_refs(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    doc = tmp_path / "docs" / "plan.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("ok", encoding="utf-8")
    created = service.create_task("Gate task", "docs/spec.md", required_doc_refs=[str(doc)], required_artifacts=[str(tmp_path / 'reports' / 'pytest.txt')])
    task_id = created["task"]["task_id"]
    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    service.record_verification(task_id, "passed", ref="x")
    service.record_doc_sync(task_id, "synced", ref=str(doc))
    try:
        service.transition_task(task_id, "done")
    except TransitionError as exc:
        assert "missing required artifacts" in str(exc)
    else:
        raise AssertionError('expected artifact gate failure')


def test_plan_progress_and_spec_drift(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    spec = tmp_path / "spec.md"
    spec.write_text("v1", encoding="utf-8")
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", str(spec), plan_node_id="phase-1-task-a")
    task_id = created["task"]["task_id"]
    spec.write_text("v2", encoding="utf-8")
    refreshed = service.refresh_spec(str(spec), reason="spec changed")
    assert task_id in refreshed["changed_tasks"]
    plan = service.get_plan()["plan"]
    progress = service.get_progress()["progress"]
    assert plan["nodes"][0]["needs_revalidation"] is True
    assert progress["stale_tasks"][0]["task_id"] == task_id


def test_deviation_recording(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md")
    task_id = created["task"]["task_id"]
    service.record_deviation(task_id, "changed behavior", "temporary divergence")
    listed = service.list_deviations()["deviations"]
    assert listed[0]["task_id"] == task_id
    assert listed[0]["summary"] == "changed behavior"


def test_pre_commit_hook_uses_active_task_when_task_id_missing(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task(
        "Gate task",
        "docs/spec.md",
        verification_mode="self-test",
        test_commands=["python3 -c 'print(123)'"],
    )
    task_id = created["task"]["task_id"]
    service.activate_task(task_id)

    env = dict(os.environ)
    env["DONEGATE_MCP_ROOT"] = str(root)
    env["DONEGATE_MCP_WORKDIR"] = str(repo)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("TASK_ID", None)

    hook = Path(__file__).resolve().parents[1] / "scripts" / "pre-commit.sh"
    completed = subprocess.run(
        [str(hook)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert '"verification_status": "passed"' in completed.stdout


def test_pre_commit_hook_blocks_when_supervision_reports_task_mismatch(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    src = repo / "src"
    tests_dir = repo / "tests"
    src.mkdir()
    tests_dir.mkdir()
    (src / "tracked.py").write_text("print('v1')\n", encoding="utf-8")
    (tests_dir / "test_tracked.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/tracked.py", "tests/test_tracked.py"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    root = repo / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo", repo_root=str(repo))
    task_id = service.create_task(
        "Gate task",
        "docs/spec.md",
        verification_mode="self-test",
        test_commands=["python3 -c 'print(123)'"],
        owned_paths=["src"],
    )["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)
    (tests_dir / "test_tracked.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")

    env = dict(os.environ)
    env["DONEGATE_MCP_ROOT"] = str(root)
    env["DONEGATE_MCP_WORKDIR"] = str(repo)
    env["DONEGATE_MCP_REPO_ROOT"] = str(repo)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("TASK_ID", None)

    hook = Path(__file__).resolve().parents[1] / "scripts" / "pre-commit.sh"
    completed = subprocess.run(
        [str(hook)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "task_mismatch" in completed.stderr


def test_pre_push_hook_blocks_when_supervision_reports_stale_docs(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    root = repo / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo", repo_root=str(repo))
    task_id = service.create_task(
        "Gate task",
        "docs/spec.md",
        verification_mode="self-test",
        test_commands=["python3 -c 'print(123)'"],
    )["task"]["task_id"]
    service.activate_task(task_id, repo_root=repo)
    service.record_verification(task_id, "passed", ref="reports/pytest.txt")

    env = dict(os.environ)
    env["DONEGATE_MCP_ROOT"] = str(root)
    env["DONEGATE_MCP_WORKDIR"] = str(repo)
    env["DONEGATE_MCP_REPO_ROOT"] = str(repo)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("TASK_ID", None)

    hook = Path(__file__).resolve().parents[1] / "scripts" / "pre-push.sh"
    completed = subprocess.run(
        [str(hook)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "stale_docs" in completed.stderr


def test_unblock_task_clears_blocked_projection_before_transition(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("Gate task", "docs/spec.md")
    task_id = created["task"]["task_id"]
    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.block_task(task_id, "waiting on design")

    result = service.unblock_task(task_id, "in_progress")

    assert result["ok"] is True
    assert result["task"]["status"] == "in_progress"
    assert result["task"]["blocked_reason"] is None
