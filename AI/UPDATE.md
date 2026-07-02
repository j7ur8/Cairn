<!--
@ai: 本文件记录项目分析的变更历史。每次运行 project-review 技能时，新增的变更摘要会追加到本文件顶部。
请勿手动编辑本文件 — 由 AI 自动维护。
-->

# 更新日志

## 2026-07-02 — AI 文档与命名检查同步

- 同步 `CODEBASE_ANALYSIS.md` 当前快照：FastAPI route decorator 计数更新为 88，顶层 `test_*.py` 文件数更新为 58，并补充 `GET /projects/{project_id}/graph` 和 `GET /projects/{project_id}/role` API 覆盖。
- 修正文档结构与注意事项：移除不存在的顶层 `cairn/src/cairn/observability/` 包描述，改为分别记录 server/dispatcher/shared observability 模块；同步当前 Alembic head 为 `0009_drop_intent_metadata`。
- 同步 CI/guardrail 说明：`CODEBASE_ANALYSIS.md` 记录 `node scripts/check_frontend.mjs` 前端静态检查；`check_naming.py` 对 `capabilities/**/tools/vendor/**` 下 vendored YAML 文件名放行，`NAMING.md` 保留首方 YAML 禁止下划线规则并记录 vendor 例外。

---

## 2026-06-23 — Intent metadata 文档残留清理

- 同步当前 Alembic head：`0009_drop_intent_metadata`，记录已废弃的 intent metadata 字段 `priority_score`、`intent_kind`、`tags`、`score_reason`、`branch_key`、`branch_depth`、`expected_value` 已由该 migration 移除。
- 同步 Reason/Scheduler 文档：Reason 三态协议的新 intent 只要求 `from` 与 `description`；Scheduler 对 unclaimed open intents 按 `created_at` 选择最新 intent，并在 claimed/running open intents 未结束时跳过 Reason。
- 本次仅清理文档残留，不删除历史 `0007` / `0008` migration 文件。

---

## 2026-06-22 — Graph/Execution Log 前端联动同步

- 同步前端 graph intent 选择行为：`state-graph.js` 在选中 intent 后调用 LLM log state，按 `llmExecutions[].intent_id` 选择对应 execution 并刷新当前日志 preview/page cards；无匹配时保留当前 Execution Log 选择。
- 同步 Execution Log header 行为：新增 `Refresh Execution Log` 按钮，调用 `refreshCurrentLlmLog()` 强制刷新 execution list 与当前 execution 事件视图，不改变 graph/detail/replay 状态且不强制展开折叠面板。
- 同步测试说明：`test_graph_state.py` 覆盖匹配、多匹配取第一个、无匹配保留；`test_static_cache.py` 覆盖 assembled frontend 的按钮和联动调用。
- 当前验证：`cd cairn && uv run pytest tests/test_graph_state.py tests/test_static_cache.py` 通过（5 passed, 22 skipped）；`node scripts/check_frontend.mjs` 通过。

---

## 2026-06-22 — Reason prompt 机制邻近中性化

- 同步 default `reason.md`：mechanism proximity 启发改为通用状态空间搜索语义，使用 `decision gate`、`state transition`、`data boundary`、`invariant check`、`persisted state`、`confirmed primitive`、`causal mechanism`，移除偏安全域的 credential/authorization/stored-secret 表达。
- 后续 `0009_drop_intent_metadata` 已移除旧 intent metadata 字段；当前 Reason 三态 marker JSON 的新增 intent 只保留 `from` 与 `description`。
- 当前验证：`cd cairn && uv run pytest tests/test_contract_parsing.py tests/test_prompt_snapshots.py` 通过（30 passed）。

---

## 2026-06-22 — Intent branch 调度元数据同步

- 旧同步记录：当时曾短期引入 intent 调度元数据字段。
- 当前状态：这些字段以及 `priority_score`、`intent_kind`、`tags`、`score_reason` 已由 `0009_drop_intent_metadata` 废弃并移除；Scheduler 不再计算 branch priority。
- 当前验证：`cd cairn && uv run pytest tests/test_scheduler_refactor.py tests/test_fact_views.py tests/test_contract_parsing.py tests/test_reason_state.py tests/test_intents_router.py tests/test_db_migrations.py tests/test_graph_state.py` 通过（50 passed, 16 skipped）。

---

## 2026-06-20 — 命名规范入口与主流命名重命名

- 新增 `AI/NAMING.md`，记录 Python PEP 8、FastAPI 分层、前端 kebab-case、配置环境后缀和协议文件例外。
- 新增 `cairn/scripts/check_naming.py`，检查 Python/JS/YAML 文件命名，并确认关键重命名后的 canonical 文件存在。
- `server/models_pkg/` 迁移为 `server/schemas/`，内部源码改用新路径；保留 `models_pkg` re-export 兼容层用于短期迁移。
- `server/application/project_read.py` 迁移为 `project_queries.py`，`dispatcher/workers/adapters/claudecode.py` 迁移为 `claude_code.py`，均保留旧模块兼容导入。
- 前端 state 文件改为 kebab-case，例如 `state-projects.js`、`state-graph.js`、`state-llm-log.js`、`state-settings-admin.js`，并增强 `check_frontend.mjs` 的本地 import 解析检查。
- mock 配置文件统一为 `config.mock.yaml` 与 `server.mock.yaml`。

---

## 2026-06-20 — Review 与仓库清理同步

- 恢复并更新被工作树删除的 `AI/ARCHITECTURE.md`、`AI/CODEBASE_ANALYSIS.md`、`AI/PROJECT_OVERVIEW.md`，保持 review 文档继续受版本控制。
- 同步当前 Alembic head：`0005_project_poll_revisions`，记录 `projects.graph_revision` / `timeline_revision` 与 `/projects/{project_id}/poll-state` 轻量轮询模型。
- 同步前端架构：旧 `parts.*`/`cairn-app.js` 描述替换为 `static/js/app/index.js` + `app/`、`workspace/`、`shared/` ES module 分层。
- 同步统计：当前扫描约 398 个源码/测试/前端文本文件、86 个 FastAPI route decorator、55 个顶层 `test_*.py` 文件；自有源码未发现显式 TODO/FIXME/HACK 标记。
- 扩展 `.gitignore`，覆盖 Python cache、virtualenv、coverage/build output、Node/frontend local artifacts、logs、runtime data、本地 config/secrets 和本地 assistant/tool state。

---

## 2026-06-17 — Execution Config 不可变性与 Dispatcher 缓存隔离同步

- 同步 execution config 语义：`project_execution_configs` 是项目创建/replay 创建时写入的一次性 snapshot，底层 repository 改为 `insert_project_execution_config()`；同一 `project_id` 再次持久化会抛 `ServerInvariantError("project execution config already exists")`，不再 delete child rows 或 upsert 覆盖。
- 同步 API 边界：`PATCH /projects/{id}/execution-config` 和 `UpdateExecutionConfigRequest` 已移除；外部只保留 `GET /projects/{id}/execution-configs` 与 `GET /projects/{id}/execution-configs/{task_type}` 读取项目执行快照。
- 同步 Dispatcher 缓存约束：`ExecutionConfigResolver` 对 cached/fetched payload 存取都做 `deepcopy`，避免下游 mutation 污染同一 `(project_id, task_type)` 的后续 dispatch；reload 清空全部缓存，project log-state clear/404 清空对应 project。
- 同步测试状态：`test_execution_config_source.py` 覆盖重复 persist 不覆盖原 snapshot、replay/new project 可写独立 snapshot、PATCH route 不存在；`test_scheduler_refactor.py` 覆盖 resolver 返回值 mutation 不污染缓存。
- 当前验证：`cd cairn && uv run --group dev python -m pytest -q tests/test_execution_config_source.py tests/test_replay_service.py tests/test_scheduler_refactor.py` 通过；`cd cairn && uv run --group dev python -m pytest -q -m 'not db'` 通过。

---

## 2026-06-17 — 热点查询二阶段优化与优化候选盘点

- 同步热点查询二阶段实现：测试侧 config loader 改走 repo 根 `server.test.yaml`，避免测试路径漂移；project list/work summaries 的事实、意图、hint 计数改为 repository 预聚合 join，消除逐项目 correlated count `SubPlan`。
- 同步观测查询优化：execution 列表先用分页 CTE 选出目标 execution，再只聚合分页集合内 events；event view 先按 `event_kind` 聚合统计，再按可见 kind 拉取 primary events，usage count/latest usage 查询只在需要时执行。
- 同步 retention 与 replay 优化：retention events 清理改为 `DELETE ... USING llm_executions`，不再预取旧 execution ids；replay route extraction 使用 `route_graph_for_facts()` 从 completion facts 反向加载可达子图，避免完整项目 replay 图扫描。
- 当前验收：`uv run python -m pytest -q tests/test_config_loader.py tests/test_replay_service.py` 通过；`CAIRN_ALLOW_DB_RESET=1 uv run python -m pytest -q tests/test_hot_query_repositories.py tests/test_retention_loop.py tests/test_observability_and_files.py::ObservabilityRepositoryTests` 通过。
- 工程保障：`cairn/tests/test_hot_query_repositories.py` 覆盖 project count、execution/event view、retention、replay route 和 PostgreSQL `EXPLAIN` 防回归；该文件必须纳入版本控制，否则热点 SQL/replay/retention 回归闭环会丢失。
- 下一阶段候选已记录到 `CODEBASE_ANALYSIS.md`：intent sources 批量 insert、project-scoped source hydrate 收窄、lease expiration/event kind 索引基于 fixture + EXPLAIN 再决策、prompt/settings YAML 缓存或 section-level reload 评估。

---

## 2026-06-17 — Review 同步

- 同步 Dispatcher 控制面：`health_server.py` 现在除 `/healthz`、`/metrics`、`/reload` 外还提供 `/mcp-probe`，Server capability admin 通过 dispatcher service token 调用它执行 MCP initialize + `tools/list` 探测。
- 同步 capability health 行为：MCP probe 在临时 startup container 中写入 `mcp.json` 和 probe 脚本，执行后删除容器；probe 结果写回 `config.resources.yaml` 的 `last_probe_*` 字段，并更新 MCP `available`。
- 同步 System Settings API：旧 runtime/tasks/observability/log-retention 分散管理接口收敛为聚合 `GET/PUT /system-settings`，`GET /container-limits` 保持只读并来自固定 `server.yaml`。
- 同步配置与启动说明：`server.yaml` 保存固定部署/敏感/基础设施配置，`config.yaml` 保存 UI 可写运行配置，`config.resources.yaml` 保存 resources；推荐启动命令改为 `./start.sh`，由其导出 `CAIRN_HOST_ROOT` 再运行 compose。
- 同步 Worker image 与能力材料：worker image 安装 Kali/Metasploit 常用工具，`metasploit-mcp` 默认 env 清空，角色提示强调先读 SKILL 和遵守 CTF/pentest/vuln-research 工作流。
- 同步测试状态：当前 `test_*.py` 文件数为 51；新增/更新 MCP probe、aggregate system settings、static UI endpoint 边界等回归说明。

---

## 2026-06-16 — Prompts 与 Settings UI 更新

- Settings 主保存/创建操作移动到对应 section 或编辑表单标题行右侧；Capabilities MCP/Skills 资源卡片改为固定高度并保持列表内部滚动。
- Prompt group 管理支持递归 `.md` 文件读取和嵌套路径保存，执行配置 prompt snapshot hash 纳入全部 prompt group 内 Markdown 文件。
- 前端 Settings 状态从 `parts.capabilities.js` 拆分为 `parts.settings.js`、`parts.settings_admin.js`、`parts.prompts.js`、`parts.ai_profiles.js`、`parts.proxies.js` 和 capability-only `parts.capabilities.js`；`cairn-app.js` 注册顺序同步更新并保留 duplicate key guard。
- `navigateSettings(section)` 改为 section 专属 loader，进入 Settings 不再全量拉取 runtime、prompts、AI profiles、proxies、capabilities 等所有管理数据。
- 同步 `ARCHITECTURE.md` 当前 Alembic head 为 `0004_prompt_snapshots`。
- 同步 `ARCHITECTURE.md`、`CODEBASE_ANALYSIS.md`、`PROJECT_OVERVIEW.md` 的前端 slice 架构描述；补充静态测试覆盖 slice 注册、loader 隔离和 capability slice endpoint 边界。
- 当前验证：`node --check` 覆盖新增/更新 JS；CairnParts VM 装载无重复 key；`uv run python -m pytest tests/test_prompt_group_admin.py` 通过；`tests/test_static_cache.py` 因本地 DB reset gate clean skip。

---

## 2026-06-15 — lint 与 AI 文档漂移修复

- 执行 `uv run ruff check src tests --fix`，修复 dispatcher health 和 auth/projects router 测试中的 import 排序问题，解除 CI lint 阻塞。
- 同步 `ARCHITECTURE.md`：SPA 描述改为 `server/partials/* + assemble_index()`，启动链路记录 partials 拼装并缓存到 `app.state.index_html`。
- 同步认证架构描述：公开路径收窄为 `/`、`/auth/login`、`/health`、`/metrics` 和 `/static/*`；其他 `/auth/*` 不再整体豁免。
- 同步 `CODEBASE_ANALYSIS.md`：记录 `/docs`、`/redoc`、`/openapi.json` 已禁用，补充 system-config 端点、安全响应头、当前 47 个测试文件和 CI blocking 检查。

---

## 2026-06-14 — 工程加固与类型清零

### P0 配置健壮性
- `_read_yaml()` 增加 `exists()`/`is_file()`/`is_dir()` 预检；目录场景给出 bind-mount 源缺失的 actionable 报错
- 新增 `ConfigError` 漏斗类型：所有 load 失败（缺文件、无效 YAML、schema 违反、资源路径检查）统一走此类型
- CLI 捕获 `ConfigError`，输出单行致命日志而非裸 traceback 崩溃循环
- `_read_yaml` 同时捕获 `yaml.YAMLError` 和 `OSError`

### P1 并发 + 测试缺口
- `HeartbeatLease._failure` 改为在 `_lock` 内读写（跨线程字段）
- `TaskCancellation` 记录 snapshot-under-lock 不变式（无真实 bug，加注释防"简化"）
- 新增 `test_lease_concurrency.py`（6 tests）、`test_hints_router.py`（4 DB tests）、`test_task_types_router.py`（2 DB-free tests）、`test_project_io_helpers.py`（15 tests）、`test_config_loader.py`（8 failure-path tests）

### P2 可维护性
- 共享 `_jsonl.py` helper 模块，消除 claudecode/codex 适配器 78 行重复
- Mock worker 在 import 时 `compile()` 语法检查
- `_remote_support_env_from_raw` 收窄 `except Exception` → `except ValidationError`

### mypy 清零 + CI blocking（116 → 0 错误，245 源文件）
- 修复变量复用类型污染（McpServerCapabilityConfig vs SkillCapabilityConfig）
- YAML `Any`/`dict`/`list`/`None` union 窄化模式（bind-to-local）
- `render_capability_path` None 崩溃修复（`@overload`）
- `AnyReporter` 类型别名（ExecutionReporter | DisabledExecutionReporter）
- 开启 `check_untyped_defs = true`、`warn_unused_ignores = true`
- CI mypy 改为 blocking（去掉 `continue-on-error`）

### 扫描索引（migration 0003）
- `idx_facts_project` on facts(project_id)：消除 WHERE project_id 的表扫描
- `idx_llm_executions_started` on llm_executions(started_at)：retention sweep 不再全表扫描
- 幂等 `_index_exists` 守卫，对称 downgrade，orm.py 同步

### DB 安全隐患修复
- `reset_postgres_db()` 要求 `CAIRN_ALLOW_DB_RESET=1` 环境变量，无它则 skip 而非 drop schema

### models_pkg shim 淘汰
- 删除 5 个 models_pkg 文件中的 re-export shim（`common.py`、`proxies.py`、`reason_models.py`、`ai_profiles.py`、`projects.py`）
- 28 个 server 文件的 import 改为直接从 `shared/contracts` 获取共享本体
- 架构文档明确分层约定：跨进程本体在 `shared/contracts`，HTTP 信封在 `models_pkg`

### 文档漂移修复
- `ARCHITECTURE.md` 和 `CODEBASE_ANALYSIS.md` 更新 Alembic head 引用
- 新增 `test_architecture_boundaries` 中的 head-vs-doc 一致性测试

---

## 2026-06-13 — compose migration head 修复

- 修复 `docker compose up --build` migration 失败：原 `0002_project_execution_config_names` revision id 超过 Alembic 默认 `alembic_version.version_num VARCHAR(32)`，业务 DDL 成功后写版本号会报 `value too long for type character varying(32)`。
- 将 Alembic head 缩短为 `0002_exec_config_names`，保持 `down_revision = "0001_initial_postgresql"` 和 migration 业务逻辑不变；已在 DB migration 测试中更新期望 head。
- 新增 migration 卫生边界测试，扫描 `cairn/migrations/versions/*.py` 的 `revision`/`down_revision` 字符串长度不超过 32，避免同类 compose 启动故障复发。
- 清理后端死代码：移除已无调用的 `ProjectRepository.open_intents()` 旧读接口；保留仍在项目状态切换中使用的 `release_open_intents()`。
- 本次不更新静态前端资源或 `README/current-architecture.html`。

---

## 2026-06-13 — Backend-only v2 边界收口

- Router purity v2：hints、attachments、files、execution configs、project capabilities/role 查询下沉到 application/query service；对应 routers 不再直接 import repository 或 SQL helper。
- Mapper purity：`server/mappers/intents.py` 改为只消费 repository projection；intent source 查询由 `IntentRepository` 一次性提供，并新增 mapper SQL-free 边界检查。
- Replay 事务边界拆清：`application/replay/service.py` 保留事务内创建/推进 use case，`application/replay/orchestration.py` 承接事务外附件复制、激活 replay project 和失败补偿清理。
- Observability repository 拆薄：删除单体 `server/observability/repositories.py`，拆为 `execution_repository.py`、`event_repository.py`、`event_view_repository.py`、`usage_repository.py`、`retention_repository.py` 和 shared query helper。
- Dispatcher submit pipeline 继续瘦身：`TaskSubmitter` 保留计划/提交编排，claim/release 和 runtime registry/log 分别拆到 `task_claims.py`、`submission_registry.py`；不恢复 collaborator 对完整 `DispatcherLoop` 的依赖。
- 架构边界测试强化：覆盖 routers 禁 repository import、mappers 禁 SQL、application core 禁隐式 session（仅 orchestration/best-effort 白名单）、observability SQL 层约束和 TaskSubmitter collaborator 边界。
- 当前环境验证：`python -m compileall -q cairn/src/cairn` 通过；`uv run python -m pytest -q -m 'not db'` 通过（158 passed, 23 skipped, 129 deselected, 7 subtests passed）；`uv run python -m pytest -q -m db` 通过（38 passed, 91 skipped, 181 deselected）。

---

## 2026-06-13 — post src 1-6 后端边界收口

- Router SQL 边界继续收口：`routers/ai_profiles.py`、`routers/export.py`、`routers/proxies.py` 不再直接调用 SQL helper；AI profile check queue、export 查询、proxy detach 分别下沉到 application/repository。
- Replay 持久化边界拆清：新增 `server/repositories/replay.py`，承接 replay run、step、fact map、source route、intent/fact 查询和条件更新；`application/replay` 保留 route/step 推进决策与响应编排。
- Observability SQL 分层完成：新增 `server/observability/repositories.py`，集中 execution/event 写入查询、usage、event view 和 retention SQL；原 events/executions/view/retention 模块只做映射和应用编排。
- Dispatcher 调度层继续瘦身：删除 `DispatcherLoop` 上 `_dispatch_*`、`_ordered_projects`、`_reap_futures`、proxy/AI selection 等兼容转发方法；测试改为直接依赖 `ProjectContextResolver`、`ProjectDispatcher`、`TaskSubmitter` 等 collaborator。
- `TaskSubmitter` 抽出通用提交流水线，统一 execution config、worker selection、export、claim、submit、失败 release、runtime registry/log，同时保持 bootstrap/explore/reason 对外调度行为。
- 测试工程补强：新增 `tests/conftest.py` 自动标记所有 `reset_postgres_db()` 测试为 `db`；新增 `test_architecture_boundaries.py` 覆盖 domain/router/scheduler/旧路径边界。
- 当前环境验证：`python -m compileall -q cairn/src/cairn` 通过；`uv run python -m pytest -q -m 'not db'` 通过（153 passed, 23 skipped, 129 deselected）；`uv run python -m pytest -q -m db` 通过（38 passed, 91 skipped, 176 deselected）。

---

## 2026-06-13 — src 1-6 架构优化落地

- Server domain 完成 SQL-free 切换：`server/domain` 不再导入 repository/SQL/FastAPI，application 层编排事务，repository 成为唯一 SQL 条件更新和读取层。
- Dispatcher 边界继续收窄：tick/dispatch/project 协作者改依赖 `SchedulerServices`；`DispatcherLoop` 主要保留生命周期、reload、health 和运行态 wiring。
- `ContainerManager` 收敛为 facade，生命周期、cleanup、archive/file、exec/process、labels、mounts、proxy env、cleanup policy 拆入 `dispatcher/runtime/*` 小模块。
- 删除 `dispatcher/tasks/common.py`，task process/release/writeback/outcome/text/snapshot 等辅助逻辑拆分；阶段 handler 主要保留 prompt、payload 和阶段策略。
- `server/models_pkg/intents.py` 与 `capabilities.py` 拆为 project request、intent/reason models、project/replay responses、capability catalog/selection/admin，并通过 `models_pkg` 包级入口统一导出。
- 测试工程补强：dev dependency 加入 `pytest>=8.0`，pytest 配置 `testpaths/pythonpath/db marker`；DB helper 增加 PostgreSQL availability probe 和 stale temp config 恢复。
- 当前环境验证：`python -m compileall -q cairn/src/cairn` 通过；架构边界 `rg` 检查无旧内部 import/domain SQL 依赖；`uv run python -m pytest -q -m 'not db'` 通过（191 passed, 114 skipped）；DB 目标无本地 PostgreSQL 时 clean skip。

---

## 2026-06-13 — 增量同步

- 继续清理后端/Dispatcher 分层：`dispatcher/protocol/client.py` 拆为 base、project、task、AI profile、observability 子客户端，`client.py` 只保留组合类。
- `shared/contracts/models.py` 删除，DTO 按 settings、timeouts、proxies、ai_profiles、llm_events、projects、reason 拆分，内部引用统一改为 `cairn.shared.contracts` 包级入口或具体模块。
- `dispatcher/tasks/reason.py` 继续拆薄，reason 输出解析和 graph 写回迁入 `dispatcher/tasks/reason_result.py`。
- 删除旧内部 facade：`server.capabilities_service`、`shared.config.resource_models`，测试和源码直接引用拆分后的 capability/config 模块。
- 当前环境验证：compileall 通过；多组非 DB unittest 通过；DB 集成测试被本机 PostgreSQL `localhost:5432` connection refused 阻塞，未能在本环境确认。

---

## 2026-06-13 — 增量同步

- 拆分 `server/application/replay` 为 package，分离 service、route extraction、attachments、step advance。
- 拆分 Dispatcher task 辅助逻辑：新增 bootstrap/explore/reason prompt/result/process helper，阶段入口保留。
- 拆分 container runtime helper：labels、mounts、proxy env、cleanup policy 从 `ContainerManager` 中外移。
- 清理 execution config 历史命名：内部 API 改为 project execution config，移除旧 legacy 表类，DB revision 列统一为 `resources_sha256`。

---

## 2026-06-13 — 增量同步

- 同步一次性源码目录重建后的架构文档：Server 拆为 `application/domain/repositories/mappers/execution_config`，Dispatcher scheduler 拆为 loop shell + coordinators/submitter/resolvers/selectors。
- 记录 `shared.config` 与 `shared.contracts` 新边界，以及 `config.yaml` + `config.resources.yaml` 的破坏性新配置格式；旧 capabilities sidecar 和旧 shared 聚合模块路径不再兼容。
- 更新执行配置说明：按 task 组装 dispatcher payload，`resources_sha256` 为对外 revision 字段。
- 更新测试状态：2026-06-13 使用 `.venv` Python 顺序执行 `cairn/tests/test_*.py` 全量通过，DB 测试需顺序执行以避免 migration/reset 竞争。

---

## 2026-06-12 — 增量同步

- 同步 Dispatcher conclude fallback 协议：`bootstrap_conclude` 和 `explore_conclude` 成功时返回 sentinel 包裹的 plain fact text，不再返回 JSON。
- 记录 `parse_sentinel_fact_output()` 的解析约束：单个 sentinel pair、内容非空、内容不能是 JSON。
- 更新 Worker 输出说明：execute 阶段仍是 JSON protocol，conclude fallback 为 sentinel text；Claude conclude 只开放 `Read` 工具。
- 修正架构文档中过期的 Pi adapter 描述。

---

## 2026-06-10 — 首次分析

- 初始化项目文档结构
- 生成 `ARCHITECTURE.md`（架构与设计、启动链路、模块通信）
- 生成 `CODEBASE_ANALYSIS.md`（全面代码分析、数据模型、API、错误处理、横切关注点、测试策略）
- 生成 `PROJECT_OVERVIEW.md`（项目概览）
- 扫描文件数：263 个
- 识别模块数：9 个
- 识别 API 端点数：76 个
- 识别 TODO/问题数：11 个显式标记，5 个审查问题

---
