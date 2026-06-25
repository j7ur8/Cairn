# Task

Use project-relative paths for generated artifacts whenever possible. The current project root is the worker workspace root, so write outputs to relative directories like `reports/` and `exploit/`, not to a nested `project/` directory.

- `reports/` stores final reports and stage summaries.
- Write long outputs to files and reference the paths instead of inlining everything.
