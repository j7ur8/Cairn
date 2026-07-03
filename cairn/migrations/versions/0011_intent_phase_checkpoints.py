from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_intent_phase_checkpoints"
down_revision = "0010_project_runtime_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intent_phase_checkpoints",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("intent_id", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("worker_name", sa.Text(), nullable=False),
        sa.Column("worker_type", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("phase IN ('explore_conclude')", name="ck_intent_phase_checkpoints_phase"),
        sa.ForeignKeyConstraint(["intent_id", "project_id"], ["intents.id", "intents.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "intent_id", "phase"),
    )


def downgrade() -> None:
    op.drop_table("intent_phase_checkpoints")
