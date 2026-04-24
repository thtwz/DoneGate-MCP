# DoneGate v0.4.0 Release Notes

v0.4.0 adds an advisory review layer for AI-assisted delivery.

## Highlights

- Records advisory review runs at `submit`, `pre_done`, or manual checkpoints.
- Stores normalized review findings with severity, disposition, and recommended action.
- Converts review findings into linked follow-up tasks.
- Exposes advisory summaries in task payloads, dashboard, progress, and supervision.
- Adds CLI commands for `task review`, `review list`, `review disposition`, and `task create-from-finding`.
- Adds MCP tools for `task_review`, `review_list`, `review_disposition`, and `task_create_from_finding`.
- Updates Codex/LLM-oriented docs so agents can inspect pending advisory reviews and record architect-style findings.

## Notes

Advisory findings do not block `done` in this release. The delivery gate remains deterministic: verification, documentation sync, required docs/artifacts, and spec drift still decide whether a task can close.
