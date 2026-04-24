from __future__ import annotations

from pathlib import Path

from donegate_mcp.mcp.server import DoneGateMcpApp, SimpleToolServer
from donegate_mcp.mcp.tool_schemas import TOOLS


def _tool(app: DoneGateMcpApp, name: str):
    """Return a registered tool callable for either fallback or real FastMCP servers."""
    server = app.server
    if isinstance(server, SimpleToolServer):
        return server.tools[name]
    return server._tool_manager._tools[name].fn


def test_mcp_app_prefers_donegate_env_repo_root_over_server_default_data_root(tmp_path, monkeypatch) -> None:
    server_home = tmp_path / "server-home"
    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()
    monkeypatch.setenv("DONEGATE_MCP_REPO_ROOT", str(target_repo))

    app = DoneGateMcpApp(data_root=str(server_home / ".donegate-mcp"))
    payload = _tool(app, "project_init")("demo")

    assert payload["ok"] is True
    assert (target_repo / ".donegate-mcp" / "project.json").exists()
    assert not (server_home / ".donegate-mcp" / "project.json").exists()


def test_mcp_tools_accept_repo_root_override_for_target_repository(tmp_path) -> None:
    server_home = tmp_path / "server-home"
    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()

    app = DoneGateMcpApp(data_root=str(server_home / ".donegate-mcp"))
    init_payload = _tool(app, "project_init")("demo", repo_root=str(target_repo))
    create_payload = _tool(app, "task_create")(
        "Gate task",
        "docs/spec.md",
        repo_root=str(target_repo),
    )

    assert init_payload["ok"] is True
    assert create_payload["ok"] is True
    assert create_payload["task"]["spec_ref"] == str((target_repo / "docs" / "spec.md").resolve())
    assert (target_repo / ".donegate-mcp" / "project.json").exists()
    assert not (server_home / ".donegate-mcp" / "project.json").exists()


def test_mcp_review_tools_record_findings_and_create_followup_tasks(tmp_path) -> None:
    server_home = tmp_path / "server-home"
    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()

    app = DoneGateMcpApp(data_root=str(server_home / ".donegate-mcp"))
    _tool(app, "project_init")("demo", repo_root=str(target_repo))
    created = _tool(app, "task_create")("Gate task", "docs/spec.md", repo_root=str(target_repo))
    task_id = created["task"]["task_id"]

    reviewed = _tool(app, "task_review")(
        task_id,
        checkpoint="manual",
        provider_id="manual",
        summary="The literal gate passes but a user-value gap remains.",
        overall_recommendation="proceed_with_followups",
        findings=[
            {
                "dimension": "outcome_gap",
                "severity": "high",
                "title": "Users still need a recovery path",
                "details": "The task can pass without documenting how users recover from failure.",
                "recommended_action": "Add a recovery workflow and acceptance criteria.",
                "suggested_task_title": "Add recovery workflow",
                "suggested_task_summary": "Capture and implement a recovery path for failed delivery gates.",
            }
        ],
        repo_root=str(target_repo),
    )
    finding_id = reviewed["findings"][0]["finding_id"]

    followup = _tool(app, "task_create_from_finding")(finding_id, repo_root=str(target_repo))
    listed = _tool(app, "review_list")(task_id=task_id, include_findings=True, repo_root=str(target_repo))

    assert reviewed["review"]["overall_recommendation"] == "proceed_with_followups"
    assert followup["task"]["source_finding_id"] == finding_id
    assert listed["findings"][0]["followup_task_id"] == followup["task"]["task_id"]


def test_mcp_task_reopen_uses_resolved_call_context(tmp_path) -> None:
    server_home = tmp_path / "server-home"
    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()

    app = DoneGateMcpApp(data_root=str(server_home / ".donegate-mcp"))
    _tool(app, "project_init")("demo", repo_root=str(target_repo))
    created = _tool(app, "task_create")("Gate task", "docs/spec.md", repo_root=str(target_repo))
    task_id = created["task"]["task_id"]
    _tool(app, "task_transition")(task_id, "ready", repo_root=str(target_repo))
    _tool(app, "task_transition")(task_id, "awaiting_verification", repo_root=str(target_repo))
    _tool(app, "task_record_verification")(task_id, "passed", repo_root=str(target_repo))
    _tool(app, "task_record_doc_sync")(task_id, "synced", repo_root=str(target_repo))
    _tool(app, "task_transition")(task_id, "done", repo_root=str(target_repo))

    reopened = _tool(app, "task_reopen")(task_id, repo_root=str(target_repo))

    assert reopened["ok"] is True
    assert reopened["task"]["status"] == "documented"


def test_mcp_tool_schema_exposes_review_and_reopen_tools() -> None:
    assert "task_reopen" in TOOLS
    assert "task_review" in TOOLS
    assert "review_list" in TOOLS
    assert "review_disposition" in TOOLS
    assert "task_create_from_finding" in TOOLS
