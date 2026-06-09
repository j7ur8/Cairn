<!--
@ai: 本文件是项目的快速概览。当需要快速了解项目是什么、用了哪些技术、目录结构如何时，请优先阅读本文件。
如需深入了解架构细节，请查阅 ARCHITECTURE.md；如需了解具体实现，请查阅 CODEBASE_ANALYSIS.md。

@update: 本文件应在项目发生重大变更（如核心目标调整、技术栈升级、目录重构）时更新。

生成日期：2026-06-09
-->

# Cairn 项目概览

## 项目名称与简介

Cairn 是一个基于事实图的通用问题求解引擎，以 penetration testing、CTF、漏洞研究等“从 origin 到 goal 的未知路径搜索”场景为首批验证领域。

项目采用 Blackboard Architecture：Server 保存事实、意图、提示和运行快照；Dispatcher 读取图状态、调度 bootstrap/reason/explore 三类任务；Worker 在容器内执行 AI 后端命令并通过 API 写回事实图。系统不依赖固定工作流，而是让事实图驱动任务生成和探索。

## 技术栈概览

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+、FastAPI、Pydantic、Click、Uvicorn |
| 前端 | 无构建 SPA，Alpine.js、Tailwind runtime、Cytoscape 及布局插件 |
| 数据库 | PostgreSQL、SQLAlchemy ORM metadata、Alembic migrations |
| Dispatcher | Python scheduler、Docker SDK、Requests、Tenacity、worker adapter |
| 安全 | JWT、bcrypt、cryptography、路径安全校验、secret 加密 |
| 部署 | Docker Compose、worker container image、host Docker socket |

## 目录结构

```text
project-root/
├── README.md                  # 项目定位、架构说明、启动方式
├── Dockerfile                 # 应用镜像
├── dispatch.yaml              # Dispatcher worker/capability 配置
├── cairn/
│   ├── pyproject.toml         # Python 包与依赖
│   ├── src/cairn/
│   │   ├── cli.py             # cairn serve / dispatch / db 命令入口
│   │   ├── server/            # FastAPI API、PostgreSQL、模型、安全、静态 SPA
│   │   ├── dispatcher/        # 调度循环、容器运行时、任务执行、worker 协议
│   │   └── observability/     # 日志、trace、metrics
│   └── tests/                 # unittest 测试集
├── capabilities/              # MCP、技能、角色、payload、报告模板
├── container/                 # Worker container 构建上下文和运行脚本
├── datas/                     # 本地运行数据、附件、项目文件
└── AI/                        # 本次生成的项目审查文档
```

## 快速开始

```bash
# Docker Compose 启动 server + dispatcher
docker compose up --build

# 手动构建 worker image
docker build ./container -t cairn-worker-container:mcp-camoufox

# 手动启动 API server
uv run --project cairn cairn serve

# 手动启动 dispatcher
uv run --project cairn cairn dispatch --config dispatch.yaml

# 只跑 dispatcher 启动健康检查
uv run --project cairn cairn dispatch --config dispatch.yaml --startup-healthcheck-only
```

## 回归测试要求

- 每次更新后，必须先跑 `cairn/tests/`，再用 Docker 启动服务，并使用本机 Chrome 远程调试 + `chrome-devtools` MCP 执行人工式功能回归。
- 测试真相源见 `AI/TESTING_PROTOCOL.md`。
- 本地闭环调度可使用 `dispatch.test.yaml` 的 `mock` worker 配置；默认运行辅助脚本见 `scripts/run-local-regression.sh`。

## 关键链接

| 资源 | 路径 |
|------|------|
| 项目 README | `README.md` |
| Python 包配置 | `cairn/pyproject.toml` |
| Server 入口 | `cairn/src/cairn/server/app.py` |
| CLI 入口 | `cairn/src/cairn/cli.py` |
| Dispatcher 主循环 | `cairn/src/cairn/dispatcher/scheduler/loop.py` |
| 数据库 ORM schema | `cairn/src/cairn/server/orm.py` |
| 数据库 migrations | `cairn/migrations/` |
| Worker container | `container/Dockerfile` |
| Capabilities | `capabilities/README.md` |
| 测试协议 | `AI/TESTING_PROTOCOL.md` |
| 本地回归配置 | `dispatch.test.yaml` |
