from __future__ import annotations

from typing import Any, Callable

from donegate_mcp.domain.services import DoneGateService
from donegate_mcp.errors import DoneGateMcpError


class SimpleToolServer:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def tool(self, name: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        def decorator(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self.tools[name] = func
            return func
        return decorator


class DoneGateMcpApp:
    def __init__(self, data_root: str | None = None) -> None:
        self.service = DoneGateService(data_root=data_root)
        self.server = self._build_server()

    def _build_server(self) -> Any:
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore
            # Use an identifier-safe MCP server name so host tooling can derive
            # stable namespaces without needing to sanitize hyphenated labels.
            server: Any = FastMCP("donegate_mcp")
        except Exception:
            server = SimpleToolServer()
        self._register_tools(server)
        return server

    def _register_tools(self, server: Any) -> None:
        @server.tool("project_init")
        def project_init(project_name: str, default_branch: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.init_project, project_name, default_branch)

        @server.tool("project_dashboard")
        def project_dashboard(include_tasks: bool = False, limit: int = 10) -> dict[str, Any]:
            return self._safe(self.service.dashboard, include_tasks=include_tasks, limit=limit)

        @server.tool("task_create")
        def task_create(title: str, spec_ref: str, summary: str = "", verification_mode: str = "manual", test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, plan_node_id: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.create_task, title, spec_ref, summary=summary, verification_mode=verification_mode, test_commands=test_commands, required_doc_refs=required_doc_refs, required_artifacts=required_artifacts, plan_node_id=plan_node_id)

        @server.tool("task_list")
        def task_list(status: str | None = None, limit: int | None = None) -> dict[str, Any]:
            return self._safe(self.service.list_tasks, status=status, limit=limit)

        @server.tool("task_transition")
        def task_transition(task_id: str, target_status: str, reason: str | None = None, notes: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.transition_task, task_id, target_status, reason=reason, notes=notes)

        @server.tool("task_record_verification")
        def task_record_verification(task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.record_verification, task_id, result, ref=ref, notes=notes)

        @server.tool("task_record_doc_sync")
        def task_record_doc_sync(task_id: str, result: str, ref: str | None = None, notes: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.record_doc_sync, task_id, result, ref=ref, notes=notes)

        @server.tool("task_update_acceptance_protocol")
        def task_update_acceptance_protocol(task_id: str, verification_mode: str | None = None, test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, plan_node_id: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.update_acceptance_protocol, task_id, verification_mode=verification_mode, test_commands=test_commands, required_doc_refs=required_doc_refs, required_artifacts=required_artifacts, plan_node_id=plan_node_id)

        @server.tool("task_run_self_test")
        def task_run_self_test(task_id: str, workdir: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.run_self_test, task_id, workdir=workdir)

        @server.tool("spec_refresh")
        def spec_refresh(spec_ref: str, reason: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.refresh_spec, spec_ref, reason=reason)

        @server.tool("deviation_record")
        def deviation_record(task_id: str, summary: str, details: str, spec_ref: str | None = None) -> dict[str, Any]:
            return self._safe(self.service.record_deviation, task_id, summary, details, spec_ref=spec_ref)

        @server.tool("deviation_list")
        def deviation_list() -> dict[str, Any]:
            return self._safe(self.service.list_deviations)

        @server.tool("task_block")
        def task_block(task_id: str, reason: str) -> dict[str, Any]:
            return self._safe(self.service.block_task, task_id, reason)

        @server.tool("task_unblock")
        def task_unblock(task_id: str, target_status: str) -> dict[str, Any]:
            return self._safe(self.service.unblock_task, task_id, target_status)

    @staticmethod
    def _safe(func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except DoneGateMcpError as exc:
            return {"ok": False, "errors": [str(exc)]}


def build_app(data_root: str | None = None) -> DoneGateMcpApp:
    return DoneGateMcpApp(data_root=data_root)
