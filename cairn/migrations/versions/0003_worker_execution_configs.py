from __future__ import annotations

from alembic import op


revision = "0003_worker_execution_configs"
down_revision = "0002_intent_partial_uniques"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_execution_configs (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_type TEXT NOT NULL,
            config_json TEXT NOT NULL,
            dispatch_sha256 TEXT NOT NULL DEFAULT '',
            capabilities_sha256 TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, task_type)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_worker_execution_configs_project_task
        ON worker_execution_configs (project_id, task_type)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_worker_execution_configs_project_task")
    op.execute("DROP TABLE IF EXISTS worker_execution_configs")
