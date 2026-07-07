<!--
@ai: 本文件是项目的快速概览。当需要快速了解项目是什么、用了哪些技术、目录结构如何时，请优先阅读此文件。
如需深入了解架构细节，请查阅 ARCHITECTURE.md；如需了解具体实现，请查阅 CODEBASE_ANALYSIS.md。

@update: 本文件应在项目发生重大变更（如核心目标调整、技术栈升级、目录重构）时更新。

生成日期：2026-07-07
-->

# Cairn 项目概览

## 1. 项目名称与简介

**Cairn** 是一个基于 fact-intent graph 的协作式状态空间搜索与 Agent 调度系统。

项目把未知状态空间搜索任务拆成 Project、Fact、Intent、Hint 与 LLM execution log。Server 维护共享黑板、配置快照、认证和观测数据；Dispatcher 按图状态调度 Bootstrap、Explore、Reason 三类任务；Worker 容器运行 Claude Code、Codex 或 mock 适配器，并可注入 MCP、Skill、Role 与项目级 CloakBrowser sidecar。

## 2. 技术栈概览

| 层级 | 技术 |
|------|------|
| 语言/运行时 | Python 3.12+ |
| API 服务 | FastAPI, Uvicorn |
| 数据库 | PostgreSQL 16, SQLAlchemy 2, Alembic |
| 配置 | YAML, Pydantic v2 |
| 调度与运行 | ThreadPoolExecutor, Docker SDK, requests, tenacity |
| Worker | Claude Code, Codex, mock driver |
| 认证 | JWT HS256, bcrypt password hash |
| 观测 | Prometheus metrics, structured logs, LLM execution events |
| 前端 | No-build SPA, FastAPI partials, Alpine ES modules, Cytoscape, Tailwind |
| 部署 | Docker Compose, uv, worker image, optional CloakBrowser sidecar |

## 3. 目录结构

```text
Cairn/
├── README.md                         # 项目说明与快速开始
├── Dockerfile                        # Cairn app 镜像
├── docker-compose.yaml               # PostgreSQL、Server、Dispatcher、Worker 编排
├── start.sh / stop.sh                # 本地 compose 启停入口
├── server.yaml                       # 固定部署、敏感值、数据库、worker runtime
├── config.yaml                       # Server/Dispatcher/task/observability/worker pool 配置
├── config.resources.yaml             # Servers、MCP、Skills、Roles 资源目录
├── cairn/
│   ├── pyproject.toml                # Python 包、依赖、CLI 入口
│   ├── migrations/                   # Alembic PostgreSQL migration
│   ├── src/cairn/                    # Server、Dispatcher、Shared 源码
│   └── tests/                        # 单元、集成、架构 guardrail 测试
├── capabilities/
│   ├── skills/                       # Skill 协议资源
│   ├── roles/                        # Role prompt 资源
│   ├── mcp/                          # MCP sidecar/source assets
│   ├── payloads/                     # 测试 payload 资源
│   └── templates/                    # 报告模板
├── container/                        # Worker 容器镜像与 MCP wrapper
├── README/                           # 图片与架构可视化素材
└── AI/                               # 本项目给 AI/工程协作用的架构文档
```

## 4. 快速开始

```bash
docker pull ghcr.io/astral-sh/uv:python3.13-trixie
docker build ./container -t cairn-worker-container:mcp-camoufox
docker build ./capabilities/mcp/js-reverse-mcp/sidecar -t cairn-cloak-browser:js-reverse
./start.sh
```

开发/维护常用命令：

```bash
uv run --project cairn cairn config check --config config.yaml
uv run --project cairn cairn serve
uv run --project cairn cairn dispatch --config config.yaml
cd cairn && uv run pytest
```

## 5. 关键链接

| 文件 | 用途 |
|------|------|
| `README.md` | 项目说明、启动方式、当前架构图入口 |
| `AI/ARCHITECTURE.md` | 系统架构、启动链路、模块职责 |
| `AI/CODEBASE_ANALYSIS.md` | 代码结构、数据模型、API、测试策略 |
| `AI/NAMING.md` | 命名规范、例外、迁移策略 |
| `cairn/tests/test_architecture_boundaries.py` | 架构文档与边界约束 guardrail |
