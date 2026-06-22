from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_intent_branch_metadata"
down_revision = "0007_intent_priority_metadata"
branch_labels = None
depends_on = None


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
    if not _column_exists("intents", "branch_key"):
        op.add_column("intents", sa.Column("branch_key", sa.Text(), nullable=True))
    if not _column_exists("intents", "branch_depth"):
        op.add_column("intents", sa.Column("branch_depth", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("intents", "expected_value"):
        op.add_column("intents", sa.Column("expected_value", sa.Float(), nullable=True))


def downgrade() -> None:
    for column_name in ("expected_value", "branch_depth", "branch_key"):
        if _column_exists("intents", column_name):
            op.drop_column("intents", column_name)
