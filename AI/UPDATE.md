<!--
@ai: 本文件记录 Cairn 项目的增量更新。后续 Codex 会话在继续实现、联调或回溯问题前，应优先阅读本文件，以了解最近一次修改、验证结果与未完成事项。

维护约定：
- 每次有实质代码/架构更新时，按时间倒序追加一节。
- 每节至少包含：背景、已完成变更、验证结果、未完成事项/风险。
- 本文件记录的是“实际已落地或已确认”的更新，不写纯设想。
-->

# Cairn 更新记录

## 2026-06-05 · AI Profile 多模型下拉与 reasoning_type（已完成）

### 背景

`dispatch.yaml` 需要配置默认 `model_reasoning_effort`，项目创建页需要为 Bootstrap / Intent / Reason 分别选择 profile、model 和 reasoning type。同时一个 AI profile 应承载多个可选 model，而不是为同一 worker 的多个 model 生成多个 seeded profile。

### 已完成变更

- `WorkerConfig` 新增 `model_reasoning_effort`，取值限定为 `low | medium | high | xhigh`。
- `dispatch.yaml` 为 codex / claudecode worker 增加 `model_reasoning_effort: "high"` 示例；`workers.models` 继续作为手动静态模型列表。
- Dispatcher AI sync 改为一个 worker 只同步一个 seeded profile，并通过 `models` 字段把 `[默认模型 + workers.models]` 写入 Server 的 `ai_profile_models`。
- AI profile / project snapshot 增加 reasoning 字段：profile 保存默认 `model_reasoning_effort`，项目 selection 保存 `primary_reasoning_type`，snapshot 保存 `snapshot_reasoning_type`。
- Create Project / Replay AI Worker Chains 改为三列下拉：Profiles、Configured Model、Reasoning Type。
- Settings 的 AI profile 表单支持默认 reasoning 和手动多模型列表。
- Runtime overlay 会把项目 snapshot reasoning 写入 `CAIRN_MODEL_REASONING_EFFORT`；Codex 使用 `-c model_reasoning_effort=...`，Claude Code 使用 `--effort ...`。

### 验证结果

已通过：

- `cd cairn && uv run python -m unittest tests.test_ai_profile_bridge tests.test_ai_profile_flow tests.test_worker_cli_adapters`
- `cd cairn && uv run python -m unittest discover -s tests`
- `python -m compileall -q cairn/src/cairn cairn/tests`
- `git diff --check`
- `node --check` 校验从 `index.html` 抽取出的 `function cairnApp()`
- `ANTHROPIC_AUTH_TOKEN=test OPENAI_API_KEY=test uv run --project cairn python - <<'PY' ... DispatchConfig.load(Path('dispatch.yaml')) ...`

### 未完成事项/风险

- reasoning type 当前只暴露共同子集 `low | medium | high | xhigh`；未包含 Codex-only `minimal` 或 Claude-only `max`。
- 历史上已经生成的 `worker:model` seeded profiles 不会自动删除；后续可由 operator 在 Settings 中手动删除。

## 2026-06-05 · dispatch.yaml workers.models 静态多模型配置（已完成）

### 背景

需要允许一个 codex/claudecode worker 在不调用 provider 远程模型列表接口的前提下，声明多个可选模型供 AI Worker Chains 选择。同时 `env.CODEX_MODEL` / `env.ANTHROPIC_MODEL` 必须继续有效，并代表该 worker 的默认模型。

### 已完成变更

- `WorkerConfig` 新增可选 `models: list[str]`，加载时会 trim、拒绝空字符串、按原顺序去重。
- Dispatcher `_build_ai_sync_payload()` 会把 `env.CODEX_MODEL` / `env.ANTHROPIC_MODEL` 作为默认模型排在第一位，再追加 `workers.models` 中未重复的模型。
- 默认模型的 seeded profile 名称继续使用原 `worker.name`，兼容已有 profile 和项目选择。
- 配置额外候选模型时，Dispatcher 为每个额外模型生成一个 seeded profile，名称为 `worker.name:model`，由 Server 继续按 `seeded_from_worker` 幂等 upsert。
- Dispatcher 启动时会持续幂等同步 `dispatch.yaml` worker profiles；已有 catalog 不会阻止新增 `workers.models` 生成的新 seeded profiles 出现。
- `dispatch.yaml` 增加注释示例，明确 `models` 是手动静态列表，不触发远程模型发现。

### 验证结果

- 已新增单元测试覆盖 `models` 去重/空值拒绝、默认模型优先、多模型 payload 展开、单模型 legacy seed name 兼容。

### 未完成事项/风险

- `workers.task_types` 仍是 worker 级约束，适用于该 worker 展开的所有模型；如果未来需要“某个模型只允许 reason/explore”，需要新增模型级 task_types schema。

## 2026-06-05 · AI Worker Chains 改回手动模型配置（已完成）

### 背景

Create Project panel 的 AI Worker Chains 需要避免直铺所有 profiles，并且不再由 Dispatcher 调 provider `/v1/models` 远程获取模型列表。模型来源改为用户在 `dispatch.yaml` worker env 或 Settings 创建/编辑 AI profile 时手动填写的 `model` 字段。

### 已完成变更

- Create Project 的 AI Worker Chains 保留 `Bootstrap Model` / `Intent Model` / `Reason Model` 三个任务切换按钮。
- Profiles 区域从按钮直铺改为单个下拉列表，只展示可用 profile 标题。
- Model 区域改为只读 configured model，值来自当前 profile 的 `model`，不再读取 `profile.models` 缓存。
- 选择 profile 时，前端写入 `primary_profile_id` 和 `primary_model=profile.model`，fallback 仍保持空。
- Replay primary profile 选择同样改为使用 `profile.model`，不再优先使用 `profile.models[0]`。
- Dispatcher AI catalog sync 不再调用模型列表同步，也不会请求 provider `/v1/models` 或回写 `/ai-profiles/models-report`。
- 保留 `ai_profile_models` 表和 Server `/ai-profiles/models-report` 作为兼容遗留接口，不做破坏性迁移。

### 验证结果

已通过：

- `cd cairn && uv run python -m unittest tests.test_ai_profile_flow tests.test_ai_profile_bridge`
- `cd cairn && uv run python -m unittest discover -s tests`
- `python -m compileall -q cairn/src/cairn cairn/tests`
- `git diff --check`
- `node --check` 校验从 `index.html` 抽取出的 `function cairnApp()`

### 未完成事项/风险

- 每个 AI profile 当前只有一个手动配置的默认 `model`；如果未来需要一个 profile 多模型选择，应新增显式手动模型列表字段，而不是恢复 provider 远程抓取。

## 2026-06-05 · Execution Log 恢复与 Project Files 自动刷新（已完成）

### 背景

运行中发现两个 UI 可观测问题：Execution Log 列表突然全部消失，以及 Project Files 未正常列出 worker 运行时写入 `/mnt/project` 的文件。排查确认至少存在两类触发条件：Execution Log 只剩 `usage/thinking_tokens` 时会被默认过滤隐藏；旧 `INSERT OR REPLACE` 路径可能把 `llm_executions.event_count/last_event_at` 重置为 0/NULL，而事件表仍有数据。

### 已完成变更

- `server/observability/repository.py`
  - `create_execution()` 从 `INSERT OR REPLACE` 改为 `ON CONFLICT DO UPDATE`，避免重建 execution 时清空已有 event 聚合字段。
  - `list_executions()` 查询时从 `llm_execution_events` 聚合修正 `event_count`、`bytes_written`、`last_event_at`，可恢复历史已被重置的 execution 列表状态。
  - `finish_execution()` 在缺少 `process_end` event 时自动补一条去重的结束事件，保证取消/异常路径至少有一条默认可见日志。
- Graph 页 Execution Log
  - 增量拉取在空列表/强制刷新场景下可从 `after=0` 回填，避免 `llmLastSequence` 与后端 sequence 失配后永久空白。
  - 当原始事件存在但被当前过滤条件隐藏时，显示“events exist but filters hide them”提示，而不是误报 `No execution log yet`。
- Project Files
  - Graph 页面轮询时，如果当前停留在 Files tab，会自动 `loadProjectFiles(true)`，运行时新写入 `/mnt/project` 的文件无需手动刷新即可出现。
- 新增 `cairn/tests/test_observability_and_files.py`
  - 覆盖 execution 重建不丢 event、历史聚合修正、finish 自动补 `process_end`、Project Files 分类和下载路径安全。

### 验证结果

已通过：

- `cd cairn && uv run python -m unittest tests.test_observability_and_files tests.test_worker_cli_adapters`
- `cd cairn && uv run python -m unittest discover -s tests`
- `python -m compileall -q cairn/src/cairn cairn/tests`
- `git diff --check`
- `node --check` 校验从 `index.html` 抽取出的 `function cairnApp()`

### 未完成事项/风险

- `Project Files` 仍依赖 Server 可访问 `CAIRN_PROJECT_FILES_ROOT`，Dispatcher worker 必须把同一宿主目录挂载到 `/mnt/project`。
- 前端 Execution Log 合并逻辑仍没有独立 JS 单测；本次以后端和语法检查覆盖关键失效路径。

## 2026-06-05 · AI Worker Chains 模型选择卡片化（已被手动模型配置取代）

### 背景

项目创建页的 AI Worker Chains 需要从“展示大量 profile 细节 + primary/fallback 选择”调整为更直接的任务模型选择：`Bootstrap Model`、`Intent Model`、`Reason Model` 三类任务分别选择 profile 和该 profile 下的具体模型。模型列表由 Dispatcher 读取 provider API 后回写 Server，避免 Server / frontend 直接持有 provider token。

### 已完成变更

- 新增 `ai_profile_models` 表和迁移 `20260605_006_ai_profile_models`，用于缓存每个 AI profile 可选模型。
- Dispatcher 曾在 AI catalog sync 后 best-effort 请求模型列表，并通过 `POST /ai-profiles/models-report` 回写 Server；该行为已在后续“手动模型配置”变更中停止。
- `/ai-profiles` 和 `/projects/{project_id}/ai-profiles` 返回 profile `models` 字段；模型列表请求失败且没有新模型时只更新错误信息，不清空旧缓存。
- `AiProfileSelection` 新增 `primary_model`；项目快照的 `snapshot_model` 优先使用用户选定模型，并校验该模型必须属于 profile 缓存模型或 profile 默认模型。
- 项目创建页 AI Worker Chains 改为单卡片：顶部任务按钮切换 `Bootstrap/Intent/Reason`，左侧只显示 profile 标题，右侧显示当前 profile 可选模型；项目创建只提交 primary profile/model，fallback 保持空。
- Replay 选择保留原有形态，但 primary profile 选择会同步默认 `primary_model`，保持新字段兼容。
- 新增/更新测试覆盖模型列表拉取、Anthropic 请求头、模型缓存回写、项目快照模型覆盖和非法模型拒绝。

### 验证结果

已通过：

- `cd cairn && uv run python -m unittest tests.test_ai_profile_flow tests.test_ai_profile_bridge`
- `cd cairn && uv run python -m unittest discover -s tests`
- `python -m compileall -q cairn/src/cairn cairn/tests`
- `git diff --check`
- `node --check` 校验从 `index.html` 抽取出的 `function cairnApp()`

### 未完成事项/风险

- 当前版本不再使用 Dispatcher 远程模型缓存；Create Project 使用 AI profile 手动配置的 `model`。

## 2026-06-05 · 当前项目增量审查同步（已完成）

### 背景

对最新提交 `ab041ab Fix worker execution and reason scheduling` 做增量审查，重点覆盖 worker CLI 执行、Codex/Claude trace 解析、Execute Log 展示、reason 调度状态、SQLite 迁移和项目级 AI profile 选择。

### 审查结论

- 未发现会直接导致当前 worker/reason 调度不可用的 P0/P1 问题。
- 旧库升级模拟通过：从已有 `20260604_001_core_indexes`、`20260604_002_ai_profiles`、`20260604_002b_ai_profile_seed` 的数据库升级到当前 schema，可正常得到 `project_ai_profiles.task_type`、`projects.reason_run_id` 与 reason state migration 记录。
- `Codex exec resume` 已不再携带 resume 不支持的 `--add-dir`；普通 `codex exec` 仍保留 `--add-dir` 供 skill 访问。
- Execute Log 前端逻辑已按当前实现过滤 Codex `turn.started`，保留 `turn.completed`，并把同一命令的 `command_start` / `command_end` 合并为一张卡片。
- Claude `system: thinking_tokens` 现在归类为 `usage`，不再作为普通 Execute Log system 卡片展示。
- 项目创建支持 `bootstrap`、`explore`、`reason` 三类任务分别保存 AI profile selection；legacy `ai_profiles` 输入仍映射为单一 legacy selection 以兼容旧客户端。

### 残余风险

- `cairn/src/cairn/dispatcher/observability/trace.py` 中 Codex stdin notice 判断仍使用原始 `line`，不是已去 ANSI 的 `plain`。如果 CLI 输出带 ANSI 控制字符的 `Reading additional input from stdin...`，仍可能被记录为 `trace_parse_error`。建议改为 `if plain == "Reading additional input from stdin...":` 并补 ANSI 回归测试。
- `GET /projects/{project_id}/ai-profiles` 的兼容字段 `selection` 固定返回 `selections.explore`。当三类任务选择不同时，旧客户端读取 `selection` 会看到 explore selection，而不是完整任务级配置；新客户端应使用 `selections` 或 `snapshots`。
- 前端 Execute Log 的 `mergeLlmCommandEvents()` 没有 JS 单测覆盖；当同一 execution/phase 下缺少 `call_id` / `item_id` 且连续重复相同命令时，退化到 command text key 可能错配 start/end。建议补前端逻辑测试覆盖 `turn.*` 过滤、`thinking_tokens` 归类、重复 command 合并边界。

### 验证结果

已通过：

- `cd cairn && uv run python -m unittest discover -s tests`
- `python -m compileall -q cairn/src/cairn cairn/tests`
- `git diff --check`
- 手工临时 SQLite 旧库升级模拟

## 2026-06-04 · Worker CLI 非交互协议收敛（Claude `--print` + Codex stdin notice）（已完成）

### 背景

项目运行时出现 `Reading additional input from stdin...`，表面看像 dispatcher / worker 卡死。实际排查后确认：

- 该行来自 `codex exec` CLI 0.118.0，自身会在启动时提示它扫描 stdin 是否有追加输入。
- Dispatcher 容器 exec 已是 `stdin=False, tty=False`，不是 Cairn 主动把 stdin 挂进去了。
- Claude Code 2.1.98 的帮助已明确把非交互模式定义为 `--print`；仓库旧代码仍在用 `-p`。

### 已完成变更

- `cairn/src/cairn/dispatcher/workers/adapters/claudecode.py`
  - `build_execute()` / `build_conclude()` 从旧的 `-p` 切到显式 `--print`
  - 保留 `--output-format stream-json`、`--verbose`、`--dangerously-skip-permissions`
- `cairn/src/cairn/dispatcher/observability/trace.py`
  - `CodexTraceParser` 新增对非 JSON 行 `Reading additional input from stdin...` 的识别
  - 不再把它记成 `trace_parse_error`，而是降级为 `system_event`
  - metadata 带 `notice_type=stdin_scan`
- 新增回归测试 `cairn/tests/test_worker_cli_adapters.py`
  - 校验 Claude adapter 命令行必须包含 `--print`
  - 校验 Codex stdin notice 被当成 `system_event`
  - 校验该 notice 后跟随 JSONL 事件时，trace 解析不中断

### 验证结果

已通过：

- `PYTHONPATH=cairn/src cairn/.venv/bin/python -m compileall -q cairn/src/cairn`
- `PYTHONPATH=cairn/src cairn/.venv/bin/python -m unittest discover -s cairn/tests -p 'test_worker_cli_adapters.py' -v`
- `PYTHONPATH=cairn/src cairn/.venv/bin/python -m unittest discover -s cairn/tests -p 'test_ai_profile_bridge.py' -v`

### 未完成事项/风险

- `Reading additional input from stdin...` 现在只被视为 Codex CLI 提示语，不单独构成阻塞或失败证据。真实 timeout / API 重试仍按原有 `communicate()` / returncode / structured trace 规则判定。
- 若后续要彻底消除这行提示，可继续研究 `codex exec` 是否存在明确禁止 stdin 扫描的官方参数；当前版本 `codex exec -h` 未暴露该开关。

## 2026-06-04 · Compose build graph 纳入 dispatcher 依赖的 worker image（已完成）

### 背景

`dispatch.yaml` 的 `container.image` 已切到本地 tag `cairn-worker-container:mcp-camoufox`，但此前 `docker compose up --build` 只会构建 `cairn-app`，不会构建 dispatcher 真正依赖的 worker image，导致首次启动前仍需手工执行 `docker build ./container -t cairn-worker-container:mcp-camoufox`。

### 已完成变更

- `docker-compose.yaml` 新增 one-shot helper service `cairn-worker-image`：
  - `build.context: ./container`
  - `image: cairn-worker-container:mcp-camoufox`
  - `command: ["true"]`
  - `restart: "no"`
  - `network_mode: "none"`
- `cairn-dispatcher.depends_on` 追加 `cairn-worker-image: { condition: service_completed_successfully }`，使 `docker compose up --build cairn-dispatcher` 与全量 `docker compose up --build` 都先把 worker image 纳入 build graph，再启动 dispatcher。
- `README.md` 更新 compose/manual 启动说明：
  - Compose 路径改为“自动构建 `cairn-worker-container:mcp-camoufox`”
  - Manual 路径显式保留 `docker build ./container -t cairn-worker-container:mcp-camoufox`
- `container/README.md` 增补说明：compose 现在会自动构建同名 tag，手工 build 仅用于单独调试 / smoke test。
- `AI/PROJECT_OVERVIEW.md` 同步更新 compose 构建图、关键文件说明和部署路径。

### 验证结果

已通过：

- `docker compose config`
  - 展开结果包含 `cairn-worker-image`
  - `cairn-dispatcher.depends_on` 同时包含 `cairn-server` 与 `cairn-worker-image`
- `docker compose build cairn-worker-image`
  - 成功构建并产出 `cairn-worker-container:mcp-camoufox`
- `docker inspect docker.io/library/cairn-worker-container:mcp-camoufox --format '{{.Id}} {{json .RepoTags}}'`
  - 确认本地 tag 存在

### 未完成事项/风险

- `cairn-worker-image` 是一次性 helper service，职责仅是把 worker image 纳入 compose build graph；真正项目 worker 仍由 dispatcher 通过宿主 Docker socket 动态创建。这保持了现有调度与黑板架构边界，不引入新的常驻控制面进程。
- `docker compose config` 会把 `.env` 中的真实密钥展开到 stdout；排查时应避免把原始输出复制到日志、issue 或聊天记录。

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

## 2026-06-03 · 接入 hello_js_reverse_skill + camoufox-reverse-mcp + 项目级代理 (已完成)

### 背景

用户要求新增前端 JS 逆向工作流(hello-js-reverse + camoufox-reverse-mcp browser MCP)和系统级代理池管理。
代理统一在 Server Settings 页面管理(socks5/http/https)，新建项目时选择，Dispatcher 在 worker 容器启动时注入对应 env 变量。

### 已完成变更

- DB: 新增 `proxies` 表(id/name/type/host/port/username/password/created_at/updated_at) + `projects.proxy_id` 渐进式 ALTER TABLE + ON DELETE SET NULL
- 模型: `ProxySummary`(列表/项目详情，不含 password) / `ProxyConfig`(GET /proxies/{id}，含凭据) / `ProxyCreate` / `ProxyUpdate`
- Server API: `cairn/src/cairn/server/routers/proxies.py` — GET/POST/PUT/DELETE /proxies/*
- UI: Settings modal 扩展为代理管理面板(添加/编辑/删除)；New Project 新增 Outbound Proxy `<select>` (默认直连)
- Dispatcher 注入: `_proxy_config_to_env()`(socks5→ALL_PROXY, http/https→HTTP_PROXY+HTTPS_PROXY+NO_PROXY)；`_resolve_project_proxy()` 每次调度刷新；`_resolve_proxy_env()` 传给 `ContainerManager(proxy_resolver=...)`；startup-healthcheck 容器不走代理
- 两端 observability redaction: BUILTIN_PATTERNS 覆盖 `HTTP_PROXY=` / `HTTPS_PROXY=` / `ALL_PROXY=` / `SOCKS5_PROXY=` env 赋值
- `dispatch.yaml`: 注册 `camoufox-reverse` MCP server(stdio, 带 CAMOUFOX_PROFILE_DIR / CAMOUFOX_HEADLESS) + `hello-js-reverse` skill
- `container/Dockerfile`: 安装 `camoufox-reverse-mcp` + COPY skill 到 workspace
- `capabilities/skills/hello-js-reverse/SKILL.md`: JS 逆向 skill 文档(profile / proxy / 完成标准)
- 测试: `cairn/tests/test_proxy_settings.py` 28 用例覆盖 schema / env 转换 / redaction / 缓存 / DB CRUD / FK cascade

### 验证结果

- `compileall cairn/src/cairn` — clean (0 warnings/errors)
- `DispatchConfig.load(dispatch.yaml)` — OK(3 MCP servers: kali-server-mcp / metasploit-mcp / camoufox-reverse; 26 skills)
- `unittest discover` — 63 tests OK (原有 35 + 新 28)

### 未完成事项/风险

- 代理密码明文存储于 SQLite;加密列为后续
- `container/Dockerfile` 需构建后才能使用 camoufox-reverse-mcp 和 hello-js-reverse skill
- HTTP MCP transport 的 TLS 软提示按用户要求跳过
- token 轮换后 in-flight worker 不会主动失效(靠 container.completed_action 自然回收)

## 2026-06-03 · 修复 startup healthcheck 在 macOS Docker Desktop 上的 bind mount 权限错误（已完成）

### 背景

`docker compose up cairn-dispatcher` 在 macOS Docker Desktop 上跑 startup healthcheck 时失败,worker 容器内的 probe 写 `/mnt/project/.cairn-write-test-...` 报 `Permission denied` (exit 3)。本仓库 CI 用的 Linux runner 不会出现这个错,用户本机是 macOS,首次落地才暴露。

### 根因(经过 `docker run --user=...` 实测校正)

macOS Docker Desktop 的 bind mount 走 VirtioFS 桥接,**write syscall 在容器内非 root 用户(无论 host 文件 mode 是什么、容器用户 UID 是不是 file owner)一律拒绝**。我最初以为是简单的 host UID 不匹配,推荐 `user: "501:20"`(host 用户 UID),但用 `docker run --user=501:20 -v ...:/mnt/project alpine sh -c 'touch /mnt/test'` 真机验证,**仍然 Permission denied**,即使容器内 `id` 是 `uid=501 gid=20`、`/mnt/project` 显示 `drwxrwx`。改 `user: "0:0"` 立即 OK。

这是 macOS Docker Desktop + VirtioFS 的内核层已知行为,跟 host 文件 mode、容器用户 UID、bind mount 选项都无关。具体到本仓库:

- host `datas/project-files` 实际权限:`drwxrwxrwx jmac staff`(UID 501, GID 20, mode 0o777) — `ls -ld` 已确认
- worker 容器以 image 内 `USER kali`(UID 1000)运行,或即使改成 `user: "501:20"`,在 macOS VirtioFS 下都写不进
- **唯一可行方案**: `user: "0:0"` (root)

`cairn/src/cairn/dispatcher/runtime/containers.py::_ensure_world_writable_dir` 在 host 端做的 `os.chmod 0o777` 在 macOS 上也无效——dispatcher 自己在容器内以非 root 跑,不能 chmod owner=不同 UID 的 host 文件(EPERM)。但这个不是 bug 主因,主因是 VirtioFS 行为。

### 已完成变更

**Schema** (`cairn/src/cairn/dispatcher/config.py`)

- `ContainerConfig` 加 `user: str | None = None`,docstring 写清 macOS 必须设 / Linux 可选 / 不设保留旧行为
- 不做格式校验,直接透传给 `docker.containers.run`

**Runtime** (`cairn/src/cairn/dispatcher/runtime/containers.py`)

- `ContainerManager._create_container` 和 `_create_startup_container` 两条路径都把 `user=self._config.user` 透传到 `self._client.containers.run(..., user=...)`。Docker SDK 接受 `None` 等效不传
- `_ensure_world_writable_dir` 把 `os.chmod` 包 `try/except PermissionError as exc: LOG.warning(...)`——chmod 失败不再 crash 进程。Probe 才是真测试,chmod 是 best-effort

**dispatch.yaml**

- `container:` 段加注释 `# user: "0:0"`,说明 macOS Docker Desktop VirtioFS 下必须 root,Linux 可不设或用 host uid:gid

**AI 文档**

- `AI/CODEBASE_ANALYSIS.md` §4 schema 表 `ContainerConfig` 行加 `user`
- `AI/CODEBASE_ANALYSIS.md` §9 config keys 表新增 `container.user` 行
- `AI/PROJECT_OVERVIEW.md` 新增 "## 部署环境前置条件" 小节,讲清 macOS / Linux 区别

**测试** (`cairn/tests/test_bind_mount_user_uid.py`,8 case)

- `ContainerConfigUserSchemaTests` (4): 默认 `user is None` / `"501:20"` 通过 / 空字符串拒绝 / 任意非空字符串通过(透传 Docker)
- `ContainerUserRuntimeTests` (3): mock docker client 验证 `user=None` 时 `docker.containers.run` 不传 `user` kwarg / `user="501:20"` 时传 `user="501:20"` / 两条路径(create + startup)都验证
- `EnsureWorldWritableDirEpermTests` (1): `os.chmod` 抛 `PermissionError` 时 `_ensure_world_writable_dir` 记 warning, 不 raise

### 验证结果

- `compileall -q cairn/src/cairn` 0 错误
- `unittest discover -s tests -p 'test_*.py'` 24 旧测试 + 8 新测试 = 32/32 通过
- `DispatchConfig.load(dispatch.yaml)` 成功,`cfg.container.user is None`(向后兼容)

### 用户操作

用户需在 `dispatch.yaml` 显式 uncomment `# user: "0:0"`(或直接 uncomment 不改,推荐值就是 root)。改完 `docker compose up cairn-dispatcher`,startup healthcheck 即通过。

如迁到 Linux Docker Engine,改回 host `uid:gid`(`id -u` / `id -g`)即可,不需要 root。

### 关键教训

**不要相信"host 文件 mode 0o777 = 任何人都能写"的隐含假设**。macOS Docker Desktop + VirtioFS 不走标准 POSIX 检查,只允许 root 通过。**任何"修 host chmod"的方案在 macOS 上都是无效猜测**。正确做法是 `docker run --user=...` 真机验一遍再下结论。

### 未完成事项 / 风险

- **不在 dispatcher 内自动探测 host UID**——dispatcher 自己在容器内,`os.getuid()` 拿到的是容器内 UID 不是 host UID。可靠做法只能 operator 显式配。
- **不动 Dockerfile 的 `USER kali` UID**——锁 UID 1000 会影响 Linux 部署兼容性(Linux host 上 `jmac` 经常是 UID 1000,会冲突)。
- **probe 仍用 bind mount 写测试文件做健康检查**——这是有意的,真要判断"能不能写"只能真写一次。
- **macOS 上 worker 容器内是 root**——网络已 `cairn` 网络隔离,bind mount 只暴露 `/mnt/project`(operator 控盘),image 内 `kali` 已有 `NOPASSWD:ALL`,实际权限等级等同 root,这个让步在 macOS 上是必要的;Linux 上仍可设 host uid:gid,无需 root。
- **VirtioFS 行为可能随 Docker Desktop 版本变化**——如果未来 Docker Desktop 修了 VirtioFS 允许非 root 写,可以把推荐值改回 host uid:gid。

---

## 2026-06-03 · HTTP (Streamable HTTP) MCP transport 接入（已完成）

### 背景

MCP catalog 之前只支持 `stdio` (容器内 spawn 子进程),与既有的 Kali/Metasploit stdio 桥一致。但实际部署里很多 MCP server 是独立的 HTTP 服务(可能是 host 上的进程,另一台机器上的服务,或 SaaS)。本轮新增 `transport: "http"`,允许 `McpServerCapabilityConfig` 走 Streamable HTTP (MCP 2025-03-26),并补齐 token 注入、observability 脱敏、可达性预检三处安全/可观测关注点。

### 已完成变更

**Schema** (`cairn/src/cairn/dispatcher/config.py`)

- `McpServerCapabilityConfig.transport: Literal["stdio", "http"] = "stdio"`
- `command` 改为可选;新增 `url: str | None`、`bearer_token_env: str | None`、`healthcheck_timeout: float = 1.0`
- `field_validator` 校验 `url` 必须以 `http://` 或 `https://` 开头;`model_validator` 保证:
  - `stdio` 必须有 `command`,不允许 `bearer_token_env`
  - `http` 必须有 `url`,`bearer_token_env` 引用到的 env var 必须在 `os.environ` 中(否则 `ValueError`,加载即失败,不是延迟到运行时)
- 类 docstring 写清两 transport 的安全/性能取舍
- `bearer_token_env` 加入 `_INTERPOLATION_SKIP_KEYS`,不被 `${ENV_VAR}` 插值吞掉

**Capabilities 注入** (`cairn/src/cairn/dispatcher/capabilities.py`)

- `_mcp_config_detail` 按 transport 分支:
  - `stdio`: 既有行为(写 `command` / `args` / `env`)
  - `http`: 写 `type: "http"` + `url`,`bearer_token_env` 存在则**现场拼** `headers.Authorization: Bearer <token>`,序列化后立即释放,不长期持有,不进 `WorkerExecutionContext`
- `_mcp_detail` 不再含 `headers`,避免 token 通过 Codex adapter context 泄漏
- 新增 `_probe_http_url(url, timeout)` — `socket.create_connection((host, port), timeout=timeout)`,在 `inject_project_capabilities` 写 `mcp.json` 前对 http 类型 server 做探活;失败 → 跳过该 mcp 并 `injection.errors.append(f"mcp_server:<id>: http probe failed ...")`,UI 已有 `unavailable` 展示
- `catalog_payload(...).available` 仍为 "config 有效",不接探活结果(探活 per-task,不 per-catalog)

**Codex adapter** (`cairn/src/cairn/dispatcher/workers/adapters/codex.py`)

- `_capability_args` 分支:
  - `http`: `-c mcp_servers.<id>.url=...` + 可选 `-c mcp_servers.<id>.bearer_token_env_var=<NAME>`,由 Codex 自身读 env
  - `stdio`: 既有行为

**Worker container env 传播** (`cairn/src/cairn/dispatcher/runtime/containers.py` + `scheduler/loop.py`)

- `ContainerManager.__init__` 多接 `bearer_token_env_keys: list[str]`
- 新增 `_bearer_token_environment()` 在 dispatcher 进程 `os.environ` 中按名取值,与 `common_env` 合并后通过 `docker.containers.run(environment=...)` 传给容器
- `DispatcherLoop` 启动时把 `cfg.capabilities.mcp_servers` 中所有 `bearer_token_env` 抽出来传给 `ContainerManager`
- 这要求 dispatcher 进程 `os.environ` 也有该 var,已由 `DispatchConfig.load()` 的 model_validator 强校验

**Observability redaction** (`cairn/src/cairn/dispatcher/observability/redaction.py` + `cairn/src/cairn/server/observability/redaction.py`)

- 升级 BUILTIN bearer 正则为 `(?i)(?<![A-Za-z_])(Authorization"?\s*:\s*"?Bearer"?\s+)[A-Za-z0-9._~+/=-]+`
- 覆盖 `Authorization: Bearer <tk>` / `Authorization: "Bearer <tk>"` / JSON 编码 `"Authorization": "Bearer <tk>"`,不命中 `XAuthorization` 等
- dispatch.yaml `observability.redaction_patterns` 默认加 `Authorization: Bearer \\S+`,用户可继续追加

**dispatch.yaml / .env.example**

- dispatch.yaml 增加一个 http MCP server 的注释样例(默认未启用,留给用户 uncomment 改)
- `.env.example` 增加 `MCP_AUTH_TOKEN=` 占位 + 末尾 SECURITY 注释(不要把 `.env` 内容贴到 issue tracker / IM / 邮件 / 截图;轮换 `MCP_AUTH_TOKEN` 后 in-flight worker 需自然回收,见 `container.completed_action`)

**测试** (`cairn/tests/test_mcp_http_transport.py`,24 case)

- `McpServerCapabilityConfigHttpTests` (9): stdio 缺 `command` / http 缺 `url` / url scheme 校验 / bearer_token_env env 未设 → ValueError / bearer_token_env env 已设 → 通过 / healthcheck_timeout bounds / stdio 不接受 bearer_token_env / http 仅 url / stdio 不带 transport 字段
- `DispatchConfigInterpTests` (1): bearer_token_env 引用到的 env 名不会被 `${VAR}` 插值吞掉
- `McpInjectionTests` (5): stdio detail shape / http detail with bearer resolves token / http detail without bearer / mcp_detail 不含 transport & bearer_env / mcp.json 混合 transport
- `HttpProbeTests` (3): localhost 可达 / 不可达 host 返回 False / 无 host URL 返回 False
- `CodexAdapterHttpTests` (3): stdio 走 command / http 走 url + bearer_token_env_var / http 无 bearer 只走 url
- `RedactionTests` (3): dispatcher 模块 bearer token 被脱敏 / server 模块 bearer token 被脱敏 / JSON 形式 `Authorization` header 也被脱敏

### 验证结果

- `compileall -q cairn/src/cairn` 0 错误
- `unittest tests.test_mcp_http_transport` 24/24 通过
- `DispatchConfig.load(dispatch.yaml)` 在 `ANTHROPIC_AUTH_TOKEN / OPENAI_API_KEY / CAIRN_REMOTE_SSH_HOST / USERNAME / PASSWORD` 这些 env 设上后成功加载

### 未完成事项 / 风险

- **TLS 软提示未做** — 用户在上一轮明确"不对 http 访问告警",所以没在 schema 加 `warnings` 字段也没在 dispatch.yaml 注释里写 http→https 升级提示。后续若需要,可单独 PR 加 `McpServerCapabilityConfig.warnings: list[str]`。
- **SSRF 未做** — schema 接受任意 `http://` 与内网 URL;worker 容器可通过 `cairn` network 触达内网 MCP。SSRF 是 deployment / egress 过滤问题,留作后续。
- **多 URL / failover** — schema 仍为单 `url: str`,不支持主备轮询。需要时升 `urls: list[str] + failover: bool`,向后兼容(`url` 退化为单元素 `urls`)。
- **Basic auth / OAuth / mTLS** — 未做;需要时 schema 升为 `auth: {type, ...}` discriminated union,`type=basic` / `oauth2` / `mtls`,向后兼容 `type=none`(默认)。
- **Token 轮换不主动失效 in-flight worker** — 依赖 `container.completed_action` 自然回收;`.env.example` SECURITY 注释已写明。
- **真实 Codex CLI 字段验证** — `mcp_servers.<id>.bearer_token_env_var` 这个 Codex CLI 字段名来自 MCP 文档与社区实践,未在真机 CI 跑通(本仓库的 worker container 没有真实 Codex CLI)。**首次联调时需实际起一个 HTTP MCP server,跑一次 bootstrap 任务,确认 Codex worker 真的能通过这个 env 拿 token 调通。** 若 Codex CLI 实际字段名不同,改 codex adapter 即可,不影响其他模块。
- **网络可达性** — HTTP MCP server 在 host 上时,worker 容器默认走 `cairn` docker network,无法直接访问 host `127.0.0.1`。部署者需:把 host 端口 publish 到 cairn network 上的 sidecar / 反代,或改 `container.network_mode: host`(本项目不自动改)。dispatch.yaml 注释里已写。

---

## 2026-06-03 · dispatch.yaml 密钥清理 + 增量同步 attachments/files/replay（已完成）

### 背景

`dispatch.yaml` 在 2026-06-02 提交的真实运行配置中保留了真实 API key、SSH 密码等敏感字段；同 commit 起的若干工作又把若干个新模块（attachments / files / replay / container MCP stdio 桥）落到了代码里。本次按"先处理密钥，再增量同步 AI 文档"两步推进。

### 已完成变更

- `cairn/src/cairn/dispatcher/config.py` 新增 `${ENV_VAR}` 插值支持：
  - `_ENV_VAR_RE` 匹配 `${NAME}` 形式（仅大写字母/下划线/数字）。
  - `_interpolate_env_data()` 在 `DispatchConfig.load()` 入口处递归遍历 YAML 数据，替换所有字符串中的 `${ENV_VAR}`；未设置的环境变量会立刻抛错并带 YAML 路径。
  - 不动 `{project_id}` 等 dispatcher 模板占位符，仍由 `prepare_*_data` 解析。
- `dispatch.yaml`：
  - 真实 SSH 主机/用户名/密码 → `${CAIRN_REMOTE_SSH_HOST}` / `${CAIRN_REMOTE_SSH_USERNAME}` / `${CAIRN_REMOTE_SSH_PASSWORD}`。
  - claudecode token → `${ANTHROPIC_AUTH_TOKEN}`。
  - codex token → `${OPENAI_API_KEY}`。
  - `bind_mounts.host_path` 从机器绝对路径改为相对路径 `./datas/attachments` 与 `./datas/project-files/{project_id}`，由 `_resolve_bind_mount_host_path()` 相对 `dispatch.yaml` 解析。
- 增量同步 AI 文档：
  - `AI/ARCHITECTURE.md`：§1 目录树补 `attachments.py / files.py / replay.py`；§5 Cypher 表移除 `cypher-flag-oob`；§8 API 概览补 Attachments / Files / Replay 三组端点；§9 dispatch.yaml 示例用 `${...}` 形式与新增 MCP；§10 密钥风险更新为"已迁移"。
  - `AI/CODEBASE_ANALYSIS.md`：ER 图补 `PROJECT_CAPABILITIES / PROJECT_ROLES / REPLAY_RUNS / REPLAY_FACT_MAP / REPLAY_STEPS` 五张表；§3 加 attachments / files / replay 三个 router 子节；§4 加 env 插值说明、`advance_replay_run` 协议方法、`_advance_replay_project` 调度钩子。
  - `AI/PROJECT_OVERVIEW.md`：§Cypher Agent 移除 `cypher-flag-oob`；§本地资源目录示例切换为 kali-server-mcp / metasploit-mcp；§关键文件速查补三个新 router、container/{Dockerfile,AGENTS.md,README.md,bin/*-mcp-stdio}；§敏感信息处理更新为 `${ENV_VAR}` 形式与 `DispatchConfig.load()` 行为；§后续修改建议加新模块入口。
  - 本文件追加本条记录。

### 架构边界

- `${ENV_VAR}` 插值发生在 YAML 解析之后、`pydantic` 校验之前，行为对所有 router / worker / capability / role 透明。
- 仍然不持久化任何 secret：catalog / project_capabilities / project_roles 表里都只存 ID 与 sha256，token 必须由环境注入。
- Replay 走的是"按原项目 step 顺序复演"，不调用任何 LLM 接口；只创建新 intent + 等待 worker 产出新 fact，所以它与 capability / role 控制面不交叉。
- Attachments 自动落 Hint，Hint 写盘路径在 `datas/attachments/{project_id}/`，worker 容器内挂载点固定为 `${CAIRN_WORKER_ATTACHMENTS_ROOT}`（默认 `/mnt/attachments`）。

### 验证结果

- `PYTHONPATH=cairn/src python3 -m compileall -q cairn/src/cairn` 通过。
- `DispatchConfig.load(Path('dispatch_mock.yaml'))` 通过。
- `DispatchConfig.load(Path('dispatch.yaml'))`：
  - 未设环境变量时抛 `ValueError: dispatch.yaml.remote_support.ssh.host references ${CAIRN_REMOTE_SSH_HOST} but environment variable is not set`。
  - 设 `CAIRN_REMOTE_SSH_HOST / CAIRN_REMOTE_SSH_USERNAME / CAIRN_REMOTE_SSH_PASSWORD / ANTHROPIC_AUTH_TOKEN` 后加载成功，`remote_support.ssh.password` 与 `workers[0].env.ANTHROPIC_AUTH_TOKEN` 都正确替换。

### 未完成事项/风险

- 本次只清理 `dispatch.yaml` 当前文件，git 历史里仍有 `sk-d04ac7b031c648c7ad66a6fad48c0d0e` 与 `2sM4VkT4JczzaiNW`。这两个值已经在 DeepSeek 控制台与对应 SSH 主机侧轮换/失效后，可考虑用 `git filter-repo` 重写历史；如不重写，建议在仓库 README/安全策略中显式声明"已知历史密钥已失效"。
- `docker-compose.yaml` 的 `CAIRN_ATTACHMENTS_ROOT / CAIRN_PROJECT_FILES_ROOT` 仍写死机器绝对路径 `/Users/jmac/Documents/GitHub/Cairn/datas/...`；本轮没改，原因是它们需要和容器内 bind-mount target 路径保持一致，跨机器时由部署方调整。
- `files.py` / `replay.py` 仍处于工作树未提交状态（untracked / modified），其 API 形态可能在 commit 前再调整；如果 commit 前有 breaking change，需要再回同步 ARCHITECTURE.md §8 的表格。
- 推进 replay 的 `_advance_replay_project` 没有处理 Server 返回 5xx 之外的所有 transient 错误（如 503），下一步应参考 `_dispatch_reason` 的一致重试策略。


## 2026-06-03 · bash 风格 env 默认值 + docker compose `.env` / `env_file` 接入（已完成）

### 背景

上一轮把 `dispatch.yaml` 的敏感字段改为 `${ENV_VAR}` 引用，但实现里“未设就抛错”的策略让用户必须把所有 5 个变量都设上才能启动 Dispatcher（包含暂时用不到的 SSH 三个）。本轮加上 bash 风格默认值语法，并把 docker compose 的 `.env` + `env_file` 通路补齐。

### 已完成变更

- `cairn/src/cairn/dispatcher/config.py`:
  - 正则升级为 `\${(?P<name>[A-Z_][A-Z0-9_]*)(?:(?P<colon>:)?-(?P<default>[^}]*))?\}`，支持 `${VAR}` / `${VAR:-default}` / `${VAR-default}` 三种语法。
  - 替换函数对应三种分支：`${VAR}` 未设报错；`${VAR:-default}` 在 unset 或空时取 default；`${VAR-default}` 仅在 unset 时取 default。
  - 19 个边界用例测试全部通过（覆盖 unset/空/已设、字符串拼接、未知前缀 `$NOT_REPLACED`、默认含空格等）。
- `dispatch.yaml`：`remote_support.ssh.{host,username,password}` 改为 `${CAIRN_REMOTE_SSH_*:-}` 形式，允许不设；`RemoteSupportConfig.ssh.is_complete` 在三个字段为空时返回 `False`，SSH 支持自动禁用，`CAIRN_REMOTE_SSH_*` 不会被注入 worker env。`ANTHROPIC_AUTH_TOKEN` 与 `OPENAI_API_KEY` 仍是无默认形式（强制设置）。
- `docker-compose.yaml`：`cairn-dispatcher` 服务加 `env_file: - .env`，从项目根 `.env` 注入密钥。`cairn-server` 的现有 `environment:` 块不动（它本身不需要密钥）。
- `.gitignore`：新增 `.env`。
- `.dockerignore`：新增 `.env`（避免 `.env` 进入镜像构建上下文）。
- 新建 `.env.example`：已提交到 git 的密钥模板，标注 `ANTHROPIC_AUTH_TOKEN` / `OPENAI_API_KEY` / SSH 三个变量。
- 增量同步 `AI/PROJECT_OVERVIEW.md` §敏感信息处理（新增语法表 + direnv 流程 + docker compose 流程），`AI/PROJECT_OVERVIEW.md` §关键文件速查（补 `.env.example`），`AI/CODEBASE_ANALYSIS.md` §4 `${ENV_VAR}` 插值（升级为 bash 风格说明）。
- 本文件追加本条记录。

### 架构边界

- `${ENV_VAR}` 插值仍只发生在 `DispatchConfig.load()` 入口，对所有 router / worker / capability / role 透明。
- Server DB / API 仍不持久化任何 secret；token 必须由 `os.environ` 注入（直接设、`.env`、direnv、CI secret 等任意途径都行）。
- 密码默认值在 `dispatch.yaml` 里以 `${VAR:-}`（空默认）出现，从不写真值；LLM token 仍以无默认形式要求必须设置。
- 部署者用 `.env` 喂入真实密钥，但 `.env` 不进 git、不进 Docker build context，只在容器运行时被 compose 读出。

### 验证结果

- `PYTHONPATH=cairn/src python3 -m compileall -q cairn/src/cairn` 通过。
- `_interpolate_env_string` 19 个用例全过（覆盖 unset / 空 / 已设 / 字符串拼接 / 前缀 `$` / 默认值含空格等）。
- `DispatchConfig.load(Path('dispatch.yaml'))`:
  - 不设任何 env → 抛 `ValueError: dispatch.yaml.workers[0].env.ANTHROPIC_AUTH_TOKEN references ${ANTHROPIC_AUTH_TOKEN} but environment variable is not set`（LLM token 必设；SSH 三个空默认后不再报错）。
  - 仅设 `ANTHROPIC_AUTH_TOKEN` / `OPENAI_API_KEY` → 加载成功，`remote_support.ssh.is_complete=False`，SSH 自动禁用。
  - 设齐 `CAIRN_REMOTE_SSH_*` 与 `ANTHROPIC_AUTH_TOKEN` / `OPENAI_API_KEY` → 加载成功，`remote_support.ssh.is_complete=True`，SSH 启用。
- `docker compose config` 在 `.env` 存在时正确 merge：`cairn-dispatcher.environment.ANTHROPIC_AUTH_TOKEN=sk-REPLACE-ME`、`cairn-dispatcher.environment.OPENAI_API_KEY=sk-REPLACE-ME`。
- `git check-ignore -v .env.example` 不返回任何规则，确认 `.env.example` 不被 `.env` 规则误忽略。

### 未完成事项/风险

- `.env` 文件本身仍可能在编辑器/IDE 同步、截图、复制粘贴时泄到 git 外。`AI/UPDATE.md` 第 132 行的密钥轮换/失效建议仍然适用。
- 当前只支持 `${VAR}` / `${VAR:-}` / `${VAR-}` 三种语法。bash 的 `${VAR:=word}`（赋值默认）、`${VAR:?msg}`（带错误信息报错）、`${VAR:+word}`（反用）暂未实现；如果之后需要，regex 多加一组分支即可，行为与 `os.environ` 一一对齐。
- `docker compose config` 在缺 `.env` 时会硬失败（`stat ... no such file or directory`）。文档已要求 `cp .env.example .env` 后再 `docker compose up`，但首次启动如果忘了 copy 会被这条硬卡住。可以考虑改成“缺 .env 时给空 env”，但默认 compose 行为对运维更安全（显式 fail fast）。


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
