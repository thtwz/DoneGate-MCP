# DoneGate end-to-end demo

This walkthrough shows the full spec-driven loop:
- create task from spec
- run self-test
- sync docs
- close task
- modify spec
- detect drift
- record deviation
- inspect progress

## Setup

```bash
cd /path/to/DoneGate
mkdir -p /tmp/delivery-demo/docs /tmp/delivery-demo/reports
printf 'version 1\n' >/tmp/delivery-demo/docs/spec.md
printf 'plan\n' >/tmp/delivery-demo/docs/plan.md
printf 'pytest ok\n' >/tmp/delivery-demo/reports/pytest.txt
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp init --project-name demo
```

## Create a task

```bash
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json task create \
  --title "implement gate" \
  --spec-ref /tmp/delivery-demo/docs/spec.md \
  --verification-mode self-test \
  --test-command "python3 -c 'print(42)'" \
  --required-doc-ref /tmp/delivery-demo/docs/plan.md \
  --required-artifact /tmp/delivery-demo/reports/pytest.txt \
  --plan-node-id phase-1-gate
```

## Drive it to done

```bash
TASK_ID=TASK-0001
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp task transition $TASK_ID --to ready
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp task start $TASK_ID
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp task submit $TASK_ID
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json task self-test $TASK_ID --workdir /tmp/delivery-demo
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp task doc-sync $TASK_ID --result synced --ref /tmp/delivery-demo/docs/plan.md
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json task done $TASK_ID
# later, if new work invalidates the closure:
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json task reopen $TASK_ID
```

## Change the spec and detect drift

```bash
printf 'version 2\n' >/tmp/delivery-demo/docs/spec.md
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json spec refresh --spec-ref /tmp/delivery-demo/docs/spec.md --reason "design updated"
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json progress
```

Expected result:
- task shows `needs_revalidation=true`
- progress includes the task under `stale_tasks`

## Record a deviation

```bash
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp deviation add $TASK_ID \
  --summary "temporary workaround" \
  --details "using compatibility path until final API lands"
donegate-mcp --data-root /tmp/delivery-demo/.donegate-mcp --json deviation list
```

## Inspect state files

```bash
cat /tmp/delivery-demo/.donegate-mcp/plan.json
cat /tmp/delivery-demo/.donegate-mcp/progress.json
cat /tmp/delivery-demo/.donegate-mcp/deviations.jsonl
```

## Acceptance check for behavior-changing workflows

Use this mental model whenever a task changes observable system behavior, not just internal policy.
A task is **not** accepted because one signal looks good or one fixture passes.

Verify the full closed loop instead:

1. **Externally observable outcome**
   - Did the behavior visible outside the component actually change the way the task promised?
2. **Boundary result**
   - Did the operation at the relevant system boundary report success rather than a hidden failure?
3. **Persisted source-of-truth state**
   - Did the backing state actually update?
4. **Downstream derived state**
   - Did the dependent summaries, views, or projections that rely on that persistence also change?

If any of those disagree, treat the task as **not done** and record that with either:
- `task verify <task-id> --result failed ...`
- or `deviation add <task-id> ...`

This is the guardrail that prevents one-layer success signals from passing acceptance when the system truth has not actually changed.
