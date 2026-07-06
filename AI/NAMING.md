# Cairn Naming Conventions

本文件是 Cairn 的命名准则入口，用于 AI/工程协作时统一文件、模块和类型命名。命名变更只处理可读性与一致性，不改变外部 API 路径、JSON/YAML 字段、数据库表/列或运行行为。

## Core Rules

- Python 包、模块、函数、变量使用 `snake_case`。
- Python 类使用 `PascalCase`。
- Python 常量使用 `UPPER_SNAKE_CASE`。
- Python 私有函数/变量使用单下划线前缀，例如 `_decode_cursor()`。
- JavaScript 文件使用 `kebab-case.js`。
- JavaScript 函数/变量使用 `camelCase`。
- JavaScript 类/构造器使用 `PascalCase`。
- 示例配置文件使用 `config.example.yaml`。
- 测试配置文件使用 `config.test.yaml`。
- mock 配置文件使用 `config.mock.yaml` 或 `server.mock.yaml`。
- Root config files use the current split: `server.yaml`, `config.yaml`, and `config.resources.yaml`; examples/tests/mocks keep the same stem with `.example.yaml`, `.test.yaml`, or `.mock.yaml` where present.
- First-party MCP assets live under `capabilities/mcp/<mcp-id>/`; sidecar internals may keep tool/runtime filenames such as `Dockerfile`, `entrypoint.sh`, and Node `.mjs` files.

## Backend Layout

FastAPI server code follows the existing layered package names:

- `routers/`: HTTP route declarations and dependency wiring.
- `schemas/`: server-only FastAPI/Pydantic request and response DTOs.
- `repositories/`: SQL and persistence access.
- `application/`: command/query orchestration.
- `domain/`: SQL-free business rules.
- `mappers/`: row/projection to contract conversion.

Application read/query modules use `*_queries.py`; mutating use cases use `*_commands.py` where the package already follows that split.

## DTO Names

- Request DTOs end in `Request`, for example `CreateProjectRequest`.
- Response DTOs end in `Response`, for example `ProjectPollStateResponse`.
- List items use domain nouns, for example `ProjectSummary`.
- Paged list wrappers end in `Page`, for example `ProjectSummaryPage`.
- Incremental payloads describe the delta, for example `ProjectGraphDelta`.

## Allowed Exceptions

- Protocol/resource files keep their required names: `SKILL.md`, `ROLE.md`, `FILE_OUTPUTS.md`, and Docker `Dockerfile`.
- Alembic migration files keep their revision-prefixed names.
- Tool-specific config files may keep ecosystem names such as `tailwind.config.js`.
- Vendored tool assets under `capabilities/**/tools/vendor/**` keep upstream filenames, including YAML files with underscores; first-party YAML files still must avoid underscores.
- Removed compatibility shims must stay removed; new code must use canonical paths.

## Current Canonical Renames

- `server/models_pkg/` is now `server/schemas/`.
- `server/application/project_read.py` is now `server/application/project_queries.py`.
- `dispatcher/workers/adapters/claudecode.py` is now `dispatcher/workers/adapters/claude_code.py`.
- Frontend state files use kebab-case names such as `state-projects.js`, `state-graph.js`, and `state-settings-admin.js`.
- Mock config files use `config.mock.yaml` and `server.mock.yaml`.

## Migration Policy

1. Prefer updating internal source imports to canonical names immediately.
2. If a future compatibility shim is unavoidable, keep it explicit, documented, and time-boxed to one CI-stable migration window.
3. Add or preserve tests that prove removed shim paths do not reappear.
4. Do not rename externally visible API routes, JSON fields, database identifiers, YAML keys, or protocol files.
5. Run `cd cairn && uv run python scripts/check_naming.py` before merging naming-sensitive changes.
