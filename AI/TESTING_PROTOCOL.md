<!--
@ai: 本文件定义 Cairn 的本地回归测试协议。任何涉及 UI、Docker、dispatcher、capabilities、AI profile、replay、项目状态流转的修改，在合并前都应先阅读并执行本文件。
优先级：当本文档与零散备注冲突时，以本文档为准。

@update:
1. 每次修改测试步骤、通过标准或回归范围时，必须同步更新 `AI/UPDATE.md`
2. 新增前端关键交互时，补充对应的稳定选择器和浏览器回归步骤
3. 若本地闭环或真实外部依赖层的执行条件变化，必须更新“前置条件”和“验收分层”

生成日期：2026-06-09
-->

# Cairn 回归测试协议

## 1. 目的

每次更新后，必须使用 Docker 启动 Cairn 服务，并通过本机 Chrome 的远程调试能力配合 `chrome-devtools` MCP 做人工式全功能回归。目标不是只验证页面能打开，而是验证关键功能链路、状态流转、网络请求、前端控制台和后端服务状态都正常。

## 2. 强制流程

1. 运行现有 Python 测试集，确认没有静态回归。
2. 使用 Docker 启动服务栈，确认 `cairn-server` 和 `cairn-dispatcher` 健康。
3. 启动本机 Chrome 远程调试：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0 \
  --user-data-dir=/tmp/cairn-chrome-profile
```

4. 访问 Docker 启动的 Cairn UI，并用 `chrome-devtools` MCP 完成全部关键页面点击与表单操作。
5. 在回归过程中持续检查：
   - 浏览器 `console` 无 error
   - 关键网络请求无失败
   - 后端无 5xx / traceback
   - UI 展示与后端副作用一致
6. 失败后先修复，再完整重跑；不允许只补跑单个按钮后宣称通过。
7. 将本次回归结论追加到 `AI/UPDATE.md`。

## 3. 验收分层

### A. 本地闭环层

默认必跑，且必须通过。

- 使用 Docker 启动服务
- 浏览器必须通过本机 Chrome 远程调试接入
- 项目、设置、代理、AI Profiles、Capabilities、Replay、导出、文件、Execution Log 等主路径必须可操作
- 若需要稳定复现 dispatcher/worker 链路，优先使用 `dispatch.test.yaml` 的 `mock` worker 配置

### B. 真实外部依赖层

当 `.env` 中真实密钥与外部服务可用时追加执行。

- 真实 AI Profile 健康检查
- 至少一条真实 worker 链路
- 若某能力依赖真实外部服务或远程 MCP，需要记录是否执行及结果

若真实外部依赖层未执行，必须在 `AI/UPDATE.md` 明确标记“未执行”，不能默认为通过。

## 4. 浏览器回归范围

### 认证

- 登录
- 会话恢复
- 登出

### 项目列表与项目生命周期

- 查看列表
- 新建项目
- 重命名
- 停止 / 恢复
- 删除
- 从 completed 状态重开
- Snapshot 查看

### 项目图与人工操作

- 打开项目图
- 选择 facts
- 创建 intent
- heartbeat
- release
- conclude
- complete
- add hint
- 布局切换
- fit graph

### Replay

- 从已完成项目打开 replay 配置
- 创建 replay
- 播放 / 暂停 / 重启 / 退出

### 设置页

- Server Settings 读取与保存
- Proxy CRUD
- AI Profile CRUD
- Capability 管理、probe、编辑、删除

### 文件与导出

- 新建项目附件上传
- 项目文件列表
- 导出 YAML / Timeline
- 复制导出内容

### Observability

- Execution Log 面板展开
- execution 过滤
- 事件展开
- 可见事件筛选

## 5. 通过标准

- 所有关键功能可完成，不出现阻断性错误
- 浏览器控制台无 error
- 关键网络请求无失败
- 后端健康检查为 `ok`
- 破坏性操作仅作用于测试数据，并在回归结束后清理

## 6. 本地辅助文件

- `dispatch.test.yaml`
  - 本地闭环 dispatcher 配置，使用 `mock` worker 和 `mock` prompt group
- `scripts/run-local-regression.sh`
  - 执行 Python 测试、启动 Docker 栈并等待健康

## 7. 执行记录要求

每次执行本协议后，在 `AI/UPDATE.md` 追加：

- 修改摘要
- 本地闭环层结果
- 真实外部依赖层结果或未执行说明
- 浏览器回归范围摘要
- 未解决问题（如有）
