# DoneGate MCP startup guide

## 1. Local development

```bash
cd /path/to/DoneGate-MCP
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

## 2. Initialize state in a target project

From the target project root:

```bash
donegate-mcp --data-root .donegate-mcp init --project-name my-project
```

## 3. Recommended hook wiring

```bash
cp /path/to/DoneGate-MCP/scripts/pre-commit.sh .git/hooks/pre-commit
cp /path/to/DoneGate-MCP/scripts/pre-push.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
```

Then export variables in your shell or CI job:

```bash
source /path/to/DoneGate-MCP/examples/donegate-mcp.env.example
export TASK_ID=TASK-0001
export SPEC_REF=docs/spec.md
```

## 4. MCP integration

Use `examples/hermes-mcp-config.yaml` as a starting point. In practice, prefer packaging DoneGate MCP into the Python environment that Hermes uses, then point `mcp_servers.donegate_mcp.command` to that interpreter.

## 5. Codex plugin integration

If you want to expose DoneGate MCP inside Codex as a local plugin, keep the plugin layer thin and point it at the same MCP entrypoint:

- Register the plugin in `~/.agents/plugins/marketplace.json`
- Put the plugin manifest at `~/plugins/donegate-mcp/.codex-plugin/plugin.json`
- Set `mcpServers` in that manifest to a relative config path such as `./.mcp.json`
- Put the actual MCP command in `~/plugins/donegate-mcp/.mcp.json`
- Point that command at the Python environment that has `donegate_mcp` and `mcp` installed

This keeps Codex-specific wiring separate from the delivery-gate core. The plugin should act as a thin adapter over the existing DoneGate MCP server, not a second implementation of delivery rules.

## 6. Operational note

For local adoption, the CLI is the primary stable interface. The MCP adapter is there for agent orchestration, but hook and CI integration should call the CLI directly.

## 7. Naming note

The public project name is `DoneGate MCP`. The CLI and Python module path are `donegate-mcp` and `donegate_mcp`.
