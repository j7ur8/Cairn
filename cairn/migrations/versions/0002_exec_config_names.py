from __future__ import annotations

from alembic import op

revision = "0002_exec_config_names"
down_revision = "0001_initial_postgresql"
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


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        """
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = %s
        """,
        (index_name,),
    ).first()
    return row is not None


def upgrade() -> None:
    if _table_exists("worker_execution_configs"):
        op.drop_table("worker_execution_configs")

    if _table_exists("project_execution_configs"):
        has_old = _column_exists("project_execution_configs", "capabilities_sha256")
        has_new = _column_exists("project_execution_configs", "resources_sha256")
        if has_old and not has_new:
            op.alter_column(
                "project_execution_configs",
                "capabilities_sha256",
                new_column_name="resources_sha256",
            )
        elif has_old and has_new:
            op.drop_column("project_execution_configs", "capabilities_sha256")

        if not _index_exists("idx_project_execution_configs_project"):
            op.create_index(
                "idx_project_execution_configs_project",
                "project_execution_configs",
                ["project_id"],
            )


def downgrade() -> None:
    if _index_exists("idx_project_execution_configs_project"):
        op.drop_index("idx_project_execution_configs_project", table_name="project_execution_configs")
    if _table_exists("project_execution_configs") and _column_exists("project_execution_configs", "resources_sha256"):
        op.alter_column(
            "project_execution_configs",
            "resources_sha256",
            new_column_name="capabilities_sha256",
        )
