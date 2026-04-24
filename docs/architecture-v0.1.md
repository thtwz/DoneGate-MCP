# DoneGate v0.1 Architecture

## 1. Design Goals
- Keep v0.1 file-backed and deterministic.
- Make delivery rules explicit in a small policy layer.
- Expose the same core operations through MCP tools and a hook-friendly CLI.
- Optimize for single-workspace local usage, not concurrency-heavy collaboration.

## 2. Proposed Package Layout

```text
src/donegate_mcp/
  __init__.py
  config.py                # data root, file names, defaults
  models.py                # typed domain objects and enums
  errors.py                # domain + validation errors
  storage/
    __init__.py
    project_store.py       # load/save project metadata
    task_store.py          # load/save task records
    event_store.py         # append-only task evidence log
    fs.py                  # atomic writes, path helpers, locking-lite
  domain/
    __init__.py
    lifecycle.py           # transition rules and gate enforcement
    dashboard.py           # summary/read model generation
    services.py            # orchestration methods used by MCP + CLI
  mcp/
    __init__.py
    server.py              # MCP server bootstrap and tool registration
    tool_schemas.py        # shared input/output schemas
  cli/
    __init__.py
    main.py                # argparse/typer entrypoint for hooks/CI
    formatters.py          # json/text output helpers
```

Supporting files:

```text
tests/
  test_lifecycle.py
  test_services.py
  test_dashboard.py
  test_cli.py
  fixtures.py
pyproject.toml             # deps, console scripts, test config
```

## 3. State Files on Disk
Use a single data root inside the project workspace so state is human-readable and commit-optional.

```text
.donegate-mcp/
  project.json             # workspace metadata + schema version
  tasks/
    TASK-001.json
    TASK-002.json
  events/
    TASK-001.jsonl         # append-only verification/doc/status events
  locks/
    .write.lock            # optional coarse lock file for atomic updates
```

### `project.json`
Fields:
- `schema_version`
- `project_id`
- `project_name`
- `created_at`
- `updated_at`
- `default_branch` (optional)
- `task_counter`

### `tasks/TASK-001.json`
Fields:
- `task_id`
- `title`
- `spec_ref` (path/URI to spec or ticket)
- `workflow_intent` (`draft|ready|in_progress|awaiting_verification`)
- `summary`
- `blocked_reason` (nullable)
- `created_at`
- `updated_at`
- `started_at` (nullable)
- `verified_at` (nullable)
- `documented_at` (nullable)
- `done_at` (nullable)
- `verification_status` (`unknown|failed|passed`)
- `doc_sync_status` (`unknown|outdated|synced`)
- `last_verification_ref` (nullable, e.g. test log path)
- `last_doc_sync_ref` (nullable)

`status` is not persisted in new task files. It is returned by CLI/MCP/read models as a compatibility alias for the projected lifecycle phase.

### `events/TASK-001.jsonl`
One JSON object per line for auditability.
Event types:
- `task_created`
- `status_changed`
- `verification_recorded`
- `doc_sync_recorded`
- `task_blocked`
- `task_unblocked`

Rationale: task JSON provides current state; event log preserves evidence history without requiring event sourcing everywhere.

## 4. Main Domain Objects
Defined in `src/donegate_mcp/models.py`.

- `ProjectState`
  - project-level metadata and task counter.
- `Task`
  - canonical facts and workflow intent for one delivery item.
- `TaskStatus` enum
  - projected phases: `draft`, `ready`, `in_progress`, `awaiting_verification`, `verified`, `documented`, `done`, `blocked`.
- `WorkflowIntent` enum
  - persisted operator intent: `draft`, `ready`, `in_progress`, `awaiting_verification`.
- `VerificationRecord`
  - `task_id`, `result`, `recorded_at`, `ref`, `notes`.
- `DocSyncRecord`
  - `task_id`, `result`, `recorded_at`, `ref`, `notes`.
- `TaskEvent`
  - generic append-only event wrapper with `type`, `timestamp`, `actor`, `payload`.
- `DashboardSummary`
  - counts by status, blocked tasks, tasks missing verification, tasks missing docs, next actionable tasks.

## 5. Transition and Gate Rules
Implement in `src/donegate_mcp/domain/lifecycle.py` as pure functions plus small validators.

### Intent-driven command surface
Preferred operator commands are:
- `start` -> expresses “work has started”
- `submit` -> expresses “ready for verification”
- `verify` / `doc-sync` -> record domain facts
- `done` -> expresses “close the task if facts satisfy the gate”
- `block` / `unblock` -> explicit interruption management

### Compatibility transitions
- `transition --to verified`
- `transition --to documented`

remain supported for backward compatibility, but should be treated as compatibility aliases rather than the recommended workflow. The real lifecycle phase is projected from facts after the transition request is applied.

### Narrow raw transition table
The raw transition table should only protect coarse intent edges and explicit unblock targets:
- `draft -> ready | blocked`
- `ready -> in_progress | blocked`
- `in_progress -> awaiting_verification | blocked`
- `awaiting_verification -> in_progress | blocked`
- `verified -> in_progress | blocked`
- `documented -> done | in_progress | blocked`
- `blocked -> draft | ready | in_progress | awaiting_verification` (explicit unblock target required)
- `done` is terminal in v0.1

### Derived gate rules
- `verified` is a projected phase: work started + `verification_status == passed` + docs not yet synced.
- `documented` is a projected phase: `verification_status == passed` + `doc_sync_status == synced` + task not yet closed.
- `done` requires both:
  - `verification_status == passed`
  - `doc_sync_status == synced`
- Recording failed verification should:
  - set `verification_status = failed`
  - project task back to `in_progress`
- Recording doc sync as outdated should:
  - set `doc_sync_status = outdated`
  - project task back to `verified` if verification still passes, otherwise `in_progress`
- A blocked task cannot move directly to `done`.

### Service-level operations
Expose intent-based methods rather than arbitrary field edits:
- `init_project(...)`
- `create_task(...)`
- `list_tasks(...)`
- `transition_task(task_id, target_status, ...)`
- `record_verification(task_id, result, ref, notes)`
- `record_doc_sync(task_id, result, ref, notes)`
- `block_task(task_id, reason)`
- `unblock_task(task_id, target_status)`
- `get_dashboard()`

## 6. MCP Tool Surface
Register these tools in `src/donegate_mcp/mcp/server.py`.

### Project tools
1. `project_init`
   - input: `project_name`, `data_root?`, `default_branch?`
   - output: project metadata and resolved paths

2. `project_dashboard`
   - input: `include_tasks?`, `limit?`
   - output: `DashboardSummary`

### Task tools
3. `task_create`
   - input: `title`, `spec_ref`, `summary?`
   - output: created `Task`

4. `task_list`
   - input: `status?`, `limit?`
   - output: list of `Task`

5. `task_transition`
   - input: `task_id`, `target_status`, `reason?`, `notes?`
   - output: updated `Task`

6. `task_record_verification`
   - input: `task_id`, `result` (`passed|failed`), `ref?`, `notes?`
   - output: updated `Task` + latest verification record

7. `task_record_doc_sync`
   - input: `task_id`, `result` (`synced|outdated`), `ref?`, `notes?`
   - output: updated `Task` + latest doc record

8. `task_block`
   - input: `task_id`, `reason`
   - output: updated `Task`

9. `task_unblock`
   - input: `task_id`, `target_status`
   - output: updated `Task`

Tool behavior notes:
- Every write tool returns machine-friendly JSON with `ok`, `task`, `events_written`, and `errors` fields.
- MCP layer should be thin: validate input schema, call domain service, serialize response.
- Avoid embedding policy in tool handlers.

## 7. CLI Hook Surface
Implement in `src/donegate_mcp/cli/main.py` and expose console script `donegate-mcp`.

Recommended commands:

```text
donegate-mcp init --project-name NAME [--data-root .donegate-mcp]
donegate-mcp task create --title ... --spec-ref ... [--summary ...]
donegate-mcp task list [--status ...] [--json]
donegate-mcp task start TASK-ID                     # alias for transition -> in_progress
donegate-mcp task submit TASK-ID                    # alias for transition -> awaiting_verification
donegate-mcp task verify TASK-ID --result passed|failed [--ref ...] [--notes ...]
donegate-mcp task doc-sync TASK-ID --result synced|outdated [--ref ...] [--notes ...]
donegate-mcp task done TASK-ID                      # attempts transition -> done, emits gate failure reason
donegate-mcp task block TASK-ID --reason ...
donegate-mcp task unblock TASK-ID --to ready|in_progress|awaiting_verification
donegate-mcp dashboard [--json]
```

Hook/CI usage guidance:
- Default all CLI output to concise text for humans; support `--json` for hooks.
- Exit codes:
  - `0`: success
  - `2`: validation/usage error
  - `3`: gate violation (e.g. cannot close task)
  - `4`: storage/runtime failure
- Hook commands should accept refs to generated artifacts (`--ref reports/pytest.xml`) instead of parsing CI systems directly.

## 8. Testing Strategy
Use `pytest` with temporary directories; no network, no real MCP client required for most tests.

### Unit tests
`tests/test_lifecycle.py`
- valid/invalid transitions
- cannot mark `done` without verification + doc sync
- failed verification rewinds status correctly
- outdated docs rewinds status correctly

### Service/storage tests
`tests/test_services.py`
- init project creates expected files
- create/list/update task persists state
- events are appended for every write operation
- task counter increments deterministically

### Dashboard tests
`tests/test_dashboard.py`
- counts by status are correct
- next actionable tasks prioritizes:
  1. `blocked`
  2. `awaiting_verification` without passed check
  3. `verified` without synced docs
  4. `ready` tasks

### CLI tests
`tests/test_cli.py`
- JSON output shape for hooks
- exit code `3` on close rejection
- aliases (`start`, `submit`, `done`) invoke correct service calls

### MCP smoke tests
If MCP SDK is stable enough, add one thin test module later:
- tool registration succeeds
- sample tool call maps to service layer

For v0.1, keep most behavior verified below the MCP adapter to avoid SDK churn risk.

## 9. Practical Implementation Notes
- Prefer Pydantic/dataclasses for models; keep serialized JSON flat and stable.
- Use atomic write pattern in `storage/fs.py`: write temp file, fsync, rename.
- Use one coarse lock per workspace during writes; sufficient for local hooks.
- Include `schema_version` in project/task files for future migrations.
- Keep task IDs simple: `TASK-0001`, `TASK-0002`.
- Do not build generic workflow configuration yet; hardcode the v0.1 lifecycle.

## 10. Suggested Build Order
1. `models.py`, `errors.py`
2. `storage/fs.py`, `project_store.py`, `task_store.py`, `event_store.py`
3. `domain/lifecycle.py`
4. `domain/services.py`
5. `domain/dashboard.py`
6. `cli/main.py`
7. `mcp/server.py`
8. tests

This keeps the core policy engine reusable and minimizes risk from MCP SDK/version differences.
