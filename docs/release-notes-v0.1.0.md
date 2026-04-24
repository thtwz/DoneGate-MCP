# DoneGate v0.1.0

Initial public release of DoneGate.

## Highlights

- Introduces a lightweight delivery gate for AI-assisted software work
- Adds a hook-friendly CLI for local workflows and CI
- Supports MCP-based orchestration on top of the same core lifecycle
- Enforces task completion rules around verification, doc sync, required docs, and required artifacts
- Tracks spec hashes and marks stale work for revalidation
- Records deviations for intentional temporary exceptions
- Generates plan and progress read models from file-backed local state

## Included in this release

- Core task lifecycle and gate enforcement
- CLI commands for task creation, transitions, verification, doc sync, block/unblock, and completion
- Self-test execution with artifact capture
- Spec refresh and stale-task detection
- Dashboard, plan, and progress outputs
- Startup guide and end-to-end demo docs
- Open-source project scaffolding: Apache-2.0 license, contribution guide, issue templates, PR template, and CI workflow

## Notes

- Public brand: `DoneGate`
- Python package name: `donegate-mcp`
- Python module path: `donegate_mcp`

## Validation

- Local test suite passing at release time
- GitHub Actions workflow added for push and pull request validation
