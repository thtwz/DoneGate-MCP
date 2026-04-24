# DoneGate

[![Test](https://img.shields.io/github/actions/workflow/status/thtwz/DoneGate/test.yml?branch=main&label=test)](https://github.com/thtwz/DoneGate/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/thtwz/DoneGate)](https://github.com/thtwz/DoneGate/blob/main/LICENSE)
[![Package](https://img.shields.io/badge/package-not%20published-lightgrey)](https://github.com/thtwz/DoneGate/releases)

[中文文档 / Chinese README](README.zh-CN.md)

DoneGate is a local-first delivery control layer for AI-assisted software work.

It gives repositories a stricter definition of done:
- a task is not done until verification passes
- documentation sync is recorded
- required docs and artifacts exist
- spec drift reopens stale work
- hooks, CLI flows, and MCP-driven agents all enforce the same rules

## Project Background

AI coding tools make it easy to produce changes quickly, but they do not automatically give teams a trustworthy delivery workflow.

In practice, the same problems keep showing up:
- code is declared finished before tests or manual verification are complete
- docs are assumed to be updated but no one records that fact
- a spec changes after work is marked complete and the repository has no reliable way to reopen that work
- local hooks, CI checks, and agent tools each invent their own rule set

DoneGate exists to solve that gap with a lightweight, file-backed control plane that works in local repos first and can be called from CLI, git hooks, CI wrappers, Hermes MCP, or Codex plugin integrations.

## Goals

DoneGate is designed to:
- make delivery state explicit instead of conversational
- keep task lifecycle, verification, doc sync, and spec drift in one shared model
- let agents use the same gate humans use
- stay easy to install from a git checkout without requiring a hosted backend
- support worktree-heavy, branch-heavy agent workflows

DoneGate is intentionally not trying to be:
- a hosted project management system
- a multi-user lock manager
- a PR platform replacement
- a full background daemon platform

## What You Get

- A hook-friendly CLI for local workflows and CI
- A file-backed state model under `.donegate-mcp/`
- MCP tool support for agent orchestration
- Self-test execution with artifact logging
- Spec hash tracking and drift detection
- Deviation logging for intentional exceptions
- Advisory review records for architect-style outcome gaps
- Follow-up task generation from review findings
- Dashboard, plan, progress, and supervision read models
- Branch-scoped active task context
- Task scope ownership and coverage checks
- Policy-aware hooks for `pre-commit` and `pre-push`
- Worktree-safe bootstrap and repo-local onboarding assets

## Quick Links

- [Startup guide](docs/startup-guide.md)
- [End-to-end demo](docs/end-to-end-demo.md)
- [Repository metadata](docs/repository-metadata.md)
- [Contributing](CONTRIBUTING.md)
- [Release checklist](docs/release-checklist.md)
- [v0.4.0 release notes](docs/release-notes-v0.4.0.md)
- [Hermes example config](examples/hermes-mcp-config.yaml)

## Human Quick Start

### 1. Install DoneGate

```bash
git clone https://github.com/thtwz/DoneGate.git
cd DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[mcp,test]"
```

After installation:

```bash
donegate-mcp --help
```

### 2. Bootstrap a target repository

From the repository you want DoneGate to supervise:

```bash
donegate-mcp bootstrap --project-name my-project --repo-root .
```

This does four important things:
- initializes `.donegate-mcp`
- installs managed `pre-commit` and `pre-push` hooks
- resolves the correct git hooks path even in linked worktrees
- generates repo-local onboarding assets

Bootstrap writes:
- `.donegate-mcp/env.sh`
- `.donegate-mcp/onboarding/codex.md`
- `.donegate-mcp/onboarding/hermes-mcp.yaml`

### 3. Create and activate a task

```bash
donegate-mcp --data-root .donegate-mcp --json task create \
  --title "Ship gate" \
  --spec-ref docs/spec.md \
  --verification-mode self-test \
  --test-command "pytest -q" \
  --required-doc-ref docs/plan.md \
  --required-artifact reports/pytest.txt \
  --plan-node-id phase-1-task-a

donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
donegate-mcp --data-root .donegate-mcp --json task active --repo-root .
```

### 4. Use the gate during implementation

```bash
donegate-mcp --data-root .donegate-mcp task start TASK-0001
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json task self-test TASK-0001 --workdir .
donegate-mcp --data-root .donegate-mcp task doc-sync TASK-0001 --result synced --ref docs/plan.md
donegate-mcp --data-root .donegate-mcp --json task done TASK-0001
# later, if the task must be reopened for more work:
donegate-mcp --data-root .donegate-mcp --json task reopen TASK-0001
```

## Typical flow

1. Create a task from a spec or ticket.
2. Start work and submit it for verification.
3. Record verification or run the configured self-test.
4. Record documentation sync.
5. Close the task only when the gate passes.
6. If completed work must resume, use `task reopen` to move it back into an active non-done state.
7. Refresh spec hashes when requirements change and revalidate stale work.

## Advisory Review

DoneGate v0.4 adds an advisory review layer for the gap that pure verification cannot catch: work that passes its formal acceptance path but still misses the real user need.

This layer is intentionally advisory:
- it does not block `done`
- it does not replace verification or doc sync
- it records architect-style findings as explicit state
- it can convert findings into follow-up tasks

Advisory review requests are created automatically when a task is submitted for verification and again before it reaches `done`.

```bash
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json review list --task-id TASK-0001 --include-findings
```

A human or host LLM can record a review finding:

```bash
donegate-mcp --data-root .donegate-mcp --json task review TASK-0001 \
  --checkpoint manual \
  --provider manual \
  --summary "The literal flow passes, but frequent users still need a faster path." \
  --recommendation proceed_with_followups \
  --finding-json '{"dimension":"outcome_gap","severity":"medium","title":"Missing fast path","details":"The accepted workflow still takes too many steps for repeat users.","recommended_action":"Add a shortcut workflow.","suggested_task_title":"Add fast path","suggested_task_summary":"Reduce the number of steps for frequent users."}'
```

Then turn a useful finding into tracked work:

```bash
donegate-mcp --data-root .donegate-mcp --json task create-from-finding FINDING-1234abcd
donegate-mcp --data-root .donegate-mcp --json dashboard --include-tasks
```

MCP hosts get the same surface through `task_review`, `review_list`, `review_disposition`, and `task_create_from_finding`. In Codex, the recommended pattern is for the DoneGate skill to inspect pending advisory requests, run an architect-style review in the host, and call the MCP tool to record normalized findings.

## LLM / Agent Quickstart From Git URL

If you give an LLM only this repository URL, the intended zero-context bootstrap path is:

```bash
git clone https://github.com/thtwz/DoneGate.git
cd DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[mcp,test]"
```

Then, in the target repository the model should supervise:

```bash
donegate-mcp bootstrap --project-name my-project --repo-root .
source .donegate-mcp/env.sh
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent codex
```

If no active task exists yet, the model should:

```bash
donegate-mcp --data-root .donegate-mcp --json task list --limit 10
donegate-mcp --data-root .donegate-mcp --json task create \
  --title "Describe the current work" \
  --spec-ref docs/spec.md
donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
```

From there, the model has enough information to use all major surfaces:
- CLI commands through `donegate-mcp`
- local hooks through the files installed by `bootstrap`
- supervision and onboarding through `--json supervision` and `--json onboarding`
- Hermes MCP through `.donegate-mcp/onboarding/hermes-mcp.yaml`
- Codex integration through `.donegate-mcp/onboarding/codex.md` and the plugin setup in the startup guide

### LLM Operating Contract

An LLM integrating DoneGate should follow this sequence:

1. Clone and install DoneGate from this repository.
2. Run `donegate-mcp bootstrap --project-name ... --repo-root .` inside the target repository.
3. Read `donegate-mcp --json onboarding --repo-root . --agent <codex|hermes>`.
4. Ensure a branch-scoped active task exists before editing code.
5. Use `donegate-mcp --json supervision --repo-root .` before commits or pushes.
6. Record verification and doc sync before calling a task done.
7. Inspect advisory reviews before closing substantial work, and convert accepted outcome gaps into follow-up tasks.

## Integrations

### CLI

The CLI is the primary stable interface for local adoption and CI wrappers.

Useful read commands:

```bash
donegate-mcp --data-root .donegate-mcp --json dashboard --include-tasks --limit 20
donegate-mcp --data-root .donegate-mcp --json progress
donegate-mcp --data-root .donegate-mcp --json plan
donegate-mcp --data-root .donegate-mcp --json supervision --repo-root .
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent codex
```

### Hooks

Managed hooks use the same supervision model as the CLI.

Current policy behavior:
- `pre-commit` blocks on `needs_task`, `task_mismatch`, and `needs_revalidation`
- `pre-commit` warns on `stale_verification` and `stale_docs`
- `pre-push` blocks on any status stronger than `tracked`

### Hermes MCP

Use the generated onboarding asset or the example config:
- `.donegate-mcp/onboarding/hermes-mcp.yaml`
- `examples/hermes-mcp-config.yaml`

The repository-local onboarding asset is the preferred source because it is generated with the correct local interpreter and `data_root`.

### Codex Plugin

DoneGate can also be exposed to Codex as a local plugin. The plugin layer should stay thin and point at the same MCP server, not reimplement delivery rules.

When Codex launches DoneGate as a shared plugin, make sure the Codex process inherits the repo-local environment from `.donegate-mcp/env.sh`. That file exports `DONEGATE_MCP_ROOT` and `DONEGATE_MCP_REPO_ROOT`, which let shared MCP sessions target the supervised repository instead of the plugin installation checkout.

If the host cannot inherit that environment, MCP calls should pass `repo_root` explicitly.

See:
- [Startup guide](docs/startup-guide.md)
- `.donegate-mcp/onboarding/codex.md`

## Acceptance guidance from real usage

When a task changes observable system behavior, do not treat any single signal as enough evidence to call it done. Real acceptance should verify the full closed loop:

- the externally observable outcome,
- the operation result at the system boundary,
- the persisted source-of-truth state,
- and the downstream derived state that depends on that persistence.

If any of those disagree, the task is not actually done and should be captured as failed verification or a deviation.

## Release notes

## Active Task Context

DoneGate stores a repo-local active task context and, when `--repo-root` points to a git repository, binds tasks to the current branch.

```bash
donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
donegate-mcp --data-root .donegate-mcp --json task active --repo-root .
donegate-mcp --data-root .donegate-mcp task clear-active --repo-root .
```

This makes branch-heavy agent workflows much safer in worktrees and parallel sessions.

## Supervision States

```bash
donegate-mcp --data-root .donegate-mcp --json supervision --repo-root .
```

The supervision read model can report:
- `clean`
- `needs_task`
- `task_mismatch`
- `needs_revalidation`
- `stale_verification`
- `stale_docs`
- `tracked`

When task scopes are configured, supervision also returns:
- `covered_files`
- `uncovered_files`
- `policy.pre_commit`
- `policy.pre_push`

## Files And State

DoneGate stores repo-local state under `.donegate-mcp/`, including:
- `project.json`
- `plan.json`
- `progress.json`
- `session.json`
- `supervision.json`
- `deviations.jsonl`
- `tasks/`
- `events/`
- `review_runs/`
- `review_findings/`
- `artifacts/`
- `onboarding/`

## Recommended Reading Order

For humans:
1. This README
2. [Startup guide](docs/startup-guide.md)
3. [End-to-end demo](docs/end-to-end-demo.md)

For LLMs and agent systems:
1. This README
2. `donegate-mcp --json onboarding --repo-root . --agent codex`
3. [Startup guide](docs/startup-guide.md)
4. `.donegate-mcp/onboarding/codex.md` or `.donegate-mcp/onboarding/hermes-mcp.yaml`

## Development

Run the test suite with:

```bash
PYTHONPATH=src pytest -q
```

## License

DoneGate is licensed under [Apache-2.0](LICENSE).
