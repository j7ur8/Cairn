from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_drop_intent_metadata"
down_revision = "0008_intent_branch_metadata"
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
    for column_name in (
        "expected_value",
        "branch_depth",
        "branch_key",
        "score_reason",
        "tags",
        "intent_kind",
        "priority_score",
    ):
        if _column_exists("intents", column_name):
            op.drop_column("intents", column_name)


def downgrade() -> None:
    if not _column_exists("intents", "priority_score"):
        op.add_column("intents", sa.Column("priority_score", sa.Float(), nullable=True))
    if not _column_exists("intents", "intent_kind"):
        op.add_column("intents", sa.Column("intent_kind", sa.Text(), nullable=True))
    if not _column_exists("intents", "tags"):
        op.add_column("intents", sa.Column("tags", sa.Text(), nullable=False, server_default="[]"))
    if not _column_exists("intents", "score_reason"):
        op.add_column("intents", sa.Column("score_reason", sa.Text(), nullable=True))
    if not _column_exists("intents", "branch_key"):
        op.add_column("intents", sa.Column("branch_key", sa.Text(), nullable=True))
    if not _column_exists("intents", "branch_depth"):
        op.add_column("intents", sa.Column("branch_depth", sa.Integer(), nullable=False, server_default="0"))
    if not _column_exists("intents", "expected_value"):
        op.add_column("intents", sa.Column("expected_value", sa.Float(), nullable=True))
