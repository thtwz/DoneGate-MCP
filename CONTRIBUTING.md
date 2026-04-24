# Contributing to DoneGate

Thanks for your interest in contributing.

DoneGate is intentionally small and opinionated. The best contributions make the delivery gate clearer, more reliable, and easier to adopt without turning the project into a full project-management platform.

## Ways to contribute

- Fix lifecycle bugs or edge cases
- Improve CLI ergonomics and error messages
- Expand tests around gating behavior
- Improve MCP tool schemas and integration docs
- Improve setup guides, examples, and end-to-end docs
- Propose carefully scoped features that strengthen the definition of done

## Before you start

Please align with the core product shape:

- DoneGate is a delivery quality gate, not a general PM system
- The CLI is the primary stable interface
- MCP support exists for orchestration, not as the only way to use the project
- Local-first, file-backed state is a feature, not a temporary shortcut
- Verification, documentation, and revalidation facts should stay explicit and testable

If a change expands scope significantly, open an issue or start a discussion before investing in a large patch.

## Development setup

```bash
cd /path/to/DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pip install -e .[test]
```

Optional MCP dependency:

```bash
pip install "mcp>=1.9.0"
```

## Run checks

Run the test suite:

```bash
PYTHONPATH=src pytest -q
```

If you change CLI behavior, lifecycle logic, or read-model generation, please add or update tests in `tests/`.

## Contribution guidelines

- Keep changes focused and small where possible
- Preserve backward compatibility unless a breaking change is clearly intentional
- Prefer explicit domain facts over hidden lifecycle magic
- Update docs when user-facing behavior changes
- Do not add large new subsystems without a strong product reason

## Good pull requests include

- A short explanation of the problem
- A concise summary of the solution
- Tests that cover the changed behavior
- Updated docs or examples when the workflow changes

## Feature direction

The strongest future contributions are likely in these areas:

- Better hook and CI integration examples
- Better MCP interoperability
- Stronger auditability and evidence recording
- More ergonomic progress and stale-work reporting
- Safer spec-drift and revalidation workflows

Less likely to be accepted without prior discussion:

- Turning the project into a hosted service
- Replacing the local-first model with a database-first design
- Building a broad PM interface or general issue tracker
- Adding automation that bypasses explicit delivery evidence

## Code of conduct

Be respectful, specific, and constructive. Assume good intent, and optimize for clarity over volume.

## Licensing note

This repository is licensed under Apache-2.0. By intentionally submitting a contribution for inclusion, you agree that your contribution will be licensed under the same terms.
