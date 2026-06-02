# capabilities

本目录用于集中存放 Cairn 项目的本地 MCP server 和 skill 资源。
`dispatch.yaml` 的 `capabilities:` 节只引用这里的路径，不直接放二进制或大文件到 yaml。

## 目录约定

| 子目录 | 用途 |
| --- | --- |
| `capabilities/mcp/` | 放本地 MCP server 相关资料：上游仓库说明、构建脚本、容器配置、`mcp.json` 模板等。当前 stdio 模式不强制要求文件，但这里可以集中管理 |
| `capabilities/skills/<skill_id>/` | 放 skill 文件包，Dispatcher 会把整个目录复制到项目容器内 `/tmp/cairn-capabilities/{project_id}/{task_instance_id}/skills/<skill_id>/` |
| `capabilities/roles/<role_id>/ROLE.md` | 放项目 primary role 的固定 prompt。角色不会作为黑板 Fact 写入，而是在任务 prompt 渲染时作为控制面上下文注入 |

skill 目录里**没有强制命名**的文件，但建议至少有一份说明文档（如 `SKILL.md`），便于人和 Agent 都能快速理解该 skill 的用途与使用方式。

## 引用方式

`dispatch.yaml` 中：

```yaml
capabilities:
  mcp_servers:
    - id: "example-mcp"
      name: "Example MCP"
      command: "/usr/local/bin/example-mcp-server"
      args: ["--stdio"]
      env: {}
      task_types: ["bootstrap", "explore"]

  skills:
    - id: "example-recon"
      name: "Example Recon Skill"
      description: "Skill bundled under capabilities/skills/example-recon."
      source_path: "./capabilities/skills/example-recon"
      task_types: ["bootstrap", "explore", "reason"]

roles:
  - id: "cypher-ctf-operator"
    name: "Cypher CTF Operator"
    description: "Primary role prompt for CTF / cyber-range projects."
    source_path: "./capabilities/roles/cypher-ctf-operator/ROLE.md"
    task_types: ["bootstrap", "explore", "reason"]
```

相对路径 `./capabilities/skills/...` 相对于 `dispatch.yaml` 所在目录解析，详见 `cairn/src/cairn/dispatcher/config.py` 的 `prepare_capability_data()`。
角色 `source_path` 同样相对于 `dispatch.yaml` 所在目录解析。

## 范围

- 这里的资源只作为 skill 文件包或 MCP 启动资料；`dispatch.yaml` 仍然是 catalog 的真相源。
- Role 属于项目控制面配置：创建项目时保存 role prompt 快照，运行时注入 `bootstrap` / `explore` / `reason` prompt，不改变 Fact / Intent / Hint 的黑板语义。
- 敏感信息（API key、token、SSH 密码）继续写在 `dispatch.yaml` 之外的环境变量或 secrets 后端，yaml 里用 `{{PLACEHOLDER}}` 占位。
- 多 Dispatcher 部署时各 `dispatch.yaml` 的 `capabilities` 与 `roles` 必须保持一致，否则会被后启动的 Dispatcher 全量覆盖。
