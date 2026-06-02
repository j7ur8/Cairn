# Example Recon Skill

这是一个最小可工作的 skill 模板，演示如何在 `dispatch.yaml` 的 `capabilities.skills`
里引用本目录。

## 目录结构

```text
capabilities/skills/example-recon/
└── SKILL.md
```

Dispatcher 启动任务时会把整个目录同步到 worker 容器
`/tmp/cairn-capabilities/{project_id}/{task_instance_id}/skills/example-recon/`。

## 怎么用

1. 复制本目录：

   ```bash
   cp -R capabilities/skills/example-recon capabilities/skills/<your-skill-id>
   ```

2. 在 `dispatch.yaml` 中声明：

   ```yaml
   capabilities:
     skills:
       - id: "<your-skill-id>"
         name: "<display name>"
         source_path: "./capabilities/skills/<your-skill-id>"
         task_types: ["bootstrap", "explore", "reason"]
   ```

3. 在 Cairn UI 的 `Caps` 侧栏中为对应项目勾选启用。

## 建议内容

- `SKILL.md`：人类和 Agent 都能阅读的说明，至少包含目标、使用场景、典型调用方式。
- `examples/`：可选，给 Agent 一些参考调用或模板。
- 任何可执行脚本、字典、payload 等。
- 避免在 skill 中放敏感凭据；凭据仍由 worker env 注入。
