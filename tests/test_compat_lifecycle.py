from __future__ import annotations

import json

from donegate_mcp.domain.services import DoneGateService


def test_old_task_json_awaiting_verification_with_all_gates_normalizes_to_documented(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("compat", "docs/spec.md")
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


def test_old_task_json_verified_with_synced_docs_normalizes_to_documented(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("compat", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload.pop("workflow_intent", None)
    payload["status"] = "verified"
    payload["verification_status"] = "passed"
    payload["doc_sync_status"] = "synced"
    payload["started_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    listed = service.list_tasks()
    assert listed["tasks"][0]["status"] == "documented"


def test_old_task_json_documented_with_done_at_normalizes_to_done(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    created = service.create_task("compat", "docs/spec.md")
    task_id = created["task"]["task_id"]

    task_file = root / "tasks" / f"{task_id}.json"
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    payload.pop("workflow_intent", None)
    payload["status"] = "documented"
    payload["verification_status"] = "passed"
    payload["doc_sync_status"] = "synced"
    payload["started_at"] = payload["created_at"]
    payload["done_at"] = payload["created_at"]
    task_file.write_text(json.dumps(payload), encoding="utf-8")

    listed = service.list_tasks()
    assert listed["tasks"][0]["status"] == "done"
