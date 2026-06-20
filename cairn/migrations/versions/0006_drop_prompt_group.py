from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_drop_prompt_group"
down_revision = "0005_project_poll_revisions"
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
    if _table_exists("project_execution_configs") and _column_exists("project_execution_configs", "prompt_group"):
        op.drop_column("project_execution_configs", "prompt_group")


def downgrade() -> None:
    if _table_exists("project_execution_configs") and not _column_exists("project_execution_configs", "prompt_group"):
        op.add_column(
            "project_execution_configs",
            sa.Column("prompt_group", sa.Text(), nullable=False, server_default=""),
        )
