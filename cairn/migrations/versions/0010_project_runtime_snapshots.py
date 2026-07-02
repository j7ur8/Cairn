from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_project_runtime_snapshots"
down_revision = "0009_drop_intent_metadata"
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
        "container_json",
        "workers_json",
        "proxies_json",
        "settings_json",
        "catalog_json",
    ):
        if not _column_exists("project_execution_configs", column_name):
            op.add_column("project_execution_configs", sa.Column(column_name, sa.Text(), nullable=True))
    if not _column_exists("project_execution_ai_profiles", "snapshot_api_key_value"):
        op.add_column(
            "project_execution_ai_profiles",
            sa.Column("snapshot_api_key_value", sa.Text(), server_default="", nullable=False),
        )


def downgrade() -> None:
    if _column_exists("project_execution_ai_profiles", "snapshot_api_key_value"):
        op.drop_column("project_execution_ai_profiles", "snapshot_api_key_value")
    for column_name in (
        "catalog_json",
        "settings_json",
        "proxies_json",
        "workers_json",
        "container_json",
    ):
        if _column_exists("project_execution_configs", column_name):
            op.drop_column("project_execution_configs", column_name)
