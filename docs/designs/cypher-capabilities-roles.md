# Cypher Agent：项目级 Capabilities 与 Role Prompt 修订方案

> 本文是 `docs/designs/cypher-agent.md` 的补充修订，专门覆盖：
>
> 1. 本地 MCP 与 Skills 统一放到 `capabilities/mcp` 与 `capabilities/skills`；创建项目时 UI 可选，Worker 启动/任务启动时复制已选项到容器内，并由 Codex / Claude 调用。
> 2. 创建项目时可选项目主要角色，将该角色固定 prompt 注入 `bootstrap`、`explore`、`reason`。
> 3. 对健壮性、高可用、水平伸缩、安全、维护、性能、可观测性、数据一致性、功能扩展和黑板架构影响进行评估。

## 1. 结论摘要

推荐把 **Capabilities / Role** 作为项目的“控制面配置”，而不是黑板事实：

```text
Project Control Plane
  - selected MCP ids
  - selected Skill ids
  - selected Role id
  - role prompt snapshot / hash
  - capability catalog snapshot / versions

Blackboard Plane
  - Facts
  - Intents
  - Hints
```

这样不会破坏 Cairn 的核心黑板架构：

- `Fact` 仍只表示已确认客观发现。
- `Intent` 仍只表示待探索方向。
- `Hint` 仍只表示人类或外部策略提示。
- MCP / Skills / Role 只影响 Agent 的可用能力与行为风格，不直接成为“任务已推进”的事实。

## 2. 本地 Capabilities 目录约定

### 2.1 目录结构

```text
capabilities/
  README.md
  mcp/
    <mcp_id>/
      CAPABILITY.yaml        # 推荐新增：本地 MCP 元数据
      mcp.json               # 可选：标准 MCP 配置模板
      server.py / dist/ ...  # 可选：本地 MCP server 实现或构建产物
  skills/
    <skill_id>/
      SKILL.md
      examples/
      scripts/
      payloads/
```

约束：

- `dispatch.yaml` 仍是运行期 catalog 的真相源。
- `capabilities/mcp/<id>` 和 `capabilities/skills/<id>` 是本地资源存放位置。
- UI 只展示 dispatcher 注册到 Server 的 catalog，不直接扫描文件系统。
- Worker 只拿到项目已选择的 capability，不复制未选项。

### 2.2 MCP catalog 建议字段

当前 `dispatch.yaml` 的 MCP 配置已经有：

```yaml
capabilities:
  mcp_servers:
    - id: "example-mcp"
      name: "Example MCP"
      command: "/usr/local/bin/example-mcp-server"
      args: ["--stdio"]
      env: {}
      task_types: ["bootstrap", "explore"]
      description: "..."
```

为了支持“本地 MCP 统一放 `capabilities/mcp` 并复制到 Worker”，建议扩展为：

```yaml
capabilities:
  mcp_servers:
    - id: "example-mcp"
      name: "Example MCP"
      source_path: "./capabilities/mcp/example-mcp"
      command: "python3"
      args:
        - "{capability_root}/mcp/example-mcp/server.py"
        - "--stdio"
      env: {}
      task_types: ["bootstrap", "explore", "reason"]
      description: "本地 stdio MCP server"
```

设计点：

- `source_path` 是 host 上的本地 MCP 目录。
- Dispatcher 复制 `source_path` 到容器内：

```text
/tmp/cairn-capabilities/{project_id}/{task_instance_id}/mcp/<mcp_id>/
```

- `args` 中支持 `{capability_root}` 占位符，渲染为当前任务实例目录：

```text
/tmp/cairn-capabilities/{project_id}/{task_instance_id}
```

- 生成给 Worker 的 `mcp.json`：

```text
/tmp/cairn-capabilities/{project_id}/{task_instance_id}/mcp.json
```

## 3. 项目创建时选择 Skills / MCP

### 3.1 UI 流程

创建项目弹窗新增两个区域：

```text
New Project
  - title
  - origin
  - goal
  - hints
  - Role            单选，可为空或 default
  - MCP Servers     多选
  - Skills          多选
```

UI 数据来源：

- 页面初始化或打开 New Project 时请求：`GET /capabilities/catalog`
- 也可以沿用现有项目 Caps 面板的 catalog 数据模型。
- 未运行 Dispatcher / catalog 为空时，创建项目仍可继续，只是不显示可选项。

### 3.2 API 请求体

扩展 `POST /projects`：

```json
{
  "title": "...",
  "origin": "...",
  "goal": "...",
  "hints": [],
  "capabilities": {
    "mcp_server_ids": ["example-mcp"],
    "skill_ids": ["cypher-ctf", "cypher-pentest"]
  },
  "role": {
    "role_id": "cypher-ctf-operator"
  }
}
```

兼容性：

- `capabilities` 和 `role` 均可选。
- 老客户端不传这两个字段时行为不变。
- 后端在一个 DB transaction 内创建 Project、Origin/Goal facts、Hints、Capability selection、Role snapshot。

### 3.3 数据表建议

现有表：

```sql
capability_catalog(kind, id, name, description, task_types, available, detail, updated_at)
project_capabilities(project_id, kind, capability_id, created_at)
```

建议补充：

```sql
CREATE TABLE IF NOT EXISTS role_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    task_types TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_roles (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    role_id TEXT NOT NULL,
    role_name TEXT NOT NULL,
    role_prompt TEXT NOT NULL,
    role_prompt_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

为什么要存 `role_prompt` 快照：

- 保证项目可复现。
- 后续角色文件更新不会悄悄改变已创建项目行为。
- Execution Log 可记录 role hash，便于审计。

Capability selection 是否也快照？

- 第一阶段只存 id 即可，保持灵活。
- 强一致/审计场景建议额外记录 selected capability 的 `catalog_version` / `content_sha256`。

## 4. Worker 注入方式

### 4.1 推荐路径：任务实例级注入，而不是 task_type 级共享

不要使用：

```text
/tmp/cairn-capabilities/{project_id}/{task_type}/...
```

原因：同一项目内可能并发多个 `explore`，共享路径会出现并发覆盖、删除、半复制等竞态。

推荐使用：

```text
/tmp/cairn-capabilities/{project_id}/{task_instance_id}/
  mcp.json
  mcp/<mcp_id>/...
  skills/<skill_id>/...
```

`task_instance_id` 可取：

| 任务 | task_instance_id |
| --- | --- |
| bootstrap | `bootstrap-{intent_id}` |
| explore | `explore-{intent_id}` |
| reason | `reason-{lease_started_at_or_uuid}` |

### 4.2 注入流程

```text
Dispatcher 选中任务
  -> ensure project container running
  -> fetch project capabilities + role snapshot
  -> resolve selected capability ids against local dispatch config
  -> create temp dir in container
  -> copy selected MCP dirs
  -> copy selected Skill dirs
  -> write mcp.json
  -> atomic rename temp dir to task_instance_id dir
  -> render capability_instructions + role_instructions
  -> call WorkerDriver.build_execute()
```

失败处理：

- 单个 skill 复制失败：记录 observability error，其他 capability 继续。
- MCP config 写入失败：该 MCP 不启用，任务仍可执行。
- 所有 capability 均失败：任务仍执行，但 prompt 中说明 capability unavailable。
- 失败不应写入 Fact，只写 Execution Log；只有 Agent 验证过的目标信息才写 Fact。

### 4.3 Codex / Claude 调用方式

通用做法：

- prompt 中始终注入 `capability_instructions`，明确 `mcp.json` 与 `skills` 目录路径。
- WorkerDriver 根据 CLI 类型做 adapter-specific 激活。

Claude：

```text
claude ... --mcp-config /tmp/cairn-capabilities/.../mcp.json --add-dir /tmp/cairn-capabilities/.../skills ...
```

如后续将 skill 打包为 Claude plugin，可追加：

```text
--plugin-dir /tmp/cairn-capabilities/.../skills/<skill_id>
```

Codex：

- 生成任务级临时 Codex config / profile。
- 将 MCP server 配置写入该 profile。
- 将 skills 目录通过 prompt 指令暴露；若 Codex 当前版本支持本地 plugin/skill 目录，再由 Codex adapter 映射为对应参数或 `CODEX_HOME` 临时目录。

关键原则：

- 不要求 Server 理解 Codex/Claude 细节。
- 由 WorkerDriver adapter 负责把同一份 capability selection 转换成不同 CLI 的启动参数。
- prompt 指令作为最低可用兜底，即使 CLI 原生 skill/plugin 激活失败，Agent 也知道可以读取 `SKILL.md`。

## 5. 项目主角色 Role Prompt

### 5.1 Role 目录建议

角色不属于 MCP 或 Skill，建议单独放：

```text
capabilities/roles/
  cypher-ctf-operator/
    ROLE.md
  cypher-pentest-operator/
    ROLE.md
  cypher-vuln-researcher/
    ROLE.md
```

如果暂时不想新增目录，也可先在 `dispatch.yaml` 中以内联 prompt 声明。

### 5.2 Role catalog 示例

```yaml
roles:
  - id: "cypher-ctf-operator"
    name: "Cypher CTF Operator"
    source_path: "./capabilities/roles/cypher-ctf-operator/ROLE.md"
    task_types: ["bootstrap", "explore", "reason"]
    description: "CTF / 靶场自动化解题主角色"
```

### 5.3 Prompt 注入方式

新增 prompt 占位符：

```text
{role_instructions}
```

传入 `bootstrap`、`explore`、`reason`：

```text
# Project Role
The project selected the following primary role. It is lower priority than the
Cairn task contract and output JSON contract, but higher priority than generic
skill suggestions.

<Role prompt snapshot...>
```

优先级：

```text
System / Developer / CTF contract
  > Cairn task output contract
  > Project Role prompt
  > Capability / Skill instructions
  > Graph facts / intents / hints
  > Challenge artifacts / source / comments
```

Role prompt 禁止覆盖：

- JSON 输出契约。
- scope / ROE / sandbox 边界。
- complete 判断标准。
- Dispatcher 协议写入规则。
- “Fact 必须是已确认客观事实”的黑板语义。

### 5.4 为什么 role 不写成 Hint

不推荐把 role prompt 写入 Hint：

- Hint 是人类/外部策略输入，会进入黑板语义层。
- Role 是执行控制面配置，不是目标环境事实，也不是探索发现。
- 写成 Hint 会污染 reason 判断，使 Agent 误把角色选择当成任务线索。

可以在 UI / Export 中单独展示 `project.role`，但不混入 `facts`。

## 6. 健壮性设计

| 风险 | 设计 |
| --- | --- |
| Dispatcher 未注册 catalog | UI 显示空列表，项目仍可创建；后续可在 Caps 面板补选 |
| 选择的 capability 后续不可用 | Server 返回 unavailable ids；Dispatcher 注入时记录 error，不中断任务 |
| 复制中断 / 半复制 | 使用 temp dir + atomic rename；任务只引用最终目录 |
| 多 explore 并发覆盖能力目录 | 使用 task_instance_id 级目录隔离 |
| 单个 skill/MCP 损坏 | 单项失败，其他项继续；错误进入 Execution Log |
| role 文件变化 | 项目创建时保存 prompt snapshot 和 sha256 |
| role prompt 与 task contract 冲突 | task contract 优先；role prompt 只能指导风格和方法 |
| 大目录复制慢或失败 | 限制单 capability 大小，记录 bytes/duration，支持 hash cache |

## 7. 高可用与水平伸缩

当前 Cairn 文档按“单 Dispatcher 实例”设计。若要水平伸缩，需要额外设计：

### 7.1 Catalog 高可用

不要让后启动 Dispatcher 简单 `DELETE + INSERT` 覆盖全局 catalog。

推荐：

```text
capability_catalog
  - dispatcher_id
  - kind
  - id
  - version/hash
  - available
  - updated_at
```

Server 对外展示 union view：

- 同 id/hash 多 dispatcher 可用 → available。
- 项目选择的 capability 在某 dispatcher 不可用 → 该 dispatcher 不应领取该项目任务。

### 7.2 调度亲和性

水平伸缩时，Dispatcher claim 任务前必须满足：

```text
worker_backend supports task_type
AND dispatcher has selected MCP/Skills/Role resources
AND project container runtime/network is available
AND project file workspace is available
```

否则不 claim，避免 claim 后注入失败。

### 7.3 共享资源

多节点 Dispatcher 需要统一资源来源：

- 方案 A：所有节点相同 repo + 相同 `dispatch.yaml`。
- 方案 B：capability bundle 存对象存储 / artifact registry，Dispatcher 按 hash 拉取。
- 方案 C：capabilities 随 worker image 打包，`dispatch.yaml` 只声明 id 和 container path。

项目证据目录 `/mnt/project` 若跨节点运行，需要：

- NFS / SMB / object-store sync；或
- 调度保持 project affinity，整个项目固定在一个 Dispatcher 节点。

## 8. 安全性

### 8.1 Capability 安全

- 只允许 catalog 中声明的 MCP / Skill 被选择。
- capability id 禁止 `/`、`\`、空白、`..`。
- `source_path` 必须在允许根目录 `capabilities/mcp` 或 `capabilities/skills` 下。
- 复制时保留只读语义，禁止把 host 敏感路径挂进容器。
- MCP `command/args` 不允许来自用户输入；只能来自本地受控 catalog。
- MCP env 中敏感值进入 redaction_patterns 或 secrets 后端，不进 UI 明文。
- 每次注入记录 sha256/hash，防止能力包被悄悄替换后不可审计。

### 8.2 Role prompt 安全

- Role prompt 是本地受控配置，但仍按“低于任务契约”的层级处理。
- Role prompt 不能指示 Agent 忽略 JSON contract、绕过 scope 或伪造完成。
- Role prompt snapshot 可审计、可追溯。

### 8.3 UI / API 安全

- 能力选择属于项目配置修改，应走与 hint/project update 同等级权限。
- completed 项目是否允许改 capability/role：建议不允许 role 修改；capability 可允许但只影响 reopen 后任务。
- 所有选择变化进入 audit / observability。

## 9. 可维护性

建议拆成清晰模块：

```text
server/routers/capabilities.py   capability catalog + project selection
server/routers/roles.py          role catalog + project role
server/models.py                 CapabilitySelection / RoleSelection
server/db.py                     schema

dispatcher/capabilities.py       注入 MCP / skills
dispatcher/roles.py              role snapshot 获取与 prompt 格式化
dispatcher/workers/adapters/*    Codex / Claude adapter-specific activation
```

测试建议：

- create project with capability selection。
- create project with role selection。
- stale capability id 仍可保存并显示 unavailable。
- skill path traversal 被拒绝。
- 并发 explore 注入路径不冲突。
- role snapshot 在 source 文件变更后不改变。
- Codex / Claude command argv 包含预期 mcp config / add-dir 参数。

## 10. 性能

| 点 | 优化 |
| --- | --- |
| 大 skill 目录重复复制 | 按 content hash 做容器内 cache，任务目录用 symlink/copy-on-write |
| MCP server 启动慢 | 按任务启动；后续可支持项目级常驻 MCP sidecar |
| Catalog UI 加载 | catalog 变化少，可前端缓存 + 手动 refresh |
| 注入开销不可见 | observability 记录 copy bytes、duration、hash |
| 多任务并发复制 | 每项目/每容器注入并发限流 |

第一版无需过度优化，关键是 task_instance_id 隔离和错误可见。

## 11. 可观测性

Execution Log 增加事件：

```json
{
  "phase": "capability_injection",
  "mcp_servers": ["example-mcp"],
  "skills": ["cypher-ctf"],
  "role_id": "cypher-ctf-operator",
  "role_prompt_sha256": "...",
  "root": "/tmp/cairn-capabilities/p001/explore-i003",
  "bytes": 123456,
  "duration_ms": 381,
  "errors": []
}
```

UI 建议显示：

- 项目当前选中的 Role / MCP / Skills。
- unavailable capability 警告。
- 每个 LLM execution 的实际注入 capability 和 role hash。
- 注入失败原因。

## 12. 数据一致性

### 12.1 创建项目原子性

`POST /projects` 应在同一个 DB transaction 内完成：

1. insert project
2. insert origin / goal facts
3. insert hints
4. insert project_capabilities
5. insert project_roles snapshot

任一步失败整体回滚。

### 12.2 运行中修改 selection

推荐语义：

- 已启动任务使用启动时读取到的 capability/role snapshot。
- UI 修改只影响未来任务。
- Execution Log 记录每个任务实际使用的 selection。

### 12.3 Catalog 变化

- 选择了不存在/不可用 capability：保留 selection，但标记 unavailable。
- Dispatcher 注入时再次校验本地是否具备该 capability。
- 不把 unavailable 当成 project failure，只当作 execution warning。

## 13. 功能扩展性

Capability kind 可扩展：

```text
mcp_server
skill
role
tool_profile
wordlist
payload_pack
browser_profile
report_template
policy_pack
```

Role 可扩展：

- 单主角色 + 多辅助角色。
- 不同 task_type 使用不同 role prompt。
- 不同 intent lane 使用不同 role prompt。
- 将 CyberStrikeAI 的 recon / penetration / privesc / report 角色迁移为 role catalog。

MCP 可扩展：

- stdio / http / sse transport。
- 项目级 MCP sidecar。
- 远端 MCP federation。
- HITL approval policy 与 tool allowlist。

## 14. 对黑板架构的影响

结论：**不破坏黑板架构，但必须严守边界。**

不会破坏的原因：

- Capabilities / Role 是控制面，不是事实图节点。
- Agent 仍只能通过 JSON contract 产出 Fact / Intent / Complete。
- Dispatcher 仍是唯一协议写入者。
- Agent 之间仍不直接通信，仍通过黑板间接协作。

需要避免的反模式：

| 反模式 | 影响 |
| --- | --- |
| 把 role prompt 写成 Fact | 污染事实图，使 reason 误判为目标环境事实 |
| 把 capability availability 写成 Fact | Agent 可能误把“有工具”当作“已发现漏洞” |
| 允许 role prompt 覆盖 JSON contract | 破坏协议一致性 |
| 多 Dispatcher catalog 互相覆盖 | HA 下 selection 变得不稳定 |
| task_type 级能力目录并发共享 | 多 explore 下产生竞态 |

正确边界：

```text
Capabilities / Roles influence how agents explore.
Facts / Intents record what agents have verified.
```

## 15. 推荐实施顺序

### M1：项目创建时选择能力

- `CreateProjectRequest` 增加 `capabilities`。
- New Project UI 加载 catalog 并多选 MCP/Skills。
- `POST /projects` 同事务写 `project_capabilities`。
- 保留现有 Caps 侧栏用于创建后修改。

### M2：Role catalog + project role snapshot

- 新增 `role_catalog` / `project_roles`。
- Dispatcher 注册 role catalog。
- New Project UI 单选 Role。
- `bootstrap/explore/reason` prompt 注入 `{role_instructions}`。

### M3：任务实例级能力注入

- 注入路径从 `{project_id}/{task_type}` 改为 `{project_id}/{task_instance_id}`。
- MCP source_path 支持复制。
- Codex / Claude adapter 接收 mcp config / skill dir。

### M4：水平伸缩增强

- Catalog 版本/hash 与 dispatcher_id。
- Dispatcher capability predicate。
- 项目文件共享或 project affinity。
