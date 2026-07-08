# Task

Use the project workspace for generated artifacts. The project workspace root is `/home/kali/workspace`; write outputs to paths like `/home/kali/workspace/reports/` and `/home/kali/workspace/exploit/`, not to the task instruction directory.

- `reports/` stores final reports and stage summaries.
- `exploit/` stores PoCs, payloads, helper scripts, and reproduction artifacts.
- `attachments/` stores input attachments only; do not use it as the destination for runtime outputs.
- Write long logs, large responses, screenshots, raw command output, and step-by-step reproduction notes to files, then reference those paths in model output instead of inlining the content.
