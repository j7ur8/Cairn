<!--
@ai: 本文件记录项目的命名规范、允许例外和迁移策略。任何 AI 会话在新增文件、模块、类型、配置文件或执行重命名前，应先阅读此文件。
使用提示："请参考 NAMING.md 完成以下命名/重命名任务..."

@update: 如需更新本文档，请遵循以下原则：
1. 只记录项目当前采用的规范和明确允许的例外，不记录一次性讨论过程
2. 命名规范变化必须同步更新 ARCHITECTURE.md 或 CODEBASE_ANALYSIS.md 中受影响的路径描述
3. 修改后必须在 UPDATE.md 追加一条变更记录
4. 不得把外部 API 路径、JSON/YAML 字段、数据库表/列重命名建议写成已执行事实

生成日期：2026-07-07
-->

# Cairn Naming Conventions

命名变更只处理可读性与一致性，不改变外部 API 路径、JSON/YAML 字段、数据库表/列或运行行为，除非用户明确要求业务级迁移。

## 1. Core Rules

- Python 包、模块、函数、变量使用 `snake_case`。
- Python 类使用 `PascalCase`。
- Python 常量使用 `UPPER_SNAKE_CASE`。
- Python 私有函数/变量使用单下划线前缀，例如 `_decode_cursor()`。
- JavaScript 文件使用 `kebab-case.js`。
- JavaScript 函数/变量使用 `camelCase`。
- JavaScript 类/构造器使用 `PascalCase`。
- 测试文件使用 `test_*.py`。
- 协议/资源入口文件保持其协议要求的大写文件名，例如 `SKILL.md`、`ROLE.md`、`FILE_OUTPUTS.md`。

## 2. Backend/Layout Rules

FastAPI server code follows the current layered package names:

- `routers/`: HTTP route declaration and dependency wiring.
- `schemas/`: FastAPI/Pydantic request and response DTOs.
- `repositories/`: SQL and persistence access.
- `application/`: command/query orchestration over repositories and domain rules.
- `domain/`: SQL-free business rules and domain errors.
- `mappers/`: row/projection to contract conversion.
- `execution_config/`: immutable project execution snapshot assembly and persistence.
- `observability/`: LLM execution/event write and read paths.
- `security/`: JWT, password hash, path and user dependencies.

Application read/query modules use `*_queries.py`; mutating use cases use `*_commands.py` where the package already follows that split.

Dispatcher code uses the current split:

- `scheduler/`: loop assembly, project dispatch, task submission, runtime maintenance.
- `tasks/`: bootstrap/explore/reason execution, prompt rendering, result parsing, writeback.
- `runtime/`: Docker container, process, mount, cleanup, Cloak sidecar runtime.
- `protocol/`: HTTP client facets for Server APIs.
- `workers/adapters/`: Claude Code, Codex, and mock CLI drivers.

## 3. DTO/API Naming

- Request DTOs end in `Request`, for example `CreateProjectRequest`.
- Response DTOs end in `Response`, for example `ProjectPollStateResponse`.
- List items use domain nouns, for example `ProjectSummary`.
- Paged wrappers end in `Page`, for example `ProjectSummaryPage`.
- Incremental payloads describe the delta, for example `ProjectGraphDelta`.
- Event and execution DTOs use explicit nouns such as `ExecutionListResponse`, `EventViewResponse`, and `CreateEventsBatchRequest`.
- External API paths, JSON fields, database table/column names, and YAML keys are stable contracts and should not be renamed as a cosmetic cleanup.

## 4. Frontend Naming

- Frontend source lives under `cairn/src/cairn/server/static/js/`.
- App-level state modules use `state-*.js`, for example `state-core.js`, `state-ai-profiles.js`, `state-settings-admin.js`.
- Workspace state modules use `workspace/state-*.js`, for example `state-graph.js`, `state-llm-log.js`, `state-cloak.js`.
- Shared helpers live under `shared/` and use short kebab-case file names, for example `api-client.js`, `capability-selection.js`.
- HTML partials live under `server/partials/`; modal fragments live under `partials/modals/`.

## 5. Config/Resource Naming

- Root runtime files use `server.yaml`, `config.yaml`, and `config.resources.yaml`.
- Examples use `.example.yaml`; test fixtures use `.test.yaml`; mock fixtures use `.mock.yaml`.
- First-party MCP assets live under `capabilities/mcp/<mcp-id>/`.
- First-party Skills live under `capabilities/skills/<skill-id>/SKILL.md`.
- First-party Roles live under `capabilities/roles/<role-id>/ROLE.md`.
- Worker wrapper binaries live under `container/bin/` and may keep tool-specific names.

## 6. Allowed Exceptions

- `SKILL.md`, `ROLE.md`, `FILE_OUTPUTS.md`: protocol discovery requires exact names.
- `Dockerfile`: Docker tooling requires exact name.
- Alembic migration files keep revision-prefixed names.
- Vendor assets under `capabilities/**/tools/vendor/**` keep upstream filenames.
- Static vendor assets under `cairn/src/cairn/server/static/vendor/` keep upstream/minified filenames.
- Ecosystem config files such as `tailwind.config.js` keep their tool names.
- Container wrapper names such as `cairn-browser-mcp` and `cairn-resources-mcp-stdio` keep their runtime contract names.

## 7. Migration Policy

1. Prefer updating internal source imports to canonical names immediately.
2. If a compatibility shim is unavoidable, keep it explicit, documented, and time-boxed.
3. Add or preserve tests proving removed shim paths do not reappear.
4. Do not rename externally visible API routes, JSON fields, database identifiers, YAML keys, or protocol files as part of internal cleanup.
5. Run `cd cairn && uv run python scripts/check_naming.py` before merging naming-sensitive changes.
