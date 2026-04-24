from __future__ import annotations

import pytest

from donegate_mcp.domain.services import DoneGateService
from donegate_mcp.errors import ValidationError


def test_service_normalizes_invalid_enum_inputs_to_validation_error(tmp_path) -> None:
    service = DoneGateService(tmp_path / ".donegate-mcp")
    service.init_project("demo")
    task_id = service.create_task("Gate task", "docs/spec.md")["task"]["task_id"]

    with pytest.raises(ValidationError, match="unknown task status"):
        service.transition_task(task_id, "shipped")

    with pytest.raises(ValidationError, match="unknown verification result"):
        service.record_verification(task_id, "green")

    with pytest.raises(ValidationError, match="unknown doc sync result"):
        service.record_doc_sync(task_id, "current")


def test_read_model_projection_stays_in_sync_after_task_write(tmp_path) -> None:
    root = tmp_path / ".donegate-mcp"
    service = DoneGateService(root)
    service.init_project("demo")
    task_id = service.create_task("Gate task", "docs/spec.md")["task"]["task_id"]

    plan = service.get_plan()["plan"]
    progress = service.get_progress()["progress"]

    assert plan["nodes"][0]["task_id"] == task_id
    assert progress["tasks"][0]["task_id"] == task_id
    assert progress["summary"]["total_tasks"] == 1
    assert (root / "locks" / "write.lock").exists()
