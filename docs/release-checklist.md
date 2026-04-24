# DoneGate release checklist

Use this checklist before tagging or publishing a release.

## Product and docs

- README reflects the current positioning and CLI examples
- Startup guide still works end to end
- End-to-end demo still matches the current command surface
- Product notes still reflect the intended scope
- Any new user-facing behavior is documented

## Packaging and naming

- `pyproject.toml` version is correct
- Package name and CLI entrypoints are correct
- The public brand is consistently `DoneGate`
- Python module and CLI names are consistently `donegate_mcp` / `donegate-mcp`

## Quality gate behavior

- Task close rules still require verification, docs, and required artifacts
- Spec drift still marks stale work for revalidation
- Deviation logging still works
- Lifecycle projection and dashboard behavior are still coherent

## Verification

- Run `PYTHONPATH=src pytest -q`
- Smoke-test the branded CLI with `donegate-mcp --help`
- Run a quick local flow: `init`, `task create`, `task start`, `task submit`, `task done`
- If self-test behavior changed, run at least one happy-path self-test command

## Release hygiene

- Decide whether the release should also update examples or docs
- Confirm whether a `LICENSE` file is present and correct
- Tag only after docs and test results match what you are publishing

## Nice-to-have before public launch

- Add a top-level `LICENSE`
- Add issue and pull request templates
- Add a CI workflow that runs tests on push and pull request
- Add badges to the README once CI and package publishing are live
