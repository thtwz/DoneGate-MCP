from __future__ import annotations

from pathlib import Path

from donegate_mcp.domain.services import DoneGateService


def test_done_transition_accepts_verified_task_with_synced_docs(tmp_path: Path) -> None:
    root = tmp_path / ".donegate-mcp"
    docs = tmp_path / "docs"
    artifacts = tmp_path / "artifacts"
    docs.mkdir()
    artifacts.mkdir()
    spec = docs / "spec.md"
    plan = docs / "plan.md"
    report = artifacts / "report.txt"
    spec.write_text("spec", encoding="utf-8")
    plan.write_text("plan", encoding="utf-8")
    report.write_text("ok", encoding="utf-8")

    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task(
        "close task",
        str(spec),
        required_doc_refs=[str(plan)],
        required_artifacts=[str(report)],
    )
    task_id = created["task"]["task_id"]
    service.transition_task(task_id, "ready")
    service.transition_task(task_id, "in_progress")
    service.transition_task(task_id, "awaiting_verification")
    service.record_verification(task_id, "passed", ref="pytest")
    service.record_doc_sync(task_id, "synced", ref=str(plan))

    result = service.transition_task(task_id, "done")

    assert result["ok"] is True
    assert result["task"]["status"] == "done"
    assert result["task"]["verification_status"] == "passed"
    assert result["task"]["doc_sync_status"] == "synced"
