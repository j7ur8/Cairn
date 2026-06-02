<!--
@ai: 本文件记录 Cairn 项目的增量更新。后续 Codex 会话在继续实现、联调或回溯问题前，应优先阅读本文件，以了解最近一次修改、验证结果与未完成事项。

维护约定：
- 每次有实质代码/架构更新时，按时间倒序追加一节。
- 每节至少包含：背景、已完成变更、验证结果、未完成事项/风险。
- 本文件记录的是“实际已落地或已确认”的更新，不写纯设想。
-->

# Cairn 更新记录

## 2026-06-02 · Cypher Agent capabilities / roles 全链路实现与 AI 文档同步（已完成）

### 背景

用户要求以 Cairn 为母版，参考自动化 CTF、渗透测试、漏洞挖掘方向，实现 Cypher Agent，并满足：

- 本地 MCP / skills 统一放到 `capabilities/mcp` 与 `capabilities/skills`。
- 创建项目时 UI 可选择 skills 与 MCP，worker 启动任务时复制已选项到 worker 容器，供 Codex / Claude 调用。
- 创建项目时可选择项目主要角色，将固定 role prompt 注入 `bootstrap`、`explore`、`reason`。
- 保持健壮性、高可用、水平伸缩、安全、可维护、性能、可观测、数据一致性和黑板架构边界。

### 已完成变更

- 新增 Cypher prompt group：`cairn/src/cairn/dispatcher/prompts/cypher/`。
- 新增 Cypher skills：
  - `capabilities/skills/cypher-ctf/`
  - `capabilities/skills/cypher-pentest/`
  - `capabilities/skills/cypher-vuln-research/`
  - `capabilities/skills/cypher-flag-oob/`
- 新增 primary role prompt：
  - `capabilities/roles/cypher-ctf-operator/ROLE.md`
  - `capabilities/roles/cypher-pentest-operator/ROLE.md`
  - `capabilities/roles/cypher-vuln-researcher/ROLE.md`
- Server 新增/扩展：
  - `role_catalog`、`project_roles` 表。
  - `GET /roles/catalog`、`POST /roles/catalog`、`GET /projects/{project_id}/role`。
  - `POST /projects` 支持 `capabilities` 与 `role` / `role_id`，并保存 role prompt 快照。
- Dispatcher 新增/扩展：
  - `RoleConfig` 与 `roles[]` 配置。
  - `dispatcher/roles.py` 负责 role catalog 与 role prompt 注入。
  - `dispatcher/capabilities.py` 改为按任务实例路径注入：`/tmp/cairn-capabilities/{project_id}/{task_instance_id}/...`。
  - Scheduler 启动时同时注册 capability catalog 和 role catalog。
  - `bootstrap` / `explore` / `reason` 都会读取项目 role 与 capabilities，并渲染 `{capability_instructions}` / `{role_instructions}`。
- Worker adapter 扩展：
  - `WorkerExecutionContext` 传递 MCP/skill 注入上下文。
  - Claude 追加 `--mcp-config` / `--add-dir`。
  - Codex 追加 `--add-dir` 与 `-c mcp_servers.<id>.*`。
  - Pi / Mock 签名兼容 `context=None`。
- UI 扩展：
  - New Project modal 可选择 Primary Role、MCP Servers、Skills。
  - 创建项目时提交 capability selection 与 role selection。
  - Graph 侧栏 `Caps` 仍可维护项目能力选择。
- 配置与文档：
  - `dispatch.yaml` 切换到 `prompt_group: "cypher"`，并声明 Cypher skills / roles。
  - `capabilities/README.md` 补 role 目录与 task-instance 注入路径约定。
  - `docs/designs/cypher-agent.md`、`docs/designs/cypher-capabilities-roles.md` 记录设计。
  - 本次已同步更新 `AI/ARCHITECTURE.md`、`AI/CODEBASE_ANALYSIS.md`、`AI/PROJECT_OVERVIEW.md`、`AI/UPDATE.md`。

### 架构边界

- Capability / Role 属于控制面配置，不写入 `facts` / `intents` / `hints`。
- `Fact` 仍只表示已确认客观发现；`Intent` 仍只表示待探索方向；`Hint` 仍只表示人工/外部策略输入。
- Server 不保存 MCP env、token 或 skill 内容；role catalog API 不向 UI 返回 prompt 正文，只返回 hash/detail。
- 项目保存 role prompt 快照，避免后续 role catalog 变化影响既有项目一致性。
- 每个任务实例使用独立 capability 注入目录，避免同项目并发任务互相覆盖。

### 验证结果

已通过：

- `PYTHONPATH=cairn/src python3 -m compileall -q cairn/src/cairn`
- `DispatchConfig.load()` 加载 `dispatch_mock.yaml` 与 `dispatch.yaml`
- 前端 inline JS `node --check`
- `git diff --check`
- 临时 DB FastAPI TestClient smoke test：
  - 注册 role catalog
  - 注册 capability catalog
  - 创建带 role / capability 的项目
  - 查询 `/projects/{project_id}/role`
  - 查询 `/projects/{project_id}/capabilities`

### 未完成事项/风险

- Codex MCP 注入使用 `-c mcp_servers.<id>.*`，需在真实 Codex CLI 环境做端到端 MCP 调用验证。
- Claude `--mcp-config` / `--add-dir` 已接线，仍需真实 Claude Code 端到端验证。
- 多 Dispatcher 场景仍要求各 Dispatcher 的 `capabilities` 与 `roles` catalog 保持一致，否则后启动实例会全量覆盖 Server catalog。
- `dispatch.yaml` 是运行期配置，仍需避免提交真实 API key / token / SSH 密码到公开仓库。

---

## 2026-06-01 · AI 文档目录结构对齐 project-review 技能（已完成）
## 2026-06-01 · capabilities/ 本地资源目录建立（已完成）

### 背景

MCP/skill 已接入但 `dispatch.yaml` 直接引用分散的目录，约定不显式。本轮在项目根新增 `capabilities/` 子目录，统一存放 MCP 资料和 skill 文件包，`dispatch.yaml` 的 `capabilities.*` 用相对路径引用。

### 已完成变更

- 新建 `capabilities/mcp/`、`capabilities/skills/`，各加 `.gitkeep` 保留空目录
- 新建 `capabilities/README.md` 描述目录约定与 yaml 引用示例
- 新建 `capabilities/skills/example-recon/SKILL.md` 作为最小可复制 skill 模板
- `dispatch.yaml` 的 `capabilities:` 节点增加注释与示例，指向 `./capabilities/skills/example-recon`
- `AI/PROJECT_OVERVIEW.md` MCP / Skill Capabilities 章节补 `本地资源目录` 小节，关键文件速查与后续修改建议同步更新

### 验证结果

- `python3 -m compileall -q cairn/src/cairn` 通过
- `DispatchConfig.load(dispatch.yaml)` 通过
- `git status --short` 仅增加新文件与 `dispatch.yaml` 注释扩展

### 未完成事项/风险

- `capabilities/mcp/` 当前没有强制内容；后续若引入本地 MCP server 资料或 `mcp.json` 模板，建议在 `capabilities/README.md` 中补一份命名约定。
- Skill 资源缺少 size/数量/符号链接限制仍属已有风险，未在本轮处理。

---


### 背景

`project-review` 技能在模式一要求生成 `AI/ARCHITECTURE.md`、`AI/CODEBASE_ANALYSIS.md`、`AI/PROJECT_OVERVIEW.md`、`AI/UPDATE.md` 四份文档，全部直接放在 `AI/` 下。
此前 Cairn 把项目概览放在 `AI/docs/project-overview.md`，与技能模板不一致，也使项目级阅读路径多一层子目录。本轮把概览文档迁回 `AI/PROJECT_OVERVIEW.md`，删除空目录，统一引用。

### 已完成变更

- `git mv AI/docs/project-overview.md AI/PROJECT_OVERVIEW.md`
- 删除空目录 `AI/docs/`
- `AI/PROJECT_OVERVIEW.md` 元指令头按技能标准增加 `@update` 提示与 `生成日期`
- `AI/ARCHITECTURE.md` 顶部两处引用、目录树入口同步改为 `AI/PROJECT_OVERVIEW.md`
- `AI/UPDATE.md` 历史条目中两处 `AI/docs/project-overview.md` 同步改为 `AI/PROJECT_OVERVIEW.md`

### 验证结果

- `git status --short AI/` 仅剩重命名与两处文本修改
- `rg -n "AI/docs|project-overview" AI/` 已无残留旧引用
- 仅做文档结构整理，未修改任何业务代码

### 未完成事项/风险

- 本轮只重命名/改引用，未同步 MCP/Skill 在 `AI/ARCHITECTURE.md`、`AI/CODEBASE_ANALYSIS.md` 中的内容（参见上一轮已识别的增量同步建议）

---

## 2026-06-01 · MCP / Skill 项目级能力管理接入（已完成）

### 背景

本轮实现 MCP 与 skill 的第一阶段能力管理闭环，同时保持 Cairn 黑板核心架构不变：

- `dispatch.yaml` 是能力目录和敏感凭据真相源。
- Server 只保存项目级启用 ID，不保存 secret。
- Dispatcher 在任务启动前把启用能力注入项目容器。

### 已完成变更

- 新增 Server 表：
  - `capability_catalog`
  - `project_capabilities`
- 新增能力 API：
  - `GET /projects/{project_id}/capabilities`
  - `PUT /projects/{project_id}/capabilities`
  - `POST /capabilities/catalog`
- 新增 dispatcher 配置模型：
  - `capabilities.mcp_servers[]`
  - `capabilities.skills[]`
- MCP 第一阶段支持容器内 `stdio + env` 配置生成。
- Skill 第一阶段支持 host/repo 目录注入。
- Dispatcher 启动后注册脱敏能力目录到 Server。
- bootstrap/explore/reason 执行前生成：
  - `/tmp/cairn-capabilities/{project_id}/{task_type}/mcp.json`
  - `/tmp/cairn-capabilities/{project_id}/{task_type}/skills/`
- 默认 prompt 增加 `{capability_instructions}`。
- Graph 侧栏新增 `Caps` tab，可按项目启用/禁用 MCP server 和 skill。
- Execution Log 记录 capability 注入摘要和错误。

### 架构边界

- 不改变 `facts/intents/hints/settings` 的业务语义。
- 不改变 bootstrap/reason/explore JSON contract。
- 不在 Server DB/API/UI 中保存 MCP env、token 或 skill 内容。
- 未声明、未启用、task type 不匹配或注入失败的能力 fail closed。

### 验证结果

已完成：

- `PYTHONPATH=cairn/src python3 -m compileall -q cairn/src/cairn`
- `DispatchConfig.load()` 加载 `dispatch.yaml` / `dispatch_mock.yaml`
- FastAPI TestClient smoke test：
  - 注册 capability catalog
  - 创建项目
  - 保存项目 capability selection
  - 查询 selection
  - 悬挂 capability ID 被标记为 unavailable

### 未完成事项/风险

- 尚未做真实 MCP server 端到端调用验证。
- 尚未做真实 skill 文件包注入后的 Agent 使用验证。
- 多 Dispatcher 场景仍要求各 Dispatcher 的 `dispatch.yaml` 能力目录一致。

## 2026-06-01 · AI 文档代码行为校准（已完成）

### 背景

本轮按当前代码重新审阅 `AI/` 下说明文件，要求以代码行为为准修正文档。

### 已完成变更

- `AI/ARCHITECTURE.md`
  - 补充主业务 DB 与 observability DB 分离。
  - 补充 Server observability API 与 Dispatcher trace/reporter 模块职责。
  - 修正工具调用链路：Codex/Claude 输出 JSONL/stream-json，Dispatcher 从最终 assistant 文本提取业务 JSON 契约，同时旁路写 Execution Log。
  - 补充 `/llm-executions`、`/llm-events` API。
- `AI/CODEBASE_ANALYSIS.md`
  - 补充 `--observability-db-path`、`server/observability/*` 模块、observability API 与配置边界。
  - 修正 `WorkerDriver` 接口说明，加入 `trace_format()`。
  - 修正 Claude/Codex 命令说明：Claude 使用 `--output-format stream-json --verbose`，Codex 使用 `--json`。
- `AI/PROJECT_OVERVIEW.md`
  - 同步快速心智模型、工具调用链路、关键文件和敏感信息处理说明。

### 验证结果

已完成文档与代码静态核对，重点核对：

- `cairn/src/cairn/cli.py`
- `cairn/src/cairn/server/observability/*`
- `cairn/src/cairn/dispatcher/config.py`
- `cairn/src/cairn/dispatcher/tasks/*`
- `cairn/src/cairn/dispatcher/workers/adapters/{claudecode,codex}.py`
- `cairn/src/cairn/dispatcher/observability/*`
- `cairn/src/cairn/server/static/index.html`

### 未完成事项/风险

- 本轮只做文档校准，没有修改业务代码。
- 未执行端到端运行验证；文档一致性依据静态代码审阅。

## 2026-06-01 · Execution Log Usage 过滤与 Remote Support 极简注入（已完成）

### 背景

本轮根据最新方案实现两项旁路能力增强：

- 修复 Claude `system/init`、`system/api_retry` 被误分类为 `Usage` 的问题，并让 `usage` 默认不打扰主视图。
- 新增极简 `remote_support`，只支持 DNSLog 地址和远程 SSH 账号密码，并只注入执行型 prompt。

### 已完成变更

- `ClaudeTraceParser` 中 `system/*` 不再映射为 `usage`：
  - `system/init` -> `session_init`
  - `system/api_retry` -> `api_retry`
  - 其他 `system/*` -> `system_event`
- Graph 页 `Execution Log` 新增 `Show Usage` 开关，默认关闭；`usage` 不再进入默认 `All/Output` 视图。
- 新增 dispatcher 配置模型 `remote_support`：
  - `dnslog.url`
  - `ssh.host / port / username / password`
- `remote_support` 会合并到 worker env：
  - `CAIRN_REMOTE_SUPPORT_ENABLED`
  - `CAIRN_DNSLOG_URL`
  - `CAIRN_REMOTE_SSH_HOST`
  - `CAIRN_REMOTE_SSH_PORT`
  - `CAIRN_REMOTE_SSH_USERNAME`
  - `CAIRN_REMOTE_SSH_PASSWORD`
- 仅 `default/bootstrap.md` 与 `default/explore.md` 增加 `{remote_support_instructions}` 占位符；conclude/reason 不注入。
- prompt 中只提示环境变量名，不渲染 SSH 密码明文。
- `dispatch.yaml` 与 `dispatch_mock.yaml` 补充 disabled 示例配置。

### 架构边界

- 不修改黑板业务 DB/schema。
- 不改变 `facts/intents` 的真相来源。
- 不改变 claim/release/heartbeat。
- 不改变 `container.network_mode: cairn`。
- Remote Support 仅作为 worker runtime env 与执行型 prompt 能力提示。

### 验证结果

已完成并通过：

- `PYTHONPATH=cairn/src python3 -m compileall -q cairn/src/cairn`
- `DispatchConfig.load()` 加载 `dispatch.yaml` / `dispatch_mock.yaml`
- Remote Support env 注入 smoke test
- `bootstrap.md` / `explore.md` prompt 注入 smoke test，确认不包含 SSH 密码明文
- Claude trace parser smoke test：`system/init`、`system/api_retry`、其他 `system/*` 与真实 `usage` 分类正确
- server `CreateEventRequest` 接受 `session_init`、`api_retry`、`system_event`、`usage`

### 追加说明

- server 观察模型已允许 `session_init`、`api_retry`、`system_event` 三类新增事件。
- dispatcher/server 内置 redaction 规则已覆盖 `CAIRN_REMOTE_SSH_PASSWORD` 和通用 `*PASSWORD`，避免环境变量出现在 prompt 或日志时明文展示。

### AI 文档同步

已同步更新：

- `AI/ARCHITECTURE.md`：补充 observability / remote_support 配置示例与架构边界说明。
- `AI/CODEBASE_ANALYSIS.md`：补充 `RemoteSupportConfig`、env 注入规则、prompt 注入范围与配置字段说明。
- `AI/PROJECT_OVERVIEW.md`：补充 Remote Support 快速说明、关键文件与敏感信息处理说明。

### 受影响文件（本轮）

- `cairn/src/cairn/dispatcher/config.py`
- `cairn/src/cairn/dispatcher/prompting.py`
- `cairn/src/cairn/dispatcher/tasks/bootstrap.py`
- `cairn/src/cairn/dispatcher/tasks/explore.py`
- `cairn/src/cairn/dispatcher/prompts/default/bootstrap.md`
- `cairn/src/cairn/dispatcher/prompts/default/explore.md`
- `cairn/src/cairn/dispatcher/observability/trace.py`
- `cairn/src/cairn/server/static/index.html`
- `dispatch.yaml`
- `dispatch_mock.yaml`

## 2026-06-01 · Execution Log 下拉防刷新首轮修复（进行中）

### 背景

在 Graph 页面中，`Execution Log` 的 execution 选择器使用原生 `<select>`。由于轮询会周期性刷新 execution 列表，导致用户在展开下拉并尝试选择某个 execution 时，DOM 被重绘，下拉被打断，难以正常选中。

### 已完成变更

已在前端加入首轮“交互冻结态”修复：

- 为 execution 选择器增加交互状态：
  - `llmExecutionSelectInteracting`
  - `llmExecutionsRefreshPending`
- 在选择器交互期间，`loadLlmExecutions()` 不再直接替换 execution 列表，而是先标记 pending
- 在交互结束后，若存在 pending，再补执行一次 execution 列表同步
- execution 列表更新逻辑改为 `applyLlmExecutions()`，避免无变化时重复赋值重绘
- 若当前选中的 execution 在刷新后已不存在，会自动回退到 `All executions`

### 当前状态

这次修复已经落地到代码，但**问题仍未彻底解决**。现有结论是：

- 单纯依赖原生 `<select>` 的 `focus / blur / mousedown / keydown / change` 事件，不足以在所有浏览器中稳定阻止原生下拉被刷新打断
- 原生 `<select>` 打开时的系统级下拉层不完全受页面 DOM 控制，只要 execution 列表对应节点发生重绘，仍可能关闭

### 当前判断

目前可以确认：

- 首轮最小修复已经实现
- 根因仍在于继续使用原生 `<select>`
- 下一轮更稳妥的方向应是改为**自定义下拉/弹层列表**，而不是继续在原生 `<select>` 上做补丁

### 受影响文件（本轮）

- `cairn/src/cairn/server/static/index.html`

---

## 2026-06-01 · Execution Log 配置显式化（已完成）

### 背景

此前 `Execution Log` 的行为主要由 dispatcher 配置模型默认值驱动，`dispatch.yaml` 中未显式写出 `observability:` 配置块，排查和调整记录策略时不够直观。

### 已完成变更

已在 `dispatch.yaml` 中显式加入完整的 `observability:` 配置块，与当前 mock 配置保持一致，包含：

- `enabled`
- `record_prompts`
- `record_stdout`
- `record_stderr`
- `record_raw_worker_stream`
- `max_event_bytes`
- `max_bytes_per_execution`
- `flush_interval_ms`
- `flush_max_bytes`
- `retention_days`
- `redaction_patterns`

### 当前效果

现在可以直接通过 `dispatch.yaml` 调整 Execution Log 的记录策略，而不必依赖代码默认值推断当前行为。

### 受影响文件（本轮）

- `dispatch.yaml`

---

## 2026-06-01 · Cairn 容器统一接入 `cairn` Docker Network（已完成）

### 背景

此前项目中存在两套网络语义：

- `docker-compose` 服务容器使用 compose 默认网络
- dispatcher 动态创建的项目容器默认使用 `network_mode: "host"`

这种分裂网络模型不利于后续容器间发现、统一调试和运维管理。

### 已完成变更

已将新的默认网络模型统一为 `cairn`：

- `docker-compose.yaml`
  - 新增顶层 `networks.cairn`
  - `cairn-server`、`cairn-dispatcher` 均接入 `cairn`
- `dispatch.yaml`
  - `container.network_mode` 从 `host` 改为 `cairn`
- `dispatch_mock.yaml`
  - `container.network_mode` 从 `host` 改为 `cairn`
- `README.md`
  - manual 运行方式新增 `docker network create cairn` 前置说明
- `docs/specs/dispatcher-design.md`
  - 示例配置中的 `network_mode` 同步改为 `cairn`

### 已完成验证

已完成静态验证：

- `docker compose config` 通过
- compose 解析结果中 `cairn-server`、`cairn-dispatcher` 均指向 `cairn` 网络
- 配置与文档中的默认网络示例已切换到 `cairn`

### 注意事项

这项更新对**新创建/重建的容器**生效；已有运行中的旧容器不会自动从 `cairn_default` 迁移到 `cairn`，需要通过重建或重启 compose 服务后生效。

### 受影响文件（本轮）

- `docker-compose.yaml`
- `dispatch.yaml`
- `dispatch_mock.yaml`
- `README.md`
- `docs/specs/dispatcher-design.md`

---

## 2026-06-01 · Execution Log 结构化增强（进行中）

### 背景

本轮目标是把现有 `Execution Log` 从简单的 prompt/stdout/stderr/result 记录，增强为接近 Codex `Ctrl+T` / Claude Code 过程面板的结构化执行轨迹，同时保持原黑板架构不受影响：

- 业务黑板 DB 继续只承载 `projects / facts / intents / hints / settings`
- 观察数据继续独立写入 observability DB
- 观察写入失败、trace 解析失败、脱敏失败都不能影响 worker 主流程
- 前端只把这些数据作为 `Execution Log` 展示，不参与 fact/intents 真值判断

### 已完成变更

#### 1. Dispatcher 观察链路增强

已新增结构化 trace 解析能力，支持把 worker 的 JSON/stream 输出转换为更细粒度事件：

- 新增 `cairn/src/cairn/dispatcher/observability/trace.py`
- 新增事件类型：
  - `agent_message`
  - `thinking`
  - `tool_call`
  - `tool_result`
  - `command_start`
  - `command_end`
  - `usage`
  - `trace_parse_error`
- `ExecutionReporter` 新增 `emit_trace_event()`，统一把结构化事件写入 observability API
- `run_worker_process()` 已接入 trace parser：
  - 对支持 trace 的 worker，优先解析 stdout 中的结构化流
  - 默认不再记录 raw JSON worker stdout，避免 Execution Log 被 JSONL 刷屏
  - 可通过 `record_raw_worker_stream: true` 打开原始流记录
  - parser 失败时只写 `trace_parse_error`，不影响任务执行结果

#### 2. Worker Driver 增强

已为不同 worker 补齐 trace 输出与最终响应提取逻辑：

- `WorkerDriver` 新增 `trace_format()`
- `CodexDriver`
  - 执行/续跑命令增加 `--json`
  - 保留 `--dangerously-bypass-approvals-and-sandbox`
  - 从 JSONL 中提取 session id 与最终 assistant message
- `ClaudeCodeDriver`
  - 执行/续跑命令增加 `--output-format stream-json`
  - 保留 `--dangerously-skip-permissions`
  - 从 stream-json 中提取最终 assistant text/result
  - 兼容当前 CLI 要求，已补充 `--verbose`

#### 3. Server 观察模型与脱敏增强

已扩展 server observability 模型与脱敏规则：

- `cairn/src/cairn/server/observability/models.py` 已允许新增 event kind
- dispatcher/server 两侧都加入内置敏感信息脱敏：
  - `OPENAI_API_KEY`
  - `ANTHROPIC_AUTH_TOKEN`
  - 通用 `*_API_KEY` / `*_AUTH_TOKEN`
  - `Authorization: Bearer ...`
- 观察事件仍然先做 redaction，再做截断与总量限制

#### 4. 前端 Execution Log 面板增强

已增强 Graph 页左侧 `Execution Log` 面板：

- 新增事件过滤：
  - `All`
  - `Tools`
  - `Cmds`
  - `Output`
  - `Errors`
- 新增结构化事件标签与样式：
  - `Tool Call`
  - `Tool Result`
  - `Command Start`
  - `Command End`
  - `Agent`
  - `Thinking`
  - `Usage`
  - `Trace Parse`
- 仍坚持纯文本渲染：使用 `x-text`，不使用 `x-html`

#### 5. 配置项补充

已新增 dispatcher 观察配置项：

```yaml
observability:
  record_raw_worker_stream: false
```

默认关闭，用于避免结构化 trace 模式下重复记录原始 JSON 输出。

### 已完成验证

#### 静态/单元级验证

已完成并通过：

- `python3 -m compileall cairn/src/cairn`
- Codex trace parser smoke test
- Claude trace parser smoke test
- driver argv smoke test
- observability repository smoke test
  - 新 event kind 可写入
  - sequence 增量查询顺序正确
  - redaction 生效
  - truncation 生效

#### 真实联调中发现并修复的问题

在真实 `Claude Code` worker 联调中，发现当前 CLI 存在兼容性约束：

```text
Error: When using --print, --output-format=stream-json requires --verbose
```

已修复：

- `ClaudeCodeDriver` 的 execute / conclude 命令已补充 `--verbose`

### 当前未完成事项

#### 1. 真实项目联调尚未完成闭环确认

虽然结构化 trace 代码已落地，且静态验证通过，但在第一次真实项目联调过程中，测试项目 `appollo / proj_016` 未保留在当前持久化 DB 中；在 compose 重建后，当前 server 实际读取的持久化 DB 中只剩旧项目：

- `Calculator`
- `CO2`

因此，**尚未完成最终的 UI 端到端确认**，还需要重新创建一个测试项目，再验证是否真实出现：

- `tool_call`
- `tool_result`
- `command_start`
- `command_end`
- `usage`
- `agent_message`

#### 2. 当前状态结论

当前可以确认：

- 结构化 Execution Log 能力已经实现到代码层
- Claude stream-json 兼容问题已修复
- 黑板主架构未被耦合进 observability
- 最后一项待确认的是：真实运行时 UI 中是否稳定看到完整结构化事件流

### 受影响文件（本轮）

- `cairn/src/cairn/dispatcher/observability/trace.py`
- `cairn/src/cairn/dispatcher/observability/reporter.py`
- `cairn/src/cairn/dispatcher/tasks/common.py`
- `cairn/src/cairn/dispatcher/workers/base.py`
- `cairn/src/cairn/dispatcher/workers/adapters/codex.py`
- `cairn/src/cairn/dispatcher/workers/adapters/claudecode.py`
- `cairn/src/cairn/dispatcher/tasks/bootstrap.py`
- `cairn/src/cairn/dispatcher/tasks/explore.py`
- `cairn/src/cairn/dispatcher/tasks/reason.py`
- `cairn/src/cairn/dispatcher/config.py`
- `cairn/src/cairn/dispatcher/observability/redaction.py`
- `cairn/src/cairn/server/observability/models.py`
- `cairn/src/cairn/server/observability/redaction.py`
- `cairn/src/cairn/server/static/index.html`
- `dispatch_mock.yaml`

### 后续追加建议

后续每次更新本文件时，建议继续沿用以下格式追加：

- 日期 + 更新标题
- 背景
- 已完成变更
- 已完成验证
- 当前未完成事项/风险
