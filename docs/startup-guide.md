# DoneGate startup guide

For project background and the agent-oriented overview, start with [README.md](../README.md). If you prefer Chinese, use [README.zh-CN.md](../README.zh-CN.md).

## 1. Local development

```bash
cd /path/to/DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

For optional MCP support:

```bash
pip install "mcp>=1.9.0"
```

After installation, the primary CLI is:

```bash
donegate-mcp --help
```

## 2. Bootstrap a target project

From the target project root, prefer a single bootstrap command:

```bash
donegate-mcp bootstrap --project-name my-project --repo-root .
```

This will:
- initialize `.donegate-mcp`
- install managed `pre-commit` and `pre-push` hooks into the resolved git hooks directory
- keep unknown existing hooks untouched and report them as skipped
- generate `.donegate-mcp/env.sh`
- generate `.donegate-mcp/onboarding/codex.md`
- generate `.donegate-mcp/onboarding/hermes-mcp.yaml`

The hook installation path is worktree-safe, so linked git worktrees do not need a separate setup flow.

## 3. Manual initialization path

If you want to initialize state without installing hooks, use:

```bash
donegate-mcp --data-root .donegate-mcp init --project-name my-project
```

## 4. Recommended manual hook wiring

```bash
cp /path/to/DoneGate/scripts/pre-commit.sh .git/hooks/pre-commit
cp /path/to/DoneGate/scripts/pre-push.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
```

Then export variables in your shell or CI job:

```bash
source /path/to/DoneGate/examples/donegate-mcp.env.example
export TASK_ID=TASK-0001
export SPEC_REF=docs/spec.md
```

For local repository work, you can also set the repo-local active task instead of exporting `TASK_ID` every time:

```bash
donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
donegate-mcp --data-root .donegate-mcp --json task active --repo-root .
```

The managed `pre-commit` and `pre-push` hooks will use the active task automatically when `TASK_ID` is absent.

When `--repo-root .` points at a git repository, DoneGate records the active task against the current branch, so different branches can carry different active task bindings.

You can also ask DoneGate to inspect whether the repository currently has work that is not tied to an active task:

```bash
donegate-mcp --data-root .donegate-mcp --json supervision --repo-root .
```

If you already know which parts of the repository a task should own, declare them up front:

```bash
donegate-mcp --data-root .donegate-mcp --json task create \
  --title "branch context follow-up" \
  --spec-ref docs/spec.md \
  --owned-path src/donegate_mcp \
  --owned-path tests
```

With task scopes in place, supervision can tell you whether the active task fully covers the current diff or whether it has drifted into `task_mismatch`.

The richer supervision statuses are:
- `needs_task`
- `task_mismatch`
- `needs_revalidation`
- `stale_verification`
- `stale_docs`
- `tracked`

Managed hook behavior now uses those statuses before self-test:
- `pre-commit` blocks on `needs_task`, `task_mismatch`, and `needs_revalidation`
- `pre-commit` warns but continues on `stale_verification` and `stale_docs`
- `pre-push` blocks on any status stronger than `tracked`

## 5. Onboarding command

After bootstrap, ask DoneGate for repo-local agent guidance:

```bash
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent codex
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent hermes
```

The response includes the current branch, any branch-bound active task, the generated onboarding file paths, and the next recommended command if work still needs to be attached to a task.

## 6. Advisory review

Advisory review helps agents catch outcome gaps that can pass verification while still missing the real user need. It is advisory in v0.4: findings do not block `done`, but they stay visible and can be converted into follow-up tasks.

DoneGate creates review requests when a task is submitted for verification and again before completion:

```bash
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json review list --task-id TASK-0001 --include-findings
```

Record a finding from a human, Codex skill, or other host reviewer:

```bash
donegate-mcp --data-root .donegate-mcp --json task review TASK-0001 \
  --checkpoint manual \
  --provider manual \
  --summary "The implementation passes the literal gate but leaves a user-value gap." \
  --recommendation proceed_with_followups \
  --finding-json '{"dimension":"outcome_gap","severity":"medium","title":"Missing fast path","details":"Frequent users still need too many steps.","recommended_action":"Add a shortcut flow.","suggested_task_title":"Add fast path","suggested_task_summary":"Reduce repeated-user steps."}'
```

Create tracked follow-up work from the finding:

```bash
donegate-mcp --data-root .donegate-mcp --json task create-from-finding FINDING-1234abcd
donegate-mcp --data-root .donegate-mcp --json review disposition FINDING-1234abcd --to accepted
```

MCP clients should use the matching tools: `task_review`, `review_list`, `review_disposition`, and `task_create_from_finding`.

## 7. MCP integration

### Hermes native MCP

Use `examples/hermes-mcp-config.yaml` as a starting point.
If Hermes runs DoneGate from the delivery checkout, the typical setup is:

```yaml
mcp_servers:
  donegate_mcp:
    command: "/Users/mac/workspace/projects/DoneGate/.venv/bin/donegate-mcp-serve"
    args: []
    env:
      DONEGATE_MCP_DATA_ROOT: "/absolute/path/to/.donegate-mcp"
    timeout: 120
    connect_timeout: 30
```

After changing the code, update the environment Hermes uses by reinstalling the editable package in that venv:

```bash
cd /Users/mac/workspace/projects/DoneGate
/Users/mac/workspace/projects/DoneGate/.venv/bin/pip install -e '.[mcp,test]'
```

If you use Hermes skills, load the `donegate-mcp-governor` skill before governed work so the operator flow stays aligned with DoneGate facts instead of chat narration.

### Trae / plugin-style MCP clients

For Trae-style plugin configs, point the plugin at the same `donegate-mcp-serve` entrypoint and data root:

```json
{
  "mcpServers": {
    "donegate_mcp": {
      "command": "/Users/mac/workspace/projects/DoneGate/.venv/bin/donegate-mcp-serve",
      "args": [],
      "env": {
        "DONEGATE_MCP_DATA_ROOT": "/absolute/path/to/.donegate-mcp"
      }
    }
  }
}
```

## 8. Codex plugin integration

If you want to expose DoneGate inside Codex as a local plugin, keep the plugin layer thin and point it at the same MCP entrypoint:

- Register the plugin in `~/.agents/plugins/marketplace.json`
- Put the plugin manifest at `~/plugins/donegate/.codex-plugin/plugin.json`
- Set `mcpServers` in that manifest to a relative config path such as `./.mcp.json`
- Put the actual MCP command in `~/plugins/donegate/.mcp.json`
- Point that command at the Python environment that has `donegate_mcp` and `mcp` installed

This keeps Codex-specific wiring separate from the delivery-gate core. The plugin should act as a thin adapter over DoneGate's MCP server, not a second implementation of delivery rules.

If Codex runs DoneGate as a shared plugin, prefer launching Codex from a shell that already sourced `.donegate-mcp/env.sh` in the target repository. That file exports `DONEGATE_MCP_ROOT` and `DONEGATE_MCP_REPO_ROOT`, which allow the shared MCP process to default to the supervised repository instead of the plugin checkout.

If the host process cannot inherit that environment, pass `repo_root` explicitly in DoneGate tool calls.

## 9. Operational note

For local adoption, the CLI is the primary stable interface. The MCP adapter is there for agent orchestration, but hook and CI integration should call the CLI directly.

## 10. Naming note

The public project name is `DoneGate`. The CLI and Python module path remain `donegate-mcp` and `donegate_mcp` for compatibility.
