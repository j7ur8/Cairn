from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_postgresql"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_profile_check_requests",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_ai_profile_check_requests_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ai_profile_check_requests_status_requested", "ai_profile_check_requests", ["status", "requested_at"])
    op.create_table(
        "counters",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "health_check_results",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.Text(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("check_type", sa.Text(), server_default="manual", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_health_check_results_profile_checked", "health_check_results", ["profile_id", "checked_at"])
    op.create_table(
        "llm_execution_events",
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("intent_id", sa.Text(), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("worker", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column("stream", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("redacted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("sequence"),
    )
    op.create_index("idx_llm_execution_events_execution_sequence", "llm_execution_events", ["execution_id", "sequence"])
    op.create_index("idx_llm_execution_events_project_sequence", "llm_execution_events", ["project_id", "sequence"])
    op.create_table(
        "llm_executions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("intent_id", sa.Text(), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("worker", sa.Text(), nullable=False),
        sa.Column("process_state", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("last_event_at", sa.Text(), nullable=True),
        sa.Column("event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bytes_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("returncode", sa.Integer(), nullable=True),
        sa.Column("timed_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column("produced_fact_id", sa.Text(), nullable=True),
        sa.Column("created_intent_ids", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_llm_executions_started", "llm_executions", ["started_at"])
    op.create_index("idx_llm_executions_project_started", "llm_executions", ["project_id", "started_at"])
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("graph_revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("timeline_revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("proxy_id", sa.Text(), nullable=True),
        sa.Column("llm_hidden_event_kinds", sa.Text(), server_default='["usage"]', nullable=False),
        sa.Column("reason_worker", sa.Text(), nullable=True),
        sa.Column("reason_run_id", sa.Text(), nullable=True),
        sa.Column("reason_trigger", sa.Text(), nullable=True),
        sa.Column("reason_started_at", sa.Text(), nullable=True),
        sa.Column("reason_last_heartbeat_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "proxies",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("type IN ('socks5','http','https')", name="ck_proxies_type"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("intent_timeout", sa.Integer(), server_default="15", nullable=False),
        sa.Column("reason_timeout", sa.Integer(), server_default="15", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_superuser", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "facts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "project_id"),
    )
    op.create_index("idx_facts_project", "facts", ["project_id"])
    op.create_table(
        "hints",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("creator", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "project_id"),
    )
    op.create_index("idx_hints_project_id", "hints", ["project_id"])
    op.create_table(
        "intents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("to_fact_id", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("creator", sa.Text(), nullable=False),
        sa.Column("worker", sa.Text(), nullable=True),
        sa.Column("last_heartbeat_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("concluded_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "project_id"),
    )
    op.create_index("idx_intents_project_to_fact", "intents", ["project_id", "to_fact_id"])
    op.create_index("idx_intents_project_open_worker", "intents", ["project_id", "concluded_at", "worker"])
    op.create_index("idx_intents_project_goal_once", "intents", ["project_id"], unique=True, postgresql_where=sa.text("to_fact_id = 'goal'"))
    op.create_index(
        "idx_intents_project_fact_once",
        "intents",
        ["project_id", "to_fact_id"],
        unique=True,
        postgresql_where=sa.text("to_fact_id IS NOT NULL AND to_fact_id != 'goal'"),
    )
    op.create_table(
        "project_execution_ai_profiles",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("snapshot_name", sa.Text(), nullable=False),
        sa.Column("snapshot_worker_type", sa.Text(), nullable=False),
        sa.Column("snapshot_provider", sa.Text(), server_default="", nullable=False),
        sa.Column("snapshot_base_url", sa.Text(), server_default="", nullable=False),
        sa.Column("snapshot_model", sa.Text(), nullable=False),
        sa.Column("snapshot_reasoning_type", sa.Text(), nullable=True),
        sa.Column("snapshot_api_key_env", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "task_type", "role", "position"),
    )
    op.create_index(
        "idx_project_execution_ai_profiles_project_task",
        "project_execution_ai_profiles",
        ["project_id", "task_type"],
    )
    op.create_table(
        "project_execution_capabilities",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "task_type"),
    )
    op.create_index(
        "idx_project_execution_capabilities_project_task",
        "project_execution_capabilities",
        ["project_id", "task_type"],
    )
    op.create_table(
        "project_execution_configs",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("role_id", sa.Text(), nullable=True),
        sa.Column("role_json", sa.Text(), nullable=True),
        sa.Column("proxy_id", sa.Text(), nullable=True),
        sa.Column("dispatch_sha256", sa.Text(), server_default="", nullable=False),
        sa.Column("resources_sha256", sa.Text(), server_default="", nullable=False),
        sa.Column("prompts_json", sa.Text(), nullable=True),
        sa.Column("prompts_sha256", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index("idx_project_execution_configs_project", "project_execution_configs", ["project_id"])
    op.create_table(
        "project_execution_task_timeouts",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("conclude_timeout", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "task_type"),
    )
    op.create_table(
        "project_reason_state",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), server_default="", nullable=False),
        sa.Column("trigger_hash", sa.Text(), server_default="", nullable=False),
        sa.Column("fact_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hint_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_intent_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("outcome", sa.Text(), server_default="initial", nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column("next_retry_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index("idx_project_reason_state_retry", "project_reason_state", ["next_retry_at"])
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_project_id", sa.Text(), nullable=False),
        sa.Column("replay_project_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("completion_description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["replay_project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("replay_project_id"),
    )
    op.create_table(
        "scoped_counters",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "kind"),
    )
    op.create_table(
        "intent_sources",
        sa.Column("intent_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("fact_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["intent_id", "project_id"], ["intents.id", "intents.project_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("intent_id", "project_id", "fact_id"),
    )
    op.create_index("idx_intent_sources_project_fact", "intent_sources", ["project_id", "fact_id"])
    op.create_table(
        "replay_fact_map",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("source_fact_id", sa.Text(), nullable=False),
        sa.Column("replay_fact_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["replay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "source_fact_id"),
    )
    op.create_table(
        "replay_steps",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("source_intent_id", sa.Text(), nullable=False),
        sa.Column("source_to_fact_id", sa.Text(), nullable=False),
        sa.Column("replay_intent_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("concluded_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["replay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "step_index"),
        sa.UniqueConstraint("run_id", "source_intent_id", name="uq_replay_steps_run_source_intent"),
    )
    op.create_index("idx_replay_steps_run_status", "replay_steps", ["run_id", "status"])


def downgrade() -> None:
    for index_name, table_name in (
        ("idx_replay_steps_run_status", "replay_steps"),
        ("idx_intent_sources_project_fact", "intent_sources"),
        ("idx_project_reason_state_retry", "project_reason_state"),
        ("idx_project_execution_configs_project", "project_execution_configs"),
        ("idx_project_execution_capabilities_project_task", "project_execution_capabilities"),
        ("idx_project_execution_ai_profiles_project_task", "project_execution_ai_profiles"),
        ("idx_intents_project_fact_once", "intents"),
        ("idx_intents_project_goal_once", "intents"),
        ("idx_intents_project_open_worker", "intents"),
        ("idx_intents_project_to_fact", "intents"),
        ("idx_hints_project_id", "hints"),
        ("idx_facts_project", "facts"),
        ("idx_llm_executions_project_started", "llm_executions"),
        ("idx_llm_executions_started", "llm_executions"),
        ("idx_llm_execution_events_project_sequence", "llm_execution_events"),
        ("idx_llm_execution_events_execution_sequence", "llm_execution_events"),
        ("idx_health_check_results_profile_checked", "health_check_results"),
        ("idx_ai_profile_check_requests_status_requested", "ai_profile_check_requests"),
    ):
        op.drop_index(index_name, table_name=table_name)
    for table_name in (
        "replay_steps",
        "replay_fact_map",
        "intent_sources",
        "scoped_counters",
        "replay_runs",
        "project_reason_state",
        "project_execution_task_timeouts",
        "project_execution_configs",
        "project_execution_capabilities",
        "project_execution_ai_profiles",
        "intents",
        "hints",
        "facts",
        "users",
        "settings",
        "proxies",
        "projects",
        "llm_executions",
        "llm_execution_events",
        "health_check_results",
        "counters",
        "ai_profile_check_requests",
    ):
        op.drop_table(table_name)
