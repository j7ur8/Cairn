from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_project_proxy_servers"
down_revision = "0011_intent_phase_checkpoints"
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


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = %s
        """,
        (table_name,),
    ).first()
    return row is not None


def upgrade() -> None:
    if _column_exists("projects", "tool_proxy_id"):
        op.drop_column("projects", "tool_proxy_id")
    if _column_exists("project_execution_configs", "tool_proxy_id"):
        op.drop_column("project_execution_configs", "tool_proxy_id")
    if _column_exists("project_execution_configs", "proxies_json"):
        op.drop_column("project_execution_configs", "proxies_json")
    if _table_exists("proxies"):
        op.drop_table("proxies")
    op.create_table(
        "project_proxy_endpoints",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("auth_type", sa.Text(), server_default="none", nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), server_default="", nullable=False),
        sa.Column("lifecycle", sa.Text(), server_default="persistent", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("scope", sa.Text(), server_default="", nullable=False),
        sa.Column("prerequisite_proxy_id", sa.Text(), nullable=True),
        sa.Column("reachable_from", sa.Text(), server_default="worker", nullable=False),
        sa.Column("usage_mode", sa.Text(), server_default="tool_native_proxy", nullable=False),
        sa.Column("health_status", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_at", sa.Text(), nullable=True),
        sa.Column("last_test_message", sa.Text(), server_default="", nullable=False),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.Column("last_usage_ok", sa.Boolean(), nullable=True),
        sa.Column("last_usage_message", sa.Text(), server_default="", nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("protocol IN ('socks5','socks5h','http','https')", name="ck_project_proxy_protocol"),
        sa.CheckConstraint("auth_type IN ('none','password')", name="ck_project_proxy_auth_type"),
        sa.CheckConstraint("lifecycle IN ('persistent','run','task')", name="ck_project_proxy_lifecycle"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "project_id"),
    )
    op.create_index("idx_project_proxy_endpoints_project", "project_proxy_endpoints", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_project_proxy_endpoints_project", table_name="project_proxy_endpoints")
    op.drop_table("project_proxy_endpoints")
