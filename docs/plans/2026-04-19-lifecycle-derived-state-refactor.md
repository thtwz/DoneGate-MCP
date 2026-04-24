# DoneGate Lifecycle Derived-State Refactor Plan

> **For Hermes:** Use subagent-driven-development to execute this plan task-by-task. Keep changes small and verify after each slice.

**Goal:** Remove order-coupling and hand-driven lifecycle drift in DoneGate by making task lifecycle status a projection of domain facts instead of a fragile manually advanced sequence.

**Architecture:** Keep the existing MCP/CLI APIs, but refactor lifecycle handling so `workflow_intent`, `verification_status`, `doc_sync_status`, `blocked_reason`, `needs_revalidation`, and completion timestamps become the primary persisted data. Introduce a single lifecycle projection function that derives the effective workflow phase (`draft`, `ready`, `in_progress`, `awaiting_verification`, `documented`, `done`, `blocked`) from those facts, then shrink imperative transition rules to only the steps that represent user intent rather than internal progress bookkeeping.

**Tech Stack:** Python, dataclasses, enum-based domain model, MCP tool server, CLI wrapper, pytest.

---

## Why this refactor is needed

The current lifecycle bug we just fixed exposed a deeper architectural issue:
- verification/doc sync are independent facts
- lifecycle status is currently advanced by event order
- therefore the system can reach illegal or stale intermediate states even when all gates are satisfied

That is the wrong ownership boundary.

**Correct model:**
- Facts:
  - `verification_status`
  - `doc_sync_status`
  - `blocked_reason`
  - `needs_revalidation`
  - `started_at`
  - `done_at`
- Derived lifecycle phase:
  - blocked / in_progress / awaiting_verification / documented / done

The lifecycle phase should be computed from facts whenever possible.

---

## Target design

### Domain facts stay explicit
Keep these persisted on `Task`:
- `verification_status`
- `doc_sync_status`
- `needs_revalidation`
- `blocked_reason`
- `started_at`
- `verified_at`
- `documented_at`
- `done_at`

### Lifecycle becomes a projection
Add a central function, for example:
- `project_status(task: Task) -> TaskStatus`

Rules should read like:
1. if `done_at` is set -> `done`
2. if blocked -> `blocked`
3. if not started -> `draft` or `ready` based on explicit start gating
4. if revalidation required -> `in_progress`
5. if verification not passed -> `awaiting_verification` once work started
6. if docs not synced -> `verified`
7. if verification passed and docs synced -> `documented` (or `done` only when explicit close action occurs)

### Explicit user actions remain explicit
Still keep intentional transitions/actions for:
- start work
- submit for verification
- block/unblock
- close/done

But those actions should mutate facts and/or milestone timestamps, then re-project status, instead of manually shuffling through intermediate labels.

### Backward compatibility
Do **not** break:
- existing `task_transition` MCP tool
- existing CLI commands (`start`, `submit`, `done`, `transition`)
- on-disk task JSON compatibility

Instead:
- persist `workflow_intent` and facts in new task JSON
- accept old task JSON that still has `status`
- return `status` from CLI/MCP as a compatibility alias for `projected_status`

---

## Scope of this refactor

### In scope
- central lifecycle projection helper
- reduce order sensitivity between verification/doc sync
- make dashboard derive missing verification/docs from facts, not brittle raw status checks
- keep current public API behavior stable
- add tests for out-of-order fact recording and replay/loading consistency

### Out of scope
- multi-user locking/concurrency
- workflow customization per project
- large storage format migration beyond additive/backward-compatible changes

---

## Execution plan

### Task 1: Add lifecycle projection helper

**Objective:** Create one canonical place that computes the effective task status from task facts.

**Files:**
- Modify: `src/donegate_mcp/domain/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Step 1: Write failing tests**
Add tests for projection cases:
- passed verification + synced docs + not done => `documented`
- passed verification + docs unknown => `verified`
- started + verification unknown => `awaiting_verification`
- blocked reason present => `blocked`
- done_at set => `done`

**Step 2: Implement helper**
Add something like:
```python
def project_status(task: Task) -> TaskStatus:
    ...
```

**Step 3: Verify tests pass**
Run:
```bash
pytest tests/test_lifecycle.py -q
```

---

### Task 2: Normalize task state after every domain mutation

**Objective:** Ensure verification/doc sync/block/start/close actions all end by projecting status from facts and `workflow_intent`.

**Files:**
- Modify: `src/donegate_mcp/domain/lifecycle.py`
- Modify: `src/donegate_mcp/domain/services.py`
- Test: `tests/test_services.py`

**Step 1: Add tests for order independence**
Cases:
- doc sync before verification
- verification before doc sync
- replay old persisted task with stale status but passed gates -> status recomputed correctly

**Step 2: Implement normalization flow**
Pattern:
- domain actions mutate facts/timestamps
- call `project_status(...)`
- return projected status at API/read-model boundaries without writing `status` back to task storage

**Step 3: Verify**
Run:
```bash
pytest tests/test_services.py tests/test_lifecycle.py -q
```

---

### Task 3: Separate intent transitions from derived internal progress

**Objective:** Make transition rules represent only user intent, not mandatory internal status stepping.

**Files:**
- Modify: `src/donegate_mcp/domain/lifecycle.py`
- Modify: `src/donegate_mcp/cli/main.py`
- Modify: `src/donegate_mcp/domain/services.py`
- Test: `tests/test_cli.py`

**Implementation direction:**
- `start` means “mark started / enter active work”
- `submit` means “ready for verification” but status after that is projected
- `done` means “close if facts satisfy done gate”
- raw `transition --to verified/documented` may remain for compatibility, but should be normalized through projection rules and explicitly labeled as deprecated compatibility aliases

**Verification:**
```bash
pytest tests/test_cli.py -q
```

---

### Task 4: Make dashboard/reporting fact-driven

**Objective:** Prevent dashboard from becoming inconsistent with projected lifecycle.

**Files:**
- Modify: `src/donegate_mcp/domain/dashboard.py`
- Test: `tests/test_services.py` or add `tests/test_dashboard.py`

**Implementation direction:**
- `missing_verification` should be based on started work + verification fact, not just raw `status == awaiting_verification`
- `missing_docs` should be based on verification passed + docs not synced
- next actions should use projected status/facts together

**Verification:**
```bash
pytest tests/test_services.py -q
```

---

### Task 5: Add compatibility/replay tests for old task JSON

**Objective:** Ensure existing task files continue to work after projection logic is introduced.

**Files:**
- Test: add `tests/test_compat_lifecycle.py`

**Cases:**
- task file says `awaiting_verification`, but verification passed + docs synced -> loads/normalizes safely
- task file says `verified`, but docs already synced -> becomes documented
- task file says `documented`, done_at set -> becomes done

---

### Task 6: Document lifecycle semantics

**Objective:** Update docs so users and future maintainers understand the distinction between facts and derived phase.

**Files:**
- Modify: `docs/plan.md`
- Add or modify: `docs/plans/2026-04-19-lifecycle-derived-state-refactor.md` (this file)

**Doc updates should state:**
- verification/doc sync are domain facts
- lifecycle phase is projected from facts
- public commands still exist, but internal progression is now order-independent

---

## Acceptance criteria

The refactor is complete when all are true:

1. Recording verification/doc sync in either order yields the same effective lifecycle state.
2. `done` succeeds whenever required facts are present, regardless of previous event order.
3. Dashboard reflects fact-derived truth, not stale raw status.
4. Existing MCP/CLI commands still work.
5. Existing task JSON remains readable and normalizable.
6. Full relevant tests pass.

---

## Recommended first implementation slice

Start with **Task 1 + Task 2 only**.

Why:
- highest leverage
- smallest safe vertical slice
- directly attacks the bug class we just found
- gives immediate confidence before touching CLI/dashboard semantics

---

## Verification commands

Minimum:
```bash
pytest tests/test_lifecycle.py tests/test_services.py -q
```

Then broader:
```bash
pytest -q
```

---

## Risks

1. **Status projection may conflict with existing CLI expectations**
   - mitigate with compatibility tests before changing CLI behavior

2. **Dashboard semantics may change subtly**
   - mitigate with explicit tests for next-actions and missing-verification/docs lists

3. **Persisted `status` field may become stale if not normalized everywhere**
   - mitigate by centralizing normalization after every mutation and on load paths if needed

---

## Next action

Proceed with the first implementation slice:
- add lifecycle projection helper
- normalize task state after verification/doc sync mutations
- add order-independence tests
