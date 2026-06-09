from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_intent_partial_uniques"
down_revision = "0001_initial_postgresql"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "intent_sources",
        "position",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "ai_profile_check_requests",
        "error_message",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_project_goal_once
        ON intents (project_id)
        WHERE to_fact_id = 'goal'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_project_fact_once
        ON intents (project_id, to_fact_id)
        WHERE to_fact_id IS NOT NULL AND to_fact_id != 'goal'
        """
    )


def downgrade() -> None:
    op.drop_index("idx_intents_project_fact_once", table_name="intents")
    op.drop_index("idx_intents_project_goal_once", table_name="intents")
    op.alter_column(
        "ai_profile_check_requests",
        "error_message",
        existing_type=sa.Text(),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "intent_sources",
        "position",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=None,
    )
