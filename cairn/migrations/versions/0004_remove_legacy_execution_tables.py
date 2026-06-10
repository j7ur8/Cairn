from __future__ import annotations

from alembic import op


revision = "0004_remove_legacy_tables"
down_revision = "0003_worker_execution_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "project_ai_profiles",
        "ai_profile_models",
        "ai_profiles",
        "project_capability_snapshots",
        "project_capabilities",
        "project_roles",
        "role_catalog",
        "capability_catalog",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported after removing legacy execution tables")
