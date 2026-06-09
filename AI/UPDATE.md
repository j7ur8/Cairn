<!--
@ai: 本文件记录项目分析的变更历史。每次运行 project-review 技能时，新增的变更摘要会追加到本文件顶部。
请勿手动编辑本文件 - 由 AI 自动维护。
-->

# 更新日志

## 2026-06-09 YAML Bind Mount And Capability Transaction Fix

- 修复 Docker 单文件 bind mount 下写入 `dispatch.yaml` / `dispatch.capabilities.yaml` 的 `OSError: [Errno 16] Device or resource busy`：YAML 写入优先原子替换，遇到 `EBUSY` 时回退为原地覆盖写入。
- 修复 `GET /projects/{project_id}/capabilities` 在 PostgreSQL 下的事务自锁：项目详情读取能力时不再卡住 pending，能力探测结果在同一事务内持久化。
- 新增 `cairn/tests/test_yaml_config.py` 覆盖 bind mount `EBUSY` 回退；扩展 capability admin 测试，断言项目创建会写入 bootstrap/explore/reason 三条 `worker_execution_configs`。
- 顺序执行 `CAIRN_DATABASE_URL='postgresql+psycopg://cairn:cairn@localhost:5432/cairn' CAIRN_DISABLE_DISPATCHER_RELOAD=1 uv run --project cairn python -m unittest discover -s cairn/tests`，结果 `327 tests OK`。
- 使用 `docker compose up -d --build cairn-server cairn-dispatcher` 验证本地栈：`cairn-postgres`、`cairn-server`、`cairn-dispatcher` 均 healthy，`/health` 返回 Alembic revision `0003_worker_execution_configs`。
- 使用本机 `chrome-devtools` MCP 完成真实浏览器回归：登录、AI Profiles Check、Capabilities Probe、Proxy CRUD、Server Settings 保存、Create Project、项目详情、Execution Log 均可操作；`GET /projects/proj_001/capabilities` 返回 200；`worker_execution_configs` 对 `proj_001` 写入 bootstrap/explore/reason 三行。
- 仍可观察到 `codex` startup healthcheck 因上游 429 被标记 unhealthy；按当前人工确认这是预期行为，不作为功能阻塞。

## 2026-06-09 YAML Dispatch Facts And Execution Snapshots

- 配置事实源收敛为 3 类：`dispatch.yaml` 管理 server settings、proxies、AI Profiles；`dispatch.capabilities.yaml` 管理 capabilities/roles；PostgreSQL `worker_execution_configs` 保存项目创建/回放时的执行配置快照。
- 新增 YAML 配置服务与 dispatcher `/reload` 热加载入口；UI 修改 AI Profiles、Proxies、Settings、Capabilities、Roles 后会写 YAML 并触发 dispatcher reload。
- 新增 `worker_execution_configs` Alembic revision `0003_worker_execution_configs`，项目创建时保存 bootstrap/explore/reason 的 AI、capability、proxy、settings 快照。
- 真实运行配置 `dispatch.yaml`、`dispatch.capabilities.yaml` 已改为本地敏感文件，不再跟踪；新增 `dispatch.example.yaml`、`dispatch.capabilities.example.yaml` 作为模板。
- Python 单元测试 `CAIRN_DATABASE_URL='postgresql+psycopg://cairn:cairn@localhost:5432/cairn' CAIRN_DISABLE_DISPATCHER_RELOAD=1 uv run --project cairn python -m unittest discover -s cairn/tests` 已通过，结果为 `325 tests OK`。
- 注意：兼容执行路径仍同步 `project_ai_profiles` / `project_capability_snapshots` 与最小 AI profile DB 镜像；`worker_execution_configs` 已作为统一快照表落地，后续可继续把 dispatcher 读取路径完全切到该表。

## 2026-06-09 PostgreSQL Migration And Browser Verification

- 全量移除运行时 SQLite 路径：删除旧 `db_schema.py`、`db_migrations.py`、`sqlite_diagnostics.py`，新增 PostgreSQL-only `server/db.py`、SQLAlchemy ORM metadata `server/orm.py`、Alembic 配置与 `0001/0002` migrations。
- Docker Compose 新增 `cairn-postgres`，server/dispatcher 通过 `CAIRN_DATABASE_URL` 连接 PostgreSQL；`/health` 和 `cairn db status/migrate/reset` 改为报告 PostgreSQL/Alembic 状态。
- 测试集已改为 PostgreSQL 语义，移除 WAL、PRAGMA、sqlite_master、migration_errors 等旧断言；`uv run --project cairn python -m unittest discover -s cairn/tests` 已通过，结果为 `325 tests OK`。
- 使用 `docker compose down -v && docker compose up -d --build` 重建本地栈，`cairn-postgres`、`cairn-server`、`cairn-dispatcher` 均为 healthy，`/health` 返回 Alembic revision `0002_intent_partial_uniques`。
- 使用本机 `chrome-devtools` MCP 访问 `http://127.0.0.1:8000/` 完成真实浏览器回归：登录、AI Profiles Check、Capabilities Probe、Proxy CRUD、Server Settings 保存、Create Project、bootstrap、Execution Log、Hints/Files/Caps、Replay Project、Stop 均可操作。
- 已确认 AI Profiles 中每个 profile 的 `Check` 按钮位于 `Edit` 左侧；`claudecode_deepseek-v4-pro` check 通过，`codex` check 因上游 429 显示 unavailable，按当前人工确认不作为阻塞。
- 已确认 Create Project 和 Replay Project 中 `EXECUTION LOG DEFAULT VISIBLE EVENTS` 不再重复出现。
- 浏览器网络请求除首次未登录 `GET /auth/me [401]` 外无失败；控制台未发现业务 JS error，仅有 Tailwind runtime 生产警告和表单可访问性 issue。
- 注意：运行时已 PostgreSQL-only，但业务层仍保留 SQLAlchemy-backed SQL adapter 和部分 raw SQL 查询；若要求严格“无 raw SQL adapter”，需要后续继续做 repository/ORM 查询替换。

## 2026-06-09 Browser Regression Execution

- 使用 `docker compose up --build -d` 启动本地栈，并通过本机 MCP `chrome-devtools` 访问 `http://127.0.0.1:8000/` 执行真实浏览器回归。
- 已验证后台与入口：登录、项目列表、Server Settings、Proxies、新建 AI Profile、项目创建、项目详情、Hint、Snapshot YAML、Snapshot Timeline、Replay、项目完成、项目重开、项目删除。
- 已验证回放控制：`Pause replay`、`Restart replay`、速度切换、`Exit` 均可用。
- 已验证项目生命周期闭环：`Create -> Claim -> Conclude -> Hint -> Snapshot -> Replay -> Complete -> Reopen -> Delete` 全链路可正常操作，最终项目被成功删除并从列表移除。
- 浏览器 console 在本次回归结束时无 `error` / `warn`。
- 已观察到后台 worker 事件中的 `bootstrap_healthcheck` / `reason_healthcheck` `unhealthy`，经当前人工确认属于本地 `codex` worker 预期行为，不作为本轮 UI 功能失败处理。
- 已观察到一个真实可用性问题：New Project 页面中三段 AI worker chain 的 `Thinking Level` 默认为空，导致标题/目标等字段已填写时 `Create` 仍保持禁用；手动为 `bootstrap`、`intent`、`reason` 三项选择 `low/medium/high/xhigh` 后方可创建项目。
- 已观察到一个既有异常请求痕迹：能力创建实验曾产生 `PUT /capabilities/admin/undefined/regression-skill [400]`，来自 capability 页面早期自动化尝试，不属于本次项目生命周期回归主路径。
- Python 单元测试 `uv run --project cairn python -m unittest discover -s cairn/tests` 仍存在 15 个既有失败，未在本轮修复。

## 2026-06-09 Regression Protocol And UI Testability

- 新增 `AI/TESTING_PROTOCOL.md`，把“每次更新后使用 Docker + 本机 Chrome DevTools 做人工式全功能回归”固化为项目级要求。
- 在 `AI/PROJECT_OVERVIEW.md`、`AI/ARCHITECTURE.md`、`AI/CODEBASE_ANALYSIS.md` 中补充测试入口、双层验收策略和前端功能面说明。
- 新增 `dispatch.test.yaml`，提供基于 `mock` worker 的本地闭环 dispatcher 配置。
- 新增 `scripts/run-local-regression.sh`，用于执行 Python 测试并启动 Docker 栈等待健康。
- 在 `server/static/index.html` 的关键导航、表单、项目操作和模态框上补充稳定测试选择器，降低浏览器回归脆弱性。
- 本地闭环层：已执行，单测仍存在既有失败。
- 真实外部依赖层：已执行，结果记录见上方 2026-06-09 Browser Regression Execution。
