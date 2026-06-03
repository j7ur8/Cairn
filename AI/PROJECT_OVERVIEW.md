<!--
@ai: 本文件是 Cairn 项目的快速概览。当需要快速了解项目是什么、用了哪些技术、目录结构如何时，请优先阅读本文件。
如需深入了解架构细节，请查阅 AI/ARCHITECTURE.md；如需了解具体实现，请查阅 AI/CODEBASE_ANALYSIS.md。

@update: 本文件应在项目发生重大变更（如核心目标调整、技术栈升级、目录重构）时更新。

生成日期：2026-06-01
-->

# Cairn 快速项目概览

## 项目一句话

Cairn 是一个以 Fact/Intent 图为核心的多 Agent 协作探索系统，通过 Dispatcher 调度容器内的 Claude Code、Codex、Pi 等 Agent，在 Kali 工具环境中推进从 `origin` 到 `goal` 的任务。

## 最重要的心智模型

```text
Server = 协议真相源，只维护图、lease、项目级 capability/role 控制面快照；另有独立 observability DB 存 Execution Log
Dispatcher = 控制面，决定何时跑 bootstrap/reason/explore，并在任务启动前注入项目已选 MCP/Skills/Role
Worker Container = 执行面，每个项目一个 Kali 容器，每个任务实例有独立 `/tmp/cairn-capabilities/{project_id}/{task_instance_id}`
Agent CLI = 真实执行者，在容器里调用工具并返回最终 JSON 契约；Codex/Claude 的结构化流只作为日志旁路
```

## 核心概念

| 概念 | 说明 |
| --- | --- |
| Project | 一个问题实例，有 `active/stopped/completed` 状态 |
| Fact | 已确认事实，只增不改 |
| Intent | 待探索方向，从一个或多个 Fact 出发，最终 conclude 成新 Fact |
| Hint | 人工或外部策略提示，不属于因果图 |
| Reason lease | 项目级互斥，保证单项目同时只有一个 reason |
| Heartbeat | 维持 intent/reason claim，失败或过期会释放/杀进程 |

## 系统架构

```mermaid
flowchart LR
    UI[Web UI / API Client] --> Server[Cairn Server<br/>FastAPI + SQLite]
    Dispatcher[Cairn Dispatcher] <--> Server
    Dispatcher --> Docker[Docker Engine]
    Docker --> PC[Project Container<br/>Kali + Agent CLI]
    PC --> Agent[Claude Code / Codex / Pi]
    Agent --> Tools[Kali Tools<br/>nuclei ffuf netexec impacket ...]
    Agent --> Dispatcher
```

## 三种任务

| 任务 | 触发 | 输入 | 输出 |
| --- | --- | --- | --- |
| `bootstrap` | 新项目初始态 | origin、goal、hints | Fact + optional complete |
| `reason` | 无可探索 intent 且图有新变化 | graph YAML、valid facts、open intents | complete 或新 intents 或 no-op |
| `explore` | 存在未认领 intent | graph YAML、intent id、intent description | 一个新 Fact |

## 调度顺序

```text
1. 项目只有 origin/goal -> bootstrap
2. 有未认领普通 intent -> explore
3. 没有 open intent 且状态变化 -> reason
4. reason 生成 intents 后，下一轮 explore
5. reason 或 bootstrap 判断目标达成 -> complete
```

## 工具如 Kali 如何被调用

Cairn 不直接调用 Kali 命令。真实链路是：

```text
Dispatcher docker exec Agent CLI
Agent CLI 在 Kali 容器内运行
Agent 根据 prompt 使用 bash/tool 调用 nuclei、ffuf、netexec、impacket 等
Agent 输出 JSONL / stream-json / 文本
Dispatcher 从最终 assistant 文本提取 JSON 契约并写回 Server
Dispatcher 同时把结构化 trace 作为 Execution Log 写入 observability API
```

`container/Dockerfile` 构建了完整 Kali 环境，并安装 `codex`、`claude-code`、`pi-coding-agent`。

## Host 附件共享

项目容器可通过 `dispatch.yaml` 的 `container.bind_mounts` 挂载 host 目录，适合 CTF 附件、源码、字典、离线工具和大输出文件：

```yaml
container:
  bind_mounts:
    - name: "ctf-attachments"
      host_path: "./attachments"
      container_path: "/mnt/attachments"
      read_only: true
    - name: "project-files"
      host_path: "./datas/project-files/{project_id}"
      container_path: "/mnt/project"
      read_only: false
```

`{project_id}` 会被渲染为当前项目 ID，用于项目级目录隔离。Agent 不会自动知道附件目录语义，需要在 `origin` 或 `Hint` 中说明，例如：`附件源码已挂载在 /mnt/attachments/web-src`。Fact 黑板仍由 Server/SQLite 维护，bind mount 只用于文件共享。

## Remote Support

`dispatch.yaml` 可配置极简远程协作资源：

```yaml
remote_support:
  enabled: true
  dnslog:
    url: "example.dnslog.cn"
  ssh:
    host: "1.2.3.4"
    port: 22
    username: "root"
    password: "{{REMOTE_SSH_PASSWORD}}"
```

启用后 Dispatcher 会把资源注入 worker 环境变量：

```text
CAIRN_DNSLOG_URL
CAIRN_REMOTE_SSH_HOST
CAIRN_REMOTE_SSH_PORT
CAIRN_REMOTE_SSH_USERNAME
CAIRN_REMOTE_SSH_PASSWORD
```

默认 prompt 只在 `bootstrap.md` / `explore.md` 提示这些变量可用；`reason` 和 conclude prompt 不注入，避免破坏黑板架构的事实判定边界。

## MCP / Skill / Role Capabilities

`dispatch.yaml` 可声明可用 MCP、skill 和 primary role catalog。Server 只保存项目启用的能力 ID 与 role prompt 快照，不保存 MCP env、token 或 skill 内容。Dispatcher 启动后把 catalog 注册到 Server；任务执行前读取项目选择，并在项目容器内按任务实例生成：

```text
/tmp/cairn-capabilities/{project_id}/{task_instance_id}/
├── mcp.json
├── mcp/<mcp_id>/
└── skills/<skill_id>/
```

当前能力边界：

- MCP：支持容器内 `stdio + env`，可选 `source_path` 目录会复制到 `mcp/<mcp_id>/`；`command/args/env` 支持 `{capability_root}` 占位符。
- Skill：支持 host/repo 目录文件包，整体复制到 `skills/<skill_id>/`。
- Role：创建项目时选择一个 primary role；Server 保存 role prompt 快照，Dispatcher 在 `bootstrap` / `explore` / `reason` prompt 中注入 `{role_instructions}`。
- 未声明、未启用、task type 不匹配或注入失败的能力 fail closed，并写入 Execution Log；业务 Fact/Intent/Hint 语义不变。

### 本地资源目录

能力相关资源统一放在项目根的 `capabilities/` 目录，`dispatch.yaml` 用相对路径引用：

```text
capabilities/
├── README.md
├── mcp/                          # 本地 MCP server 资料：仓库说明、构建脚本、容器配置、mcp.json 模板
├── skills/<skill_id>/            # 单个 skill 文件包，会被整体复制到容器内
│   └── SKILL.md
└── roles/<role_id>/              # primary role 固定 prompt
    └── ROLE.md
```

`dispatch.yaml` 示例：

```yaml
runtime:
  prompt_group: "cypher"

capabilities:
  mcp_servers:
    - id: "kali-server-mcp"
      name: "Kali Server MCP"
      command: "/usr/local/bin/kali-mcp-stdio"
      args: []
      env: {}
      task_types: ["bootstrap", "explore", "reason"]
    - id: "metasploit-mcp"
      name: "Metasploit MCP"
      command: "/usr/local/bin/metasploit-mcp-stdio"
      args: []
      env: {}
      task_types: ["explore", "reason"]
  skills:
    - id: "cypher-ctf"
      name: "Cypher CTF"
      source_path: "./capabilities/skills/cypher-ctf"
      task_types: ["bootstrap", "explore", "reason"]

roles:
  - id: "cypher-ctf-operator"
    name: "Cypher CTF Operator"
    source_path: "./capabilities/roles/cypher-ctf-operator/ROLE.md"
    task_types: ["bootstrap", "explore", "reason"]
```

### Cypher Agent 预置能力

本轮已落地 `cypher` prompt group 和 3 个内置 skill：

- `cypher-ctf`
- `cypher-pentest`
- `cypher-vuln-research`

并提供 3 个 primary role：

- `cypher-ctf-operator`
- `cypher-pentest-operator`
- `cypher-vuln-researcher`

这些都是控制面上下文，不会把角色或能力本身写成 Fact；只有 Agent 验证后的结论才写入黑板。

## Heartbeat 如何保证任务存活

Dispatcher 任务启动后会创建 `HeartbeatLease`：

| 任务 | Lease |
| --- | --- |
| `bootstrap` | Intent heartbeat |
| `explore` | Intent heartbeat |
| `reason` | Project reason heartbeat |

heartbeat 每 `runtime.interval` 秒调用一次 Server：

```text
成功 -> 更新 last_heartbeat_at
403/409 -> lease 无效，杀掉当前容器 exec
临时失败 -> 等待 grace，超过 grace 后杀进程
```

Server 会按 `/settings` 中的 `intent_timeout` 和 `reason_timeout` 清理过期 claim。

## 如何避免 infinite loop

主要靠多层限制：

| 层级 | 机制 |
| --- | --- |
| 命令层 | Docker exec 前加 `timeout -k 5s` |
| 任务层 | bootstrap/reason/explore 都有 timeout |
| 收尾层 | conclude fallback 有独立短 timeout |
| 调度层 | reason 只有图状态变化时触发 |
| 图层 | concluded intent 不会再次执行 |
| 并发层 | max_workers/max_project_workers/max_running_projects |
| 输出层 | JSON contract 校验失败不写图 |
| backoff | unhealthy/rejected worker 短暂不可选 |

>>⚠️ 注意：这些机制防止进程和调度死循环，但不能完全防止 Agent 语义上不断生成低质量 intent。实际运行仍需要合理 prompt、`max_intents`、人工 Hint 和项目 stop 控制。

## 常用命令

```bash
uv run --project cairn cairn serve
uv run --project cairn cairn serve --observability-db-path ~/.local/share/cairn/cairn_observability.db
uv run --project cairn cairn dispatch --config dispatch.yaml
uv run --project cairn cairn dispatch --config dispatch.yaml --startup-healthcheck-only
docker compose up --build
```

## 关键文件速查

| 文件 | 作用 |
| --- | --- |
| `cairn/src/cairn/cli.py` | CLI 入口 |
| `cairn/src/cairn/server/app.py` | FastAPI app |
| `cairn/src/cairn/server/db.py` | SQLite schema |
| `cairn/src/cairn/server/observability/` | 独立 Execution Log DB、API、脱敏与查询 |
| `cairn/src/cairn/server/observability/redaction.py` | Server 侧内置脱敏(密码 / `*PASSWORD` / `*TOKEN` / `Authorization: Bearer ...`) |
| `cairn/src/cairn/dispatcher/observability/redaction.py` | Dispatcher 侧内置脱敏,与 Server 端正则集合对齐 |
| `cairn/src/cairn/server/routers/capabilities.py` | 项目 MCP/skill 能力启用、capability catalog、role catalog 与 project role API |
| `cairn/src/cairn/server/routers/attachments.py` | 附件上传（multipart），自动写 Hint |
| `cairn/src/cairn/server/routers/files.py` | 项目报告 / exploit / 附件文件列举与下载 |
| `cairn/src/cairn/server/routers/replay.py` | Replay run 创建与推进（基于已完成项目） |
| `cairn/src/cairn/server/routers/projects.py` | Project/status/reason/complete API |
| `cairn/src/cairn/server/routers/intents.py` | Intent create/heartbeat/release/conclude API |
| `cairn/src/cairn/server/routers/export.py` | YAML/timeline 导出 |
| `cairn/src/cairn/dispatcher/scheduler/loop.py` | 主调度循环 |
| `cairn/src/cairn/dispatcher/tasks/bootstrap.py` | bootstrap 任务 |
| `cairn/src/cairn/dispatcher/tasks/reason.py` | reason 任务 |
| `cairn/src/cairn/dispatcher/tasks/explore.py` | explore 任务 |
| `cairn/src/cairn/dispatcher/runtime/containers.py` | Docker 容器管理 |
| `cairn/src/cairn/dispatcher/runtime/heartbeat.py` | heartbeat lease |
| `cairn/src/cairn/dispatcher/capabilities.py` | MCP/skill catalog 构造、项目能力选择解析与容器注入 |
| `cairn/src/cairn/dispatcher/roles.py` | Role catalog 构造、项目 role prompt 快照注入 |
| `capabilities/README.md` | MCP/skill/role 本地资源目录约定 |
| `capabilities/skills/` | Cypher 与示例 skill 文件包 |
| `capabilities/roles/` | Cypher primary role prompt 文件 |
| `cairn/src/cairn/dispatcher/workers/adapters/` | Claude/Codex/Pi/Mock 适配器 |
| `cairn/src/cairn/dispatcher/prompts/default/` | 默认任务 prompt；已支持 capability 与 role 注入 |
| `cairn/src/cairn/dispatcher/prompts/cypher/` | Cypher Agent 专用 bootstrap/explore/reason/conclude prompt；强制最终交付物写盘 |
| `cairn/src/cairn/dispatcher/observability/trace.py` | 解析 Codex/Claude 结构化执行轨迹 |
| `dispatch.yaml` | 真实运行 Dispatcher 配置；密钥全部用 `${ENV_VAR}` 引用 |
| `.env.example` | 密钥模板，提交到 git；真实 `.env` 由本机 `cp` 出来使用 |
| `dispatch_mock.yaml` | mock 运行配置 |
| `container/Dockerfile` | Worker 容器镜像（Kali + Claude/Codex/Pi + MCP stdio 桥） |
| `container/AGENTS.md` | Worker 容器内 Agent 操作约定 |
| `container/README.md` | Worker 容器构建与 smoke test 步骤 |
| `container/bin/kali-mcp-stdio` | Kali MCP stdio 桥，对应 dispatch.yaml `kali-server-mcp` |
| `container/bin/metasploit-mcp-stdio` | Metasploit MCP stdio 桥，对应 dispatch.yaml `metasploit-mcp` |

## 敏感信息处理

不要在文档、日志或示例里复制真实 API key、SSH 密码或远程辅助服务器凭据。文档示例统一写成 `${ENV_VAR}`：

```text
${OPENAI_API_KEY}
${ANTHROPIC_AUTH_TOKEN}
${PI_API_KEY}
${CAIRN_REMOTE_SSH_PASSWORD}
```

`dispatch.yaml` 现在用 `${ENV_VAR}` 引用敏感字段。`DispatchConfig.load()` 加载时按以下规则解析:

| 语法 | 行为 |
| --- | --- |
| `${VAR}` | 必须设置；未设则抛 `ValueError: ... environment variable is not set` |
| `${VAR:-default}` | 未设或为空时使用 default（等同 bash `:-` 语义） |
| `${VAR-default}` | 仅未设时使用 default；显式空串保留为空（等同 bash `-` 语义） |

`dispatch.yaml` 中 SSH 字段用 `${CAIRN_REMOTE_SSH_*:-}` 形式，允许不设；LLM token 用 `${DEEPSEEK_AUTH_TOKEN}` 这种无默认形式，强制要求。

**MCP HTTP transport**（`McpServerCapabilityConfig.transport: "http"`）— token 走 `${MCP_AUTH_TOKEN}` 形式注入:

- `bearer_token_env: MCP_AUTH_TOKEN` 引用**变量名**而非值,被 `${VAR}` 插值跳过,加载时校验 env 必须存在,缺失即 `ValueError`。
- Codex adapter 走 `-c mcp_servers.<id>.bearer_token_env_var=MCP_AUTH_TOKEN`,由 Codex 自身读 env;Claude adapter 在写 `mcp.json` 时**现场拼** `headers.Authorization: Bearer <token>`,序列化后立即释放,不进 `WorkerExecutionContext`。
- 变量名会合并进 worker container `environment`,确保容器内 worker 进程能 `os.environ` 拿到。
- HTTP MCP server 可达性由 `inject_project_capabilities` 在写 `mcp.json` 前做 TCP 探活(默认 1s),失败 → 跳过该 mcp,UI 标 `unavailable`。
- HTTP MCP server 与 worker 容器的网络连通由部署者负责(可改 `container.network_mode` 或把端口 bind 到 `cairn` network);`Authorization: Bearer ...` 由 observability `redaction.py` 兜底,落库前替换为 `Authorization: Bearer ***`。
- `.env.example` 末尾有 SECURITY 注释(不要把 `.env` 内容贴到 issue tracker / IM / 邮件 / 截图,定期轮换 `MCP_AUTH_TOKEN`)。

**本地运行（直接 `uv run`）** — 在 shell 临时 export，或用 direnv:

```bash
brew install direnv
# ~/.zshrc: eval "$(direnv hook zsh)"
echo 'export DEEPSEEK_AUTH_TOKEN=sk-...' > Cairn/.envrc
cd Cairn && direnv allow
```

**docker compose 部署** — 项目根的 `.env` 文件被 `cairn-dispatcher` 服务的 `env_file: - .env` 注入容器。`.env` 已被 `.gitignore` 和 `.dockerignore` 排除；`.env.example` 进了 git 作为模板:

```bash
cp .env.example .env
# 编辑 .env 填入真实密钥
docker compose up --build cairn-dispatcher
```

这样 `dispatch.yaml` 和 `docker-compose.yaml` 都可以提交到公开仓库而不会泄露密钥。

Execution Log 默认隐藏 `usage`，并会对 `CAIRN_REMOTE_SSH_PASSWORD` / 通用 `*PASSWORD` 做 redaction；但仍应避免主动把真实 secret 写入 prompt、fact 或文档。

Dispatcher 的 `observability` 配置控制是否记录 prompt/stdout/stderr/raw worker stream 以及 Dispatcher 侧缓冲、脱敏和大小限制；Server 端 observability API 仍使用内置默认设置做二次脱敏与截断。

## 部署环境前置条件

**macOS Docker Desktop** — `container.user` **必须** 在 `dispatch.yaml` 显式设成 `"0:0"`,否则 worker 写 `/mnt/project` 报 `Permission denied`,startup healthcheck 不过。根因是 VirtioFS 的内核层行为:write syscall 在容器内非 root 用户(无论 host 文件 mode 是不是 0o777、容器用户 UID 是不是 file owner)一律拒绝,已用 `docker run --user=...` 真机验证过 3 次。worker 容器本身已用 `network_mode: cairn` 限制网络、bind mount 只暴露到 `/mnt/project`、image 内 `kali` 用户已 `NOPASSWD:ALL`,实际权限等级等同 root,这个让步在 macOS 上是必要的。

**Linux Docker Engine** — UID namespace 与 host 1:1 共享,`container.user` 可不设,默认行为(image 内 `USER kali`)直接可用。如要最小化攻击面,设成 host `uid:gid`(`id -u` / `id -g`)即可,不需要 root。

详细根因分析见 `AI/UPDATE.md` 2026-06-03 "修复 startup healthcheck 在 macOS Docker Desktop 上的 bind mount 权限错误" 条目。

## 后续修改建议

| 目标 | 修改入口 |
| --- | --- |
| 改调度策略 | `dispatcher/scheduler/loop.py` |
| 新增 Agent 后端 | `dispatcher/workers/adapters/` + `registry.py` + `config.py` |
| 改输出 JSON 契约 | `dispatcher/contracts.py` + prompts |
| 改 Server 协议 | `server/models.py` + routers + `db.py` schema |
| 改容器生命周期 | `dispatcher/runtime/containers.py` |
| 改 heartbeat 行为 | `dispatcher/runtime/heartbeat.py` + Server heartbeat API |
| 改 MCP/skill/role 本地资源位置 | `capabilities/mcp/` / `capabilities/skills/<id>/` / `capabilities/roles/<id>/ROLE.md` + `dispatch.yaml` 的 `capabilities.*` / `roles.*` |
| 加附件上传行为 | `cairn/src/cairn/server/routers/attachments.py` + `datas/attachments/` 主机目录 |
| 加项目文件浏览/下载 | `cairn/src/cairn/server/routers/files.py` |
| 加 Replay run 行为 | `cairn/src/cairn/server/routers/replay.py` + `dispatcher/scheduler/loop.py:_advance_replay_project()` |
| 改 Worker 容器镜像/工具 | `container/Dockerfile` + `container/bin/*-mcp-stdio` + `dispatch.yaml` 的 `capabilities.mcp_servers` |
