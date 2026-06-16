<!--
@ai: 本文件是项目的快速概览。当需要快速了解项目是什么、用了哪些技术、目录结构如何时，请优先阅读此文件。
如需深入了解架构细节，请查阅 ARCHITECTURE.md；如需了解具体实现，请查阅 CODEBASE_ANALYSIS.md。

@update: 本文件应在项目发生重大变更（如核心目标调整、技术栈升级、目录重构）时更新。

生成日期：2026-06-13
-->

# Cairn 项目概览

## 1. 项目名称与简介

**Cairn** 是一个基于 fact-intent graph 的协作式状态空间搜索引擎。项目以 AI 渗透测试、CTF、漏洞研究等任务为首批验证场景，但核心抽象是从已知 origin 到明确 goal 的路径搜索。

Cairn 采用 Blackboard Architecture。Server 维护事实、意图和提示构成的共享图；Dispatcher 读取图状态并调度任务；Worker Container 中的 AI Worker 执行 Bootstrap、Reason、Explore 三类任务，并将结果写回共享图。

## 2. 技术栈概览

| 层级 | 技术 |
|------|------|
| 语言/运行时 | Python 3.12+ |
| API 服务 | FastAPI, Uvicorn |
| 数据库 | PostgreSQL 16, SQLAlchemy 2, Alembic |
| 配置 | YAML, Pydantic v2 |
| 调度与运行 | ThreadPoolExecutor, Docker SDK, requests |
| 认证 | JWT, bcrypt |
| 观测 | Prometheus metrics, 结构化日志, LLM execution events |
| 前端 | 无构建 SPA, FastAPI partials, Alpine.js `CairnParts` slices, Tailwind CDN/vendor, Cytoscape |
| 部署 | Docker Compose, uv |

## 3. 目录结构

```text
Cairn/
├── README.md                         # 项目说明与快速开始
├── Dockerfile                        # Cairn app 镜像
├── docker-compose.yaml               # PostgreSQL、Server、Dispatcher、Worker image 编排
├── config.yaml                     # 本地运行配置
├── config.resources.yaml           # remote support、能力、角色、MCP 配置
├── cairn/
│   ├── pyproject.toml                # Python 包、依赖和 CLI 入口
│   ├── alembic.ini                   # Alembic 配置
│   ├── migrations/                   # PostgreSQL schema migration
│   ├── src/cairn/                    # Server、Dispatcher、Shared、Observability 分层源码
│   └── tests/                        # 单元与集成测试
├── capabilities/
│   ├── skills/                       # 领域能力 Skill
│   ├── roles/                        # Worker 角色提示
│   ├── payloads/                     # 安全测试 payload 库
│   └── templates/                    # 报告模板
├── container/
│   ├── Dockerfile                    # Worker 容器镜像
│   └── bin/                          # MCP stdio wrapper
```

## 4. 快速开始

```bash
docker pull ghcr.io/astral-sh/uv:python3.13-trixie
docker compose up --build
```

手动运行：

```bash
docker build ./container -t cairn-worker-container:mcp-camoufox
docker network create cairn
uv run --project cairn cairn serve
uv run --project cairn cairn dispatch --config config.yaml
```

数据库维护：

```bash
uv run --project cairn cairn db status
uv run --project cairn cairn db migrate
uv run --project cairn cairn db reset --yes
```

测试：

```bash
uv run --project cairn python -m pytest
uv run --project cairn python -m pytest -m 'not db'
uv run --project cairn python -m pytest -m db
```

无本地 PostgreSQL 时，DB 集成测试通过 availability probe clean skip；引用 `reset_postgres_db()` 的测试收集时自动标记为 `db`，`-m 'not db'` 不触发数据库初始化。

## 5. 关键链接

| 链接 | 说明 |
|------|------|
| `README.md` | 项目定位、架构图、Docker Compose 和手动启动方式 |
| `README/current-architecture.html` | 当前架构可视化材料 |
| `container/README.md` | Worker 容器说明 |
| `capabilities/README.md` | 能力目录说明 |
| `AI/ARCHITECTURE.md` | 架构与设计细节 |
| `AI/CODEBASE_ANALYSIS.md` | 全量代码分析 |
