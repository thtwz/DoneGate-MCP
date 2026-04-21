# Product Notes

## Brand

Project name: `DoneGate MCP`
Public-facing docs and code-facing package names should use `DoneGate MCP` / `donegate_mcp` consistently.

## Core framing

Position v0.1 as a lightweight quality gate for AI-assisted software delivery.

This project is not a project manager, not a CI platform, and not a general workflow engine. It is the narrow layer that answers one question reliably: can this task honestly be called done?

## Keep

- Hard gate: a task cannot become done without verification pass and doc sync.
- Local-first file state that teams can inspect and optionally commit.
- Hook-friendly CLI as the primary operational surface.
- MCP support as an orchestration layer, not the primary value proposition.
- Strong tests around lifecycle and gate enforcement.
- Spec drift and revalidation as first-class workflow concepts.
- Acceptance must be evidence-driven, not narration-driven: one-layer success cues are never enough on their own.

## Acceptance lessons from real usage

DoneGate MCP should explicitly encode the following reusable lessons about acceptance:

1. **A single success signal is not acceptance evidence.**
   A UI message, a log line, a returned status, or any other one-layer success cue is not enough by itself; acceptance still has to verify that the underlying state change actually happened.

2. **Acceptance must verify the full closed loop, not just one layer.**
   For any workflow step that changes system behavior, the real gate should check all of:
   - the externally observable outcome,
   - the operation result at the system boundary,
   - the persisted source-of-truth state,
   - and the downstream derived state that depends on that persistence.

3. **Synthetic/unit tests are necessary but not sufficient for closure.**
   If a task claims to improve real behavior, acceptance should include at least one validation path against realistic operating conditions. Otherwise a fixture can accidentally encode unrealistic preconditions and let a broken workflow pass.

4. **Truth alignment matters more than surface coherence.**
   If observable behavior, boundary responses, and persisted truth disagree, the task has failed acceptance. DoneGate should encourage operators to record this explicitly as a deviation or failed verification, not as an informal note.

## Cut for v0.1

- Full PM system behavior.
- Fancy dashboards or hosted web UI.
- Broad automation beyond explicit tools and hook entrypoints.
- Deep CI-provider-specific integrations.
- Team management, auth, permissions, and approval workflows.

## Positioning statement

`DoneGate MCP prevents AI-assisted tasks from being marked done before verification passes, docs are synced, and changed specs are revalidated.`

## Open-source pitch

DoneGate MCP is for teams that already have code generation and automation, but do not yet have a trustworthy definition of done.

## Tagline options

- `Not done until it passes the gate.`
- `A delivery gate for AI-assisted software work.`
- `Make done mean verified.`
