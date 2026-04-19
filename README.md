# DoneGate MCP

[![Test](https://img.shields.io/github/actions/workflow/status/thtwz/DoneGate-MCP/test.yml?branch=main&label=test)](https://github.com/thtwz/DoneGate-MCP/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/thtwz/DoneGate-MCP)](https://github.com/thtwz/DoneGate-MCP/blob/main/LICENSE)
[![Package](https://img.shields.io/badge/package-not%20published-lightgrey)](https://github.com/thtwz/DoneGate-MCP/releases)

DoneGate MCP is a lightweight quality gate for AI-assisted software delivery.

It prevents tasks from being marked done until verification passes, docs are synced, required artifacts exist, and changed specs have been revalidated. It is designed for local-first workflows, git hooks, CI wrappers, and MCP-based agent orchestration.

## Why it exists

AI can produce code quickly, but teams still need a trustworthy definition of done.

DoneGate MCP adds a small, explicit delivery layer on top of the tools you already use:
- tasks move through a real lifecycle instead of ad hoc status updates
- verification and documentation become recorded facts, not assumptions
- spec changes can reopen previously finished work
- hooks, CI, and agents can all enforce the same gate

## Core rule

A task cannot become `done` unless all of the following are true:
- verification status is `passed`
- doc sync status is `synced`
- every configured `required_doc_ref` exists
- every configured `required_artifact` exists
- the task is not marked `needs_revalidation`

## What it includes

- A hook-friendly CLI for local workflows and CI
- A file-backed state model under `.donegate-mcp/`
- MCP tool support for agent orchestration
- Self-test execution with artifact logging
- Spec hash tracking and drift detection
- Deviation logging for intentional temporary exceptions
- Dashboard, plan, and progress read models

## Who it is for

- Teams shipping with AI coding agents
- Repositories that want a stricter definition of done
- Local-first workflows that do not want a heavy external control plane
- Tool builders who want a delivery gate they can call from hooks, CI, or MCP

## Quick links

- `docs/startup-guide.md`
- `docs/end-to-end-demo.md`
- `docs/product-notes.md`
- `docs/release-notes-v0.1.0.md`
- `docs/repository-metadata.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `docs/release-checklist.md`
- `examples/donegate-mcp.env.example`
- `examples/hermes-mcp-config.yaml`

## Installation

```bash
git clone https://github.com/thtwz/DoneGate-MCP.git
cd DoneGate-MCP
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

For optional MCP support:

```bash
pip install "mcp>=1.9.0"
```

The CLI and Python module path are both named `donegate_mcp` / `donegate-mcp`.

## CLI quick start

```bash
donegate-mcp --data-root .donegate-mcp init --project-name demo

donegate-mcp --data-root .donegate-mcp --json task create \
  --title "Ship gate" \
  --spec-ref docs/spec.md \
  --verification-mode self-test \
  --test-command "pytest -q" \
  --required-doc-ref docs/plan.md \
  --required-artifact reports/pytest.txt \
  --plan-node-id phase-1-task-a

donegate-mcp --data-root .donegate-mcp task transition TASK-0001 --to ready
donegate-mcp --data-root .donegate-mcp task start TASK-0001
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json task self-test TASK-0001 --workdir .
donegate-mcp --data-root .donegate-mcp task doc-sync TASK-0001 --result synced --ref docs/plan.md
donegate-mcp --data-root .donegate-mcp --json task done TASK-0001
```

## Typical flow

1. Create a task from a spec or ticket.
2. Start work and submit it for verification.
3. Record verification or run the configured self-test.
4. Record documentation sync.
5. Close the task only when the gate passes.
6. Refresh spec hashes when requirements change and revalidate stale work.

## Spec drift workflow

```bash
donegate-mcp --data-root .donegate-mcp --json spec refresh --spec-ref docs/spec.md --reason "design changed"
donegate-mcp --data-root .donegate-mcp --json progress
```

## Deviation workflow

```bash
donegate-mcp --data-root .donegate-mcp deviation add TASK-0001 \
  --summary "temporary workaround" \
  --details "using fallback behavior until API is ready"

donegate-mcp --data-root .donegate-mcp --json deviation list
```

## Hook examples

```bash
TASK_ID=TASK-0001 DONEGATE_MCP_ROOT=.donegate-mcp DONEGATE_MCP_WORKDIR=$(pwd) scripts/pre-commit.sh
TASK_ID=TASK-0001 DONEGATE_MCP_ROOT=.donegate-mcp DONEGATE_MCP_WORKDIR=$(pwd) scripts/pre-push.sh
TASK_ID=TASK-0001 DONEGATE_MCP_ROOT=.donegate-mcp DOC_REF=docs/plan.md scripts/post-doc-sync.sh synced
SPEC_REF=docs/spec.md DONEGATE_MCP_ROOT=.donegate-mcp scripts/post-spec-change.sh "design changed"
```

## State files

- `.donegate-mcp/plan.json`
- `.donegate-mcp/progress.json`
- `.donegate-mcp/deviations.jsonl`

## Current status

DoneGate MCP is already a working vertical slice. It includes executable self-test gates, artifact and doc validation, lifecycle projection, spec drift detection, deviation logging, and enough docs/examples to wire into a real repository today.

## Release notes

The initial public release notes live in [docs/release-notes-v0.1.0.md](docs/release-notes-v0.1.0.md).

## Development

Run the test suite with:

```bash
PYTHONPATH=src pytest -q
```

## Contributing

Contributions are welcome. If you want to propose a feature, tighten the lifecycle rules, improve the MCP surface, or sharpen the docs, start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Release checklist

Before publishing a new version, walk through [docs/release-checklist.md](docs/release-checklist.md).

## License

DoneGate MCP is licensed under [Apache-2.0](LICENSE).
