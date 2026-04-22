#!/usr/bin/env bash
set -euo pipefail
ROOT=${DONEGATE_MCP_ROOT:-.donegate-mcp}
WORKDIR=${DONEGATE_MCP_WORKDIR:-$(pwd)}

if [ -z "${TASK_ID:-}" ]; then
  ACTIVE_JSON=$(PYTHONPATH=${PYTHONPATH:-src} python3 -m donegate_mcp.cli.main --data-root "$ROOT" --json task active 2>/dev/null || true)
  TASK_ID=$(printf '%s' "$ACTIVE_JSON" | python3 -c 'import json, sys
data = sys.stdin.read().strip()
if not data:
    raise SystemExit(1)
payload = json.loads(data)
task = payload.get("active_task") or {}
task_id = task.get("task_id")
if not task_id:
    raise SystemExit(1)
print(task_id)' 2>/dev/null || true)
fi

: "${TASK_ID:?TASK_ID is required; set TASK_ID or activate a task in DoneGate}"
PYTHONPATH=${PYTHONPATH:-src} python3 -m donegate_mcp.cli.main --data-root "$ROOT" --json task self-test "$TASK_ID" --workdir "$WORKDIR" >/tmp/donegate-mcp-self-test.json
