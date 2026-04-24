# DoneGate

[English README](README.md)

DoneGate 是一个面向 AI 辅助研发场景的、本地优先的交付控制层。

它解决的问题不是“怎么写代码”，而是“什么时候这项工作才真的算完成”。

## 项目背景

AI 编码工具让代码产出变快了，但交付纪律并不会自动出现。真实仓库里最常见的问题通常是：
- 任务在验证没有完成前就被宣布 done
- 文档是否同步只停留在口头假设
- 规格变了，但历史完成任务没有被可靠 reopen
- 本地 hook、CI、agent 各自维护一套不一致的规则

DoneGate 的目标就是给这些流程加上一层轻量、明确、可复用的“交付门禁”。

## 核心目标

DoneGate 主要想做到：
- 用显式任务状态代替模糊的沟通状态
- 把 verification、doc sync、spec drift 放进同一套模型
- 让人类和 AI agent 使用同一套 done 规则
- 保持本地优先，不依赖托管控制平面
- 能从 CLI、git hooks、CI、Hermes MCP、Codex plugin 一起接入
- 用建议型架构审查记录“验收通过但没有真正满足用户需求”的缺口
- 把有价值的审查发现直接拆成可跟踪的后续任务

## DoneGate 的核心规则

一个任务不能被标记为 `done`，除非这些条件同时满足：
- verification status = `passed`
- doc sync status = `synced`
- 所有 `required_doc_ref` 都存在
- 所有 `required_artifact` 都存在
- 任务没有被标记成 `needs_revalidation`

## 给人类的快速上手

### 1. 安装 DoneGate

```bash
git clone https://github.com/thtwz/DoneGate.git
cd DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[mcp,test]"
```

### 2. 在目标仓库里 bootstrap

进入你想纳管的目标仓库后执行：

```bash
donegate-mcp bootstrap --project-name my-project --repo-root .
```

它会自动完成：
- 初始化 `.donegate-mcp`
- 安装 `pre-commit` / `pre-push`
- 在 linked git worktree 下解析正确的 hooks 路径
- 生成 repo-local onboarding 文件

生成的关键文件包括：
- `.donegate-mcp/env.sh`
- `.donegate-mcp/onboarding/codex.md`
- `.donegate-mcp/onboarding/hermes-mcp.yaml`

### 3. 创建并激活任务

```bash
donegate-mcp --data-root .donegate-mcp --json task create \
  --title "实现当前需求" \
  --spec-ref docs/spec.md

donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
```

### 4. 开发期间使用门禁

```bash
donegate-mcp --data-root .donegate-mcp task start TASK-0001
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json task self-test TASK-0001 --workdir .
donegate-mcp --data-root .donegate-mcp task doc-sync TASK-0001 --result synced --ref docs/plan.md
donegate-mcp --data-root .donegate-mcp --json task done TASK-0001
```

## 建议型架构审查

v0.4 新增了 advisory review 层，用来兜住传统 verification 很难发现的问题：功能虽然通过验收，但仍然没有满足真实用户意图。

这一层默认是建议型，不是硬门禁：
- 不阻断 `done`
- 不替代 verification 或 doc sync
- 把架构师视角的发现记录成结构化状态
- 支持把发现一键转成 follow-up task

任务进入 `submit` 和 `done` 前会自动留下 advisory review request：

```bash
donegate-mcp --data-root .donegate-mcp task submit TASK-0001
donegate-mcp --data-root .donegate-mcp --json review list --task-id TASK-0001 --include-findings
```

人类或宿主 LLM 可以把审查结论写回 DoneGate：

```bash
donegate-mcp --data-root .donegate-mcp --json task review TASK-0001 \
  --checkpoint manual \
  --provider manual \
  --summary "流程验收通过了，但高频用户仍然缺少快速路径。" \
  --recommendation proceed_with_followups \
  --finding-json '{"dimension":"outcome_gap","severity":"medium","title":"缺少快速路径","details":"已验收流程对重复使用者来说步骤仍然过多。","recommended_action":"增加快捷流程。","suggested_task_title":"增加快速路径","suggested_task_summary":"减少高频用户完成任务所需步骤。"}'
```

如果这个发现值得落地，就直接拆成任务：

```bash
donegate-mcp --data-root .donegate-mcp --json task create-from-finding FINDING-1234abcd
donegate-mcp --data-root .donegate-mcp --json dashboard --include-tasks
```

MCP 宿主可以使用同等能力：`task_review`、`review_list`、`review_disposition`、`task_create_from_finding`。在 Codex 里，推荐让 DoneGate skill 读取 pending advisory request，在宿主侧执行架构师视角审查，再把标准化 findings 写回 MCP。

## 给 LLM / Agent 的零上下文接入说明

如果你只把这个仓库的 git 地址给一个大模型，推荐它按下面顺序操作：

### 1. clone 并安装 DoneGate

```bash
git clone https://github.com/thtwz/DoneGate.git
cd DoneGate
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[mcp,test]"
```

### 2. 在目标仓库里启用 DoneGate

```bash
donegate-mcp bootstrap --project-name my-project --repo-root .
source .donegate-mcp/env.sh
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent codex
```

### 3. 确保当前分支有 active task

如果当前分支还没有任务绑定：

```bash
donegate-mcp --data-root .donegate-mcp --json task list --limit 10
donegate-mcp --data-root .donegate-mcp --json task create \
  --title "Describe the current work" \
  --spec-ref docs/spec.md
donegate-mcp --data-root .donegate-mcp task activate TASK-0001 --repo-root .
```

### 4. 使用所有主要功能

只靠这个仓库地址和 README，大模型就应该能顺着文档接通这些能力：
- CLI
- bootstrap + managed hooks
- branch-scoped active task
- supervision / onboarding JSON
- Hermes MCP
- Codex plugin

推荐模型遵循的操作顺序是：
1. 安装 DoneGate
2. 在目标仓库里运行 `bootstrap`
3. 读取 `onboarding`
4. 确认当前分支有 active task
5. 在 commit / push 前读取 `supervision`
6. 在 `done` 之前记录 verification 和 doc sync
7. 对重要任务检查 advisory review，把已接受的真实需求缺口拆成 follow-up task

## 主要集成方式

### CLI

最稳定的本地接口还是 CLI：

```bash
donegate-mcp --data-root .donegate-mcp --json dashboard --include-tasks --limit 20
donegate-mcp --data-root .donegate-mcp --json supervision --repo-root .
donegate-mcp --data-root .donegate-mcp --json onboarding --repo-root . --agent codex
```

### Hooks

`pre-commit` 和 `pre-push` 会使用同一套 supervision 状态：
- `pre-commit` 会 block `needs_task`、`task_mismatch`、`needs_revalidation`
- `pre-commit` 会 warn `stale_verification`、`stale_docs`
- `pre-push` 会 block 所有比 `tracked` 更严重的状态

### Hermes MCP

优先使用 bootstrap 后生成的：
- `.donegate-mcp/onboarding/hermes-mcp.yaml`

也可以参考：
- `examples/hermes-mcp-config.yaml`

### Codex Plugin

Codex 接入建议看：
- `.donegate-mcp/onboarding/codex.md`
- `docs/startup-guide.md`

如果 DoneGate 是以“共享插件”的方式被 Codex 启动，最好让 Codex 进程继承 `.donegate-mcp/env.sh` 导出的环境变量。这个文件会提供 `DONEGATE_MCP_ROOT` 和 `DONEGATE_MCP_REPO_ROOT`，这样共享 MCP 会话才能默认指向被纳管的目标仓库，而不是插件安装目录。

如果宿主进程不能继承这些环境变量，MCP 工具调用时就应该显式传 `repo_root`。

## Supervision 状态

```bash
donegate-mcp --data-root .donegate-mcp --json supervision --repo-root .
```

当前可能看到的状态包括：
- `clean`
- `needs_task`
- `task_mismatch`
- `needs_revalidation`
- `stale_verification`
- `stale_docs`
- `tracked`

如果任务配置了 scope，还会返回：
- `covered_files`
- `uncovered_files`
- `policy.pre_commit`
- `policy.pre_push`

## 建议阅读顺序

如果是人类开发者：
1. 本文档
2. [README.md](README.md)
3. [docs/startup-guide.md](docs/startup-guide.md)

如果是 LLM / agent：
1. [README.md](README.md)
2. `donegate-mcp --json onboarding --repo-root . --agent codex`
3. [docs/startup-guide.md](docs/startup-guide.md)
4. `.donegate-mcp/onboarding/codex.md` 或 `.donegate-mcp/onboarding/hermes-mcp.yaml`

## 其他文档

- [启动指南](docs/startup-guide.md)
- [端到端演示](docs/end-to-end-demo.md)
- [贡献指南](CONTRIBUTING.md)
- [发布检查表](docs/release-checklist.md)
- [v0.4.0 发布说明](docs/release-notes-v0.4.0.md)

## 许可证

DoneGate 使用 [Apache-2.0](LICENSE) 许可证。
