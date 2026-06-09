<!--
@ai: 本文件记录项目分析的变更历史。每次运行 project-review 技能时，新增的变更摘要会追加到本文件顶部。
请勿手动编辑本文件 - 由 AI 自动维护。
-->

# 更新日志

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
