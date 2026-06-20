from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_prompt_snapshots"
down_revision = "0003_add_scan_indexes"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    ).first()
    return row is not None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("project_execution_configs"):
        return
    if not _column_exists("project_execution_configs", "prompts_json"):
        op.add_column(
            "project_execution_configs",
            sa.Column("prompts_json", sa.Text(), nullable=True),
        )
    if not _column_exists("project_execution_configs", "prompts_sha256"):
        op.add_column(
            "project_execution_configs",
            sa.Column("prompts_sha256", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    if not _table_exists("project_execution_configs"):
        return
    if _column_exists("project_execution_configs", "prompts_sha256"):
        op.drop_column("project_execution_configs", "prompts_sha256")
    if _column_exists("project_execution_configs", "prompts_json"):
        op.drop_column("project_execution_configs", "prompts_json")
