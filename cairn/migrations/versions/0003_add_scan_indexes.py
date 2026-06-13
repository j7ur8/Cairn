from __future__ import annotations

from alembic import op

revision = "0003_add_scan_indexes"
down_revision = "0002_exec_config_names"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    # facts is keyed (id, project_id); with id leading, a project-scoped lookup
    # (WHERE project_id = ...) cannot use the primary key and otherwise scans
    # the table. This index backs the project facts reads (export/listing).
    if _table_exists("facts") and not _index_exists("idx_facts_project"):
        op.create_index("idx_facts_project", "facts", ["project_id"])

    # The observability retention sweep deletes by started_at alone, which the
    # existing (project_id, started_at) composite index cannot serve.
    if _table_exists("llm_executions") and not _index_exists("idx_llm_executions_started"):
        op.create_index("idx_llm_executions_started", "llm_executions", ["started_at"])


def downgrade() -> None:
    if _index_exists("idx_llm_executions_started"):
        op.drop_index("idx_llm_executions_started", table_name="llm_executions")
    if _index_exists("idx_facts_project"):
        op.drop_index("idx_facts_project", table_name="facts")
