from __future__ import annotations

import os
from pathlib import Path
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
        self.default_data_root = str(Path(data_root).resolve()) if data_root is not None else None
        self.server = self._build_server()

    def _resolve_call_context(self, repo_root: str | None = None, data_root: str | None = None) -> tuple[DoneGateService, str | None]:
        resolved_repo_root = repo_root or os.environ.get("DONEGATE_MCP_REPO_ROOT") or os.environ.get("DONEGATE_MCP_WORKDIR")
        resolved_data_root = data_root or os.environ.get("DONEGATE_MCP_ROOT")
        if resolved_data_root is None and resolved_repo_root is not None:
            resolved_data_root = str((Path(resolved_repo_root).resolve() / ".donegate-mcp"))
        if resolved_data_root is None:
            resolved_data_root = self.default_data_root
        return DoneGateService(data_root=resolved_data_root), resolved_repo_root

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
        def project_init(project_name: str, default_branch: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, resolved_repo_root = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.init_project, project_name, default_branch, repo_root=resolved_repo_root)

        @server.tool("project_dashboard")
        def project_dashboard(include_tasks: bool = False, limit: int = 10, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.dashboard, include_tasks=include_tasks, limit=limit)

        @server.tool("task_create")
        def task_create(title: str, spec_ref: str, summary: str = "", verification_mode: str = "manual", test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, owned_paths: list[str] | None = None, plan_node_id: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.create_task, title, spec_ref, summary=summary, verification_mode=verification_mode, test_commands=test_commands, required_doc_refs=required_doc_refs, required_artifacts=required_artifacts, owned_paths=owned_paths, plan_node_id=plan_node_id)

        @server.tool("task_list")
        def task_list(status: str | None = None, limit: int | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.list_tasks, status=status, limit=limit)

        @server.tool("task_transition")
        def task_transition(task_id: str, target_status: str, reason: str | None = None, notes: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.transition_task, task_id, target_status, reason=reason, notes=notes)

        @server.tool("task_record_verification")
        def task_record_verification(task_id: str, result: str, ref: str | None = None, notes: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.record_verification, task_id, result, ref=ref, notes=notes)

        @server.tool("task_record_doc_sync")
        def task_record_doc_sync(task_id: str, result: str, ref: str | None = None, notes: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.record_doc_sync, task_id, result, ref=ref, notes=notes)

        @server.tool("task_update_acceptance_protocol")
        def task_update_acceptance_protocol(task_id: str, verification_mode: str | None = None, test_commands: list[str] | None = None, required_doc_refs: list[str] | None = None, required_artifacts: list[str] | None = None, owned_paths: list[str] | None = None, plan_node_id: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.update_acceptance_protocol, task_id, verification_mode=verification_mode, test_commands=test_commands, required_doc_refs=required_doc_refs, required_artifacts=required_artifacts, owned_paths=owned_paths, plan_node_id=plan_node_id)

        @server.tool("task_run_self_test")
        def task_run_self_test(task_id: str, workdir: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.run_self_test, task_id, workdir=workdir)

        @server.tool("spec_refresh")
        def spec_refresh(spec_ref: str, reason: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.refresh_spec, spec_ref, reason=reason)

        @server.tool("deviation_record")
        def deviation_record(task_id: str, summary: str, details: str, spec_ref: str | None = None, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.record_deviation, task_id, summary, details, spec_ref=spec_ref)

        @server.tool("deviation_list")
        def deviation_list(repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.list_deviations)

        @server.tool("task_block")
        def task_block(task_id: str, reason: str, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.block_task, task_id, reason)

        @server.tool("task_reopen")
        def task_reopen(task_id: str, target_status: str = "in_progress") -> dict[str, Any]:
            return self._safe(self.service.reopen_task, task_id, target_status=target_status)

        @server.tool("task_unblock")
        def task_unblock(task_id: str, target_status: str, repo_root: str | None = None, data_root: str | None = None) -> dict[str, Any]:
            service, _ = self._resolve_call_context(repo_root=repo_root, data_root=data_root)
            return self._safe(service.unblock_task, task_id, target_status)

    @staticmethod
    def _safe(func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except DoneGateMcpError as exc:
            return {"ok": False, "errors": [str(exc)]}


def build_app(data_root: str | None = None) -> DoneGateMcpApp:
    return DoneGateMcpApp(data_root=data_root)


def main(data_root: str | None = None) -> int:
    resolved_root = data_root or os.environ.get("DONEGATE_MCP_DATA_ROOT")
    app = build_app(resolved_root)
    server = app.server
    if hasattr(server, "run"):
        server.run()
        return 0
    raise SystemExit("donegate-mcp fallback server loaded; install mcp in runtime env")


if __name__ == "__main__":
    raise SystemExit(main())
