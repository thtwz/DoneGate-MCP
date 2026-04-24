# DoneGate v0.1 Plan

## Goal
Build a first working MCP server that manages a spec-driven delivery workflow for AI-assisted projects. The server should externalize project state, enforce simple delivery gates, and be easy to trigger from git hooks or CI.

## Assumptions
1. Single project workspace per MCP server data root.
2. State is stored on disk in human-readable files, no DB in v0.1.
3. Hooks will call the MCP tools or bundled CLI wrapper.
4. A task cannot be closed unless verification and doc-sync evidence exist.
5. We optimize for local reliability first, not multi-user concurrency.

## Scope for v0.1
- Load/create project workspace state.
- Manage tasks with projected workflow phases: draft, ready, in_progress, awaiting_verification, verified, documented, done, blocked.
- Treat verification/doc-sync/blocking/completion timestamps as primary domain facts.
- Keep `start`, `submit`, `done`, `reopen`, `block`, and `unblock` as the main intent commands.
- Preserve `transition --to verified|documented` only as compatibility aliases, not preferred operator workflow.
- Record verification results.
- Record documentation sync results.
- Close task only if required evidence exists.
- Provide dashboard summary.
- Provide a small CLI wrapper for git/CI hooks.
- Include tests for gating behavior.

## Out of Scope for v0.1
- Auto-generating plans from natural language.
- Multi-project registry server.
- Web UI.
- Real CI provider integrations.
- Background watchers/daemons.
- Fine-grained RBAC or auth.

## Milestones
1. Scaffold package and storage model.
2. Implement project/task lifecycle logic.
3. Expose MCP tools.
4. Add CLI wrapper for hooks.
5. Add tests for gates and state transitions.
6. Smoke test via local CLI/MCP entrypoints.

## Acceptance Criteria
- Can initialize a project state folder.
- Can create/list/start tasks.
- Can record failed/passed verification for a task.
- Can record doc sync for a task.
- Closing a task without both verification pass and doc sync is rejected.
- Closing a task after both conditions succeeds.
- Dashboard shows counts and next actionable tasks.
- Existing task JSON can be replayed and normalized from stale raw status values.
- New task JSON persists `workflow_intent` and facts; `status` is projected at read/API boundaries.
- Tests pass locally.
- The documentation clearly states that acceptance evidence must come from real system facts, not assistant narration or UI-only cues.
- The demo/docs show that acceptance for behavior-changing workflows should verify externally observable outcome + boundary result + persisted source-of-truth state + downstream derived state, not just a single success cue.
- The project guidance explicitly calls out that realistic validation conditions may be required when fixtures can hide broken workflow assumptions.

## Risks
- MCP SDK APIs differ by installed version.
- Hook usage may need a CLI wrapper to avoid direct MCP-client dependency.
- Over-design risk: avoid building full PM system in v0.1.

## Delivery Strategy
Implement a thin but real vertical slice: storage + policy engine + MCP tool layer + CLI wrapper + tests.
