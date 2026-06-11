<!--
@ai: 本文件是项目的全面代码分析。当需要了解具体实现细节、函数签名、数据模型或业务逻辑时，请查阅本文件。
本文件按模块组织，每个模块包含其文件清单、核心函数、数据结构和实现细节。

@update: 如需更新本文档，请遵循以下原则：
1. 优先局部修改受影响的章节，而非全文重写
2. 修改后必须在 UPDATE.md 追加一条变更记录
3. 如数据模型或 API 端点有变更，同步更新 ARCHITECTURE.md 中的相关图表
4. 新增的函数入口点不超过 15 个上限时，追加到入口点列表；超过则替换次重要的

生成日期：2026-06-10
-->

# Cairn 全面代码分析

## 1. 项目概览

| 项 | 内容 |
|----|------|
| 项目名称 | Cairn |
| 版本 | `0.2.1` |
| 核心描述 | Fact-graph based collaborative exploration protocol |
| 核心目标 | 用 fact-intent graph 和共享黑板机制，把未知状态空间搜索任务拆成可并行探索、可回写、可观测的 Agent 工作流。 |

Cairn 的核心不是固定渗透测试流程，而是一个通用 problem-solving engine。用户创建项目并给出 origin、goal 和 hints；Server 维护图一致性；Dispatcher 基于图状态调度 Bootstrap、Reason、Explore 任务；Worker 在隔离容器中执行 AI CLI 或 mock 后端，再把事实、意图、完成信号和观测事件写回 Server。

技术栈：

| 层级 | 技术 | 版本/约束 |
|------|------|-----------|
| 运行时/语言 | Python | `>=3.12` |
| 后端框架 | FastAPI | `>=0.115` |
| ASGI Server | Uvicorn | `>=0.34` |
| CLI | Click | `>=8.1` |
| 数据库 | PostgreSQL | Docker Compose 使用 `postgres:16-alpine` |
| ORM / Migration | SQLAlchemy, Alembic | SQLAlchemy `>=2.0`, Alembic `>=1.13` |
| 配置 | PyYAML, Pydantic v2 | YAML + validated models |
| Docker 控制 | Docker SDK for Python | `>=7.1.0` |
| HTTP Client | requests, tenacity | Dispatcher 调 Server |
| 认证 | PyJWT, bcrypt | JWT + 密码 hash |
| 观测 | prometheus-client | HTTP/Dispatcher/Worker metrics |
| 前端 | Static HTML, Alpine, Tailwind, Cytoscape | 无构建静态资源 |
| 测试 | unittest/pytest 风格测试文件 | 当前环境缺少 pytest 包 |

## 2. 工程目录结构

```text
Cairn/
├── cairn/
│   ├── pyproject.toml                # Python 包元信息、依赖、CLI 入口
│   ├── alembic.ini                   # Alembic 配置
│   ├── migrations/                   # PostgreSQL 迁移
│   ├── src/cairn/
│   │   ├── cli.py                    # cairn serve / dispatch / db 命令
│   │   ├── server/                   # FastAPI Server、routers、models、repositories
│   │   ├── dispatcher/               # 调度器、worker adapters、runtime、prompts
│   │   ├── shared/                   # 共享协议模型、配置模型、任务类型
│   │   └── observability/            # 日志、metrics、trace id
│   └── tests/                        # 认证、路径安全、调度、配置、观测等测试
├── capabilities/                     # 技能、角色、payload 和模板
├── container/                        # Worker 容器镜像与 MCP wrapper
├── datas/                            # 默认数据目录
├── README/                           # 图片和架构可视化素材
├── dispatch.yaml                     # 主运行配置
├── dispatch.capabilities.yaml        # 能力配置
├── docker-compose.yaml               # 本地完整栈
└── Dockerfile                        # app 镜像
```

核心文件：

| 文件 | 作用 |
|------|------|
| `cairn/src/cairn/cli.py` | CLI 入口，启动 Server、Dispatcher 和 DB 命令 |
| `cairn/src/cairn/server/app.py` | FastAPI app、lifespan、全局鉴权、路由注册、静态文件 |
| `cairn/src/cairn/server/db.py` | SQLAlchemy engine/session、Alembic migration、seed |
| `cairn/src/cairn/server/orm.py` | 数据表、索引、约束定义 |
| `cairn/src/cairn/server/services.py` | 图操作、claim/conclude/reason lease 等核心规则 |
| `cairn/src/cairn/server/project_creation_service.py` | 项目创建、执行配置快照 |
| `cairn/src/cairn/dispatcher/scheduler/loop.py` | Dispatcher 主循环、任务分发 |
| `cairn/src/cairn/dispatcher/protocol/client.py` | Dispatcher 调 Server 的 HTTP client |
| `cairn/src/cairn/dispatcher/runtime/containers.py` | Worker 容器生命周期管理 |
| `cairn/src/cairn/shared/dispatch_config.py` | YAML 配置模型和校验 |

## 3. 关键入口点

| 入口点 | 文件位置 | 触发方式 | 功能说明 |
|--------|----------|----------|----------|
| `main()` | `cairn/src/cairn/cli.py` | `cairn` CLI | Click 根命令 |
| `serve()` | `cairn/src/cairn/cli.py` | `cairn serve` | 启动 Uvicorn/FastAPI |
| `dispatch()` | `cairn/src/cairn/cli.py` | `cairn dispatch` | 启动 DispatcherLoop |
| `db_migrate()` | `cairn/src/cairn/cli.py` | `cairn db migrate` | 执行 Alembic migration |
| `lifespan()` | `cairn/src/cairn/server/app.py` | FastAPI startup/shutdown | 配置日志、DB、管理员 bootstrap、retention loop |
| `_enforce_auth()` | `cairn/src/cairn/server/app.py` | FastAPI global dependency | 全局 Bearer token 鉴权 |
| `create_project()` | `server/routers/projects.py` | `POST /projects` | 创建项目和 execution config snapshot |
| `claim_open_intent_or_409()` | `server/services.py` | Intent claim API | Worker claim open intent |
| `conclude_open_intent_or_409()` | `server/services.py` | Intent conclude API | 写入 fact 并结束 intent |
| `claim_project_reason_or_409()` | `server/services.py` | Reason claim API | 项目级 reason lease |
| `DispatcherLoop.run()` | `dispatcher/scheduler/loop.py` | Dispatcher process | 持续调度 tick |
| `ContainerManager.ensure_running()` | `dispatcher/runtime/containers.py` | 任务启动前 | 创建或复用项目容器 |
| `run_bootstrap_task()` | `dispatcher/tasks/bootstrap.py` | Dispatcher task | Bootstrap 阶段 |
| `run_reason_task()` / `run_explore_task()` | `dispatcher/tasks/` | Dispatcher task | Reason 和 Explore 阶段 |

## 4. 核心算法

| 算法/机制 | 文件位置 | 功能描述 | 复杂度/特性 | 备注 |
|-----------|----------|----------|-------------|------|
| Fact-Intent graph expansion | `server/services.py`, `dispatcher/scheduler/loop.py` | 通过 facts、intents、hints 逐步扩展状态空间 | 与项目图规模线性相关 | 核心业务模型 |
| Round-robin project ordering | `dispatcher/scheduler/loop.py` | 在 active/running/idle 项目间轮转调度 | O(n log n) 排序 + O(n) 轮转 | 避免固定顺序饥饿 |
| Worker selection | `dispatcher/scheduler/worker_select.py`, `worker_selection.py` | 根据 task type、AI profile、健康状态选择 worker | 与 worker 数量线性相关 | 支持 primary/fallback |
| Lease expiration | `server/services.py` | 过期 intent worker 和 reason lease | SQL update/select | 通过 heartbeat_at 判断 |
| Replay advance | `server/routers/replay.py`, `replay_service.py` | 从完成项目生成 replay run 并推进步骤 | 与 replay steps 数量相关 | 用于复现实验链路 |
| Redaction | `server/observability/redaction.py`, `dispatcher/observability/redaction.py` | 对 token/key 等敏感文本脱敏 | 与事件文本长度和 pattern 数量相关 | 用于观测数据 |

## 5. 主要业务流程

### 项目创建

```mermaid
sequenceDiagram
    participant UI as SPA/API Client
    participant Server as FastAPI
    participant DB as PostgreSQL
    participant YAML as dispatch YAML

    UI->>Server: POST /projects
    Server->>YAML: load capabilities/roles/AI profiles/proxy
    Server->>DB: next_project_id()
    Server->>DB: INSERT projects, facts(origin), hints
    Server->>DB: INSERT worker_execution_configs snapshots
    Server-->>UI: ProjectDetail
```

### Bootstrap/Explore 执行

```mermaid
sequenceDiagram
    participant D as Dispatcher
    participant S as Server
    participant DB as PostgreSQL
    participant C as Container
    participant W as Worker Adapter

    D->>S: GET /projects
    S->>DB: list active summaries
    D->>S: GET /projects/{id}
    D->>S: claim bootstrap or intent
    S->>DB: update lease
    D->>C: ensure_running(project_id)
    D->>W: execute prompt
    W-->>D: structured result
    D->>S: conclude/create_intent/complete/report events
    S->>DB: persist graph changes
```

### Reason 阶段

```mermaid
sequenceDiagram
    participant D as Dispatcher
    participant S as Server
    participant DB as PostgreSQL
    participant W as Worker

    D->>S: POST /projects/{id}/reason/claim
    S->>DB: set reason_worker/run_id/trigger
    D->>W: run reason prompt with graph_yaml
    W-->>D: complete/intents/noop/blocked/error
    D->>S: POST /projects/{id}/reason/finish
    S->>DB: update project_reason_state and release reason lease
```

### 附件上传与文件下载

```mermaid
sequenceDiagram
    participant UI as SPA
    participant S as Server
    participant FS as Filesystem
    participant DB as PostgreSQL

    UI->>S: POST /projects/{id}/attachments
    S->>FS: sanitize filename and write file
    S->>DB: insert hint with worker path
    UI->>S: GET /projects/{id}/files/download
    S->>FS: safe_resolve_within + size guard
    S-->>UI: FileResponse
```

## 6. 数据模型

```mermaid
erDiagram
    projects ||--o{ facts : owns
    projects ||--o{ intents : owns
    projects ||--o{ hints : owns
    projects ||--o{ scoped_counters : owns
    projects ||--o{ worker_execution_configs : snapshots
    projects ||--o{ replay_runs : source
    projects ||--o{ llm_executions : observes
    intents ||--o{ intent_sources : has_sources
    facts ||--o{ intent_sources : referenced_by
    replay_runs ||--o{ replay_fact_map : maps
    replay_runs ||--o{ replay_steps : steps
    llm_executions ||--o{ llm_execution_events : emits

    projects {
        text id PK
        text title
        text status
        text created_at
        text proxy_id
        text reason_worker
        text reason_run_id
    }
    facts {
        text id PK
        text project_id PK
        text description
    }
    intents {
        text id PK
        text project_id PK
        text to_fact_id
        text description
        text creator
        text worker
        text concluded_at
    }
    hints {
        text id PK
        text project_id PK
        text content
        text creator
        text created_at
    }
    users {
        text id PK
        text email
        text hashed_password
        int is_active
        int is_superuser
    }
```

关键约束：

| 表 | 约束 |
|----|------|
| `facts` | `(id, project_id)` 复合主键，`project_id` cascade 到 `projects` |
| `intents` | `(id, project_id)` 复合主键；每个项目最多一个 `to_fact_id='goal'`；每个非 goal fact 只能被一个 intent 产生 |
| `intent_sources` | 引用 `(intent_id, project_id)`，cascade 删除 |
| `users` | `email` unique |
| `replay_runs` | `replay_project_id` unique |
| `replay_steps` | `(run_id, source_intent_id)` unique |
| `proxies` | `type IN ('socks5','http','https')` |
| `ai_profile_check_requests` | `status IN ('pending','running','completed','failed')` |

敏感字段：

| 字段/配置 | 存储方式 | 说明 |
|-----------|----------|------|
| `users.hashed_password` | bcrypt hash | 不存明文密码 |
| `system.auth.jwt_secret` | YAML 配置 | JWT HS256 签名密钥 |
| `system.auth.dispatcher_api_token` | YAML 配置 | Dispatcher reload/API service token |
| AI profile `sk` | YAML/加密包装服务 | Server 提供读取 secret 的接口 |
| proxy password | YAML-backed config | Dispatcher 启动任务时注入 worker env |
| remote SSH password | YAML config | Worker remote support env |

核心状态：

| 实体 | 状态 |
|------|------|
| Project | `active`、`stopped`、`completed` |
| Intent | open、claimed、concluded、goal completion |
| Reason | idle、claimed、heartbeat、finished、backoff/blocked |
| Replay step | `pending`、running/concluded 类状态由 replay 服务维护 |
| AI profile check | `pending`、`running`、`completed`、`failed` |

## 7. API 端点

项目没有独立 OpenAPI 文件，FastAPI 运行时可生成 schema。当前扫描到 `@router`/`@app` 装饰器约 76 个。

| 分组 | 主要端点 | 用途 | 认证 |
|------|----------|------|------|
| App | `GET /`, `GET /health`, `GET /metrics` | SPA、健康检查、Prometheus | public |
| Auth | `POST /auth/login`, `GET /auth/me`, `POST /auth/refresh`, `POST /auth/users` | 登录、用户信息、刷新、创建用户 | login public；users 需要 superuser |
| Projects | `GET/POST /projects`, `GET/DELETE /projects/{id}`, `PUT /projects/{id}/title/status` | 项目 CRUD 和状态管理 | Bearer |
| Reason | `/projects/{id}/reason/*` | reason claim/heartbeat/release/state/finish | Bearer |
| Complete/Reopen | `POST /projects/{id}/complete`, `POST /projects/{id}/reopen` | 完成或重开项目 | Bearer |
| Intents | `POST /projects/{id}/intents`, `/claim`, `/heartbeat`, `/release`, `/conclude` | intent 生命周期 | Bearer |
| Hints | `POST /projects/{id}/hints` | 添加人工提示 | Bearer |
| Attachments/Files | `POST /projects/{id}/attachments`, `GET /projects/{id}/files`, `/download` | 附件上传和文件浏览 | Bearer |
| Export/Replay | `GET /projects/{id}/export`, `POST /projects/{id}/replay-runs` | 导出与复现 | Bearer |
| Capabilities/Roles | `/capabilities/*`, `/roles/catalog`, `/projects/{id}/capabilities` | 能力和角色管理 | Bearer |
| AI Profiles | `/ai-profiles/*`, `/projects/{id}/ai-profiles` | AI profile catalog、secret、health check | Bearer |
| Proxies/Settings | `/proxies/*`, `/settings` | 系统代理和超时配置 | Bearer |
| Observability | `/projects/{id}/llm-executions*`, `/llm-events*` | LLM execution/event 记录与查询 | Bearer |

## 8. 错误处理策略

| 层面 | 策略 |
|------|------|
| 数据库不可用 | `DatabaseUnavailable` 和 `SQLAlchemyError` 被转换为 503 JSON |
| 业务冲突 | 使用 `HTTPException(409, ...)` 表示 intent 已被 claim、项目状态冲突等 |
| 鉴权失败 | 401 + `WWW-Authenticate: Bearer` |
| 权限不足 | 403 |
| 文件路径 | traversal、非法 project_id/path 返回 400；不存在返回 404；超大文件返回 413 |
| Dispatcher HTTP | `CairnClient` 对部分请求返回 `ApiResult`，对读取请求调用 `raise_for_status()` |
| Worker 执行 | adapters 输出 structured events，rejected/invalid_json/timeout 通过任务结果和观测事件体现 |

日志和 trace：

- `RequestIdMiddleware` 为每个 HTTP 请求绑定 `X-Request-Id`。
- Server 和 Dispatcher 都有独立 logging 配置。
- HTTP latency/request count、dispatcher ticks/inflight/overflow、worker unhealthy 等暴露为 Prometheus metrics。

## 9. 配置与运行

配置加载顺序：

| 配置 | 加载位置 |
|------|----------|
| Server runtime system config | 优先 `/cairn/dispatch.yaml`，否则 repo 根 `dispatch.yaml` |
| Dispatcher full config | CLI 参数 `--config` 指定 |
| Capabilities config | `/cairn/dispatch.capabilities.yaml` 或 repo 根 `dispatch.capabilities.yaml` |
| Docker Compose bind mount | 将本地 YAML 挂载到 `/cairn/` |

核心命令：

```bash
uv run --project cairn cairn serve
uv run --project cairn cairn dispatch --config dispatch.yaml
uv run --project cairn cairn dispatch --config dispatch.yaml --startup-healthcheck-only
uv run --project cairn cairn db migrate
docker compose up --build
```

重要配置项：

| 配置 | 说明 |
|------|------|
| `system.database.url` | PostgreSQL URL，SQLite 被显式拒绝 |
| `system.auth.jwt_secret` | JWT 签名密钥 |
| `system.auth.dispatcher_api_token` | Dispatcher API/reload token |
| `system.dispatcher.*` | reload、health addr |
| `workers[]` | Worker 后端、优先级、env、模型 |
| `container.*` | Worker image、network、capabilities、bind mounts |
| `tasks.bootstrap/reason/explore` | 超时和 reason max intents |
| `observability.*` | 记录范围、事件大小、retention |
| `capabilities.*` | MCP、skills、roles 和能力可用性 |

## 10. 基础设施与横切关注点

| 关注点 | 实现 |
|--------|------|
| 日志 | Python logging，Server/Dispatcher 分别配置 |
| Metrics | `prometheus-client`，Server `/metrics`，Dispatcher health server `/metrics` |
| Trace | contextvars trace id，HTTP 响应 `X-Request-Id` |
| Redaction | Server/Dispatcher 观测模块脱敏 token/key |
| 文件安全 | project_id/path 校验、symlink escape 检查、download size cap、危险 MIME 强制 attachment |
| 静态资源缓存 | SPA 和 static vendor 资源 `Cache-Control: no-store` |
| 容器隔离 | 每项目 worker container，Docker labels 管理生命周期 |
| 配置写入 | `ConfigStore` 临时文件 + fsync + replace，Docker bind mount EBUSY 时 fallback overwrite |

## 11. 测试策略

测试文件覆盖面：

| 测试文件 | 覆盖主题 |
|----------|----------|
| `test_auth.py` | JWT、登录、刷新、superuser 注册 |
| `test_path_security.py` | 文件路径、symlink escape、下载大小限制 |
| `test_ai_profile_*` | AI profile、secret、bridge、flow |
| `test_capability_*` | 能力配置和 admin 行为 |
| `test_mcp_http_transport.py` | MCP HTTP transport、bearer token、redaction |
| `test_observability*.py` | LLM events、文件和 retention |
| `test_db_*` | migration、PostgreSQL hardening |
| `test_worker_cli_adapters.py` | Worker CLI adapters |
| `test_yaml_config.py`, `test_proxy_settings.py` | YAML 配置和代理 |

当前验证状态：

- 仓库有 30 个 `test_*.py` 测试文件。
- 当前环境中 `pytest` 不在 PATH，`uv run python -m pytest ...` 报 `No module named pytest`；未能执行测试套件。

## 12. 待办与已知问题

显式标记：

| 类型 | 位置 | 说明 |
|------|------|------|
| SECURITY | `docker-compose.yaml` | Dispatcher 需要 Docker socket，注释已说明 docker.sock RCE blast radius |
| TODO | `server/static/vendor/*` | vendor 依赖内部 TODO，不属于项目业务代码 |
| XXX placeholder | `capabilities/templates/*` | 报告模板中的占位字段 |

审查发现：

| 严重度 | 问题 | 位置 | 影响 |
|--------|------|------|------|
| High | 多个管理面接口只要求登录，未要求 superuser | `server/app.py`, `routers/settings.py`, `routers/proxies.py`, `routers/capabilities.py`, `routers/ai_profiles.py` | 普通用户可改系统配置、代理、能力、AI profile |
| High | AI Profile secret 通过 API 明文返回 | `server/routers/ai_profiles.py` | 凭据泄露风险 |
| Medium | AI profile check request claim 为 read-then-update，缺少状态条件保护 | `server/routers/ai_profiles.py` | 多个消费者可能重复 claim 同一任务 |
| Medium | 测试依赖未完整声明 | `pyproject.toml` dev group 只有 `httpx` | 本地无法直接运行 pytest |

## 13. 隐藏细节与注意事项

| 标注 | 内容 |
|------|------|
| 注意 | Server 的全局鉴权只区分 public 和 authenticated；是否需要 superuser 要由各 router 单独声明。 |
| 注意 | Dispatcher service token 被建模为 `role=service` 的 synthetic superuser。 |
| 注意 | `dispatch.yaml` 同时被 Server 和 Dispatcher 使用，但 Dispatcher 通过 CLI 指定配置路径，Server 通过固定路径探测。 |
| 性能敏感 | 项目详情会构建完整 facts/intents/hints 图，项目规模变大后可能成为 hot path。 |
| 性能敏感 | LLM event 写入有批量接口和 event size limit，但保留策略依赖 retention loop。 |
| 向后兼容 | Prompt 模板要求固定变量，如 `{graph_yaml}`、`{intent_id}`、`{capability_instructions}`，配置模型会校验。 |
| 向后兼容 | Worker adapters 的输出结构驱动 fact/intent/complete 解析，变更需同步 parser 和测试。 |
