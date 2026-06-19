from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_project_poll_revisions"
down_revision = "0004_prompt_snapshots"
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
    if not _table_exists("projects"):
        return
    if not _column_exists("projects", "graph_revision"):
        op.add_column(
            "projects",
            sa.Column("graph_revision", sa.BigInteger(), nullable=False, server_default="0"),
        )
    if not _column_exists("projects", "timeline_revision"):
        op.add_column(
            "projects",
            sa.Column("timeline_revision", sa.BigInteger(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if not _table_exists("projects"):
        return
    if _column_exists("projects", "timeline_revision"):
        op.drop_column("projects", "timeline_revision")
    if _column_exists("projects", "graph_revision"):
        op.drop_column("projects", "graph_revision")
