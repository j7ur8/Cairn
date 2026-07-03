from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SettingRow(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    intent_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    reason_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")


class CounterRow(Base):
    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    graph_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    timeline_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    llm_hidden_event_kinds: Mapped[str] = mapped_column(Text, nullable=False, default='["usage"]', server_default='["usage"]')
    reason_worker: Mapped[str | None] = mapped_column(Text)
    reason_run_id: Mapped[str | None] = mapped_column(Text)
    reason_trigger: Mapped[str | None] = mapped_column(Text)
    reason_started_at: Mapped[str | None] = mapped_column(Text)
    reason_last_heartbeat_at: Mapped[str | None] = mapped_column(Text)


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("idx_facts_project", "project_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)


class IntentRow(Base):
    __tablename__ = "intents"
    __table_args__ = (
        Index("idx_intents_project_open_worker", "project_id", "concluded_at", "worker"),
        Index("idx_intents_project_to_fact", "project_id", "to_fact_id"),
        Index(
            "idx_intents_project_goal_once",
            "project_id",
            unique=True,
            postgresql_where=text("to_fact_id = 'goal'"),
        ),
        Index(
            "idx_intents_project_fact_once",
            "project_id",
            "to_fact_id",
            unique=True,
            postgresql_where=text("to_fact_id IS NOT NULL AND to_fact_id != 'goal'"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    to_fact_id: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    creator: Mapped[str] = mapped_column(Text, nullable=False)
    worker: Mapped[str | None] = mapped_column(Text)
    last_heartbeat_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    concluded_at: Mapped[str | None] = mapped_column(Text)


class IntentSourceRow(Base):
    __tablename__ = "intent_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["intent_id", "project_id"],
            ["intents.id", "intents.project_id"],
            ondelete="CASCADE",
        ),
        Index("idx_intent_sources_project_fact", "project_id", "fact_id"),
    )

    intent_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fact_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class HintRow(Base):
    __tablename__ = "hints"
    __table_args__ = (Index("idx_hints_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    creator: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class ScopedCounterRow(Base):
    __tablename__ = "scoped_counters"

    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ReplayRunRow(Base):
    __tablename__ = "replay_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    replay_project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    completion_description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text)


class ReplayFactMapRow(Base):
    __tablename__ = "replay_fact_map"

    run_id: Mapped[str] = mapped_column(Text, ForeignKey("replay_runs.id", ondelete="CASCADE"), primary_key=True)
    source_fact_id: Mapped[str] = mapped_column(Text, primary_key=True)
    replay_fact_id: Mapped[str] = mapped_column(Text, nullable=False)


class ReplayStepRow(Base):
    __tablename__ = "replay_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "source_intent_id", name="uq_replay_steps_run_source_intent"),
        Index("idx_replay_steps_run_status", "run_id", "status"),
    )

    run_id: Mapped[str] = mapped_column(Text, ForeignKey("replay_runs.id", ondelete="CASCADE"), primary_key=True)
    step_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_intent_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_to_fact_id: Mapped[str] = mapped_column(Text, nullable=False)
    replay_intent_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    created_at: Mapped[str | None] = mapped_column(Text)
    concluded_at: Mapped[str | None] = mapped_column(Text)


class ProjectProxyEndpointRow(Base):
    __tablename__ = "project_proxy_endpoints"
    __table_args__ = (
        CheckConstraint("protocol IN ('socks5','socks5h','http','https')", name="ck_project_proxy_protocol"),
        CheckConstraint("auth_type IN ('none','password')", name="ck_project_proxy_auth_type"),
        CheckConstraint("lifecycle IN ('persistent','run','task')", name="ck_project_proxy_lifecycle"),
        Index("idx_project_proxy_endpoints_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    auth_type: Mapped[str] = mapped_column(Text, nullable=False, default="none", server_default="none")
    username: Mapped[str | None] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    lifecycle: Mapped[str] = mapped_column(Text, nullable=False, default="persistent", server_default="persistent")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    prerequisite_proxy_id: Mapped[str | None] = mapped_column(Text)
    reachable_from: Mapped[str] = mapped_column(Text, nullable=False, default="worker", server_default="worker")
    usage_mode: Mapped[str] = mapped_column(Text, nullable=False, default="tool_native_proxy", server_default="tool_native_proxy")
    health_status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown", server_default="unknown")
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_at: Mapped[str | None] = mapped_column(Text)
    last_test_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    last_used_at: Mapped[str | None] = mapped_column(Text)
    last_usage_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_usage_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    run_id: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectReasonStateRow(Base):
    __tablename__ = "project_reason_state"
    __table_args__ = (Index("idx_project_reason_state_retry", "next_retry_at"),)

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    trigger_hash: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    open_intent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    outcome: Mapped[str] = mapped_column(Text, nullable=False, default="initial", server_default="initial")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    next_retry_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectExecutionConfigRow(Base):
    __tablename__ = "project_execution_configs"
    __table_args__ = (Index("idx_project_execution_configs_project", "project_id"),)

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    role_id: Mapped[str | None] = mapped_column(Text)
    role_json: Mapped[str | None] = mapped_column(Text)
    container_json: Mapped[str | None] = mapped_column(Text)
    workers_json: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[str | None] = mapped_column(Text)
    catalog_json: Mapped[str | None] = mapped_column(Text)
    dispatch_sha256: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    resources_sha256: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    prompts_json: Mapped[str | None] = mapped_column(Text)
    prompts_sha256: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectExecutionTaskTimeoutRow(Base):
    __tablename__ = "project_execution_task_timeouts"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    task_type: Mapped[str] = mapped_column(Text, primary_key=True)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False)
    conclude_timeout: Mapped[int | None] = mapped_column(Integer)


class ProjectExecutionAiProfileRow(Base):
    __tablename__ = "project_execution_ai_profiles"
    __table_args__ = (Index("idx_project_execution_ai_profiles_project_task", "project_id", "task_type"),)

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    task_type: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_name: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_worker_type: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_provider: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    snapshot_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    snapshot_model: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_reasoning_type: Mapped[str | None] = mapped_column(Text)
    snapshot_api_key_env: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    snapshot_api_key_value: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class ProjectExecutionCapabilityRow(Base):
    __tablename__ = "project_execution_capabilities"
    __table_args__ = (Index("idx_project_execution_capabilities_project_task", "project_id", "task_type"),)

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    task_type: Mapped[str] = mapped_column(Text, primary_key=True)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)


class HealthCheckResultRow(Base):
    __tablename__ = "health_check_results"
    __table_args__ = (
        Index("idx_health_check_results_profile_checked", "profile_id", "checked_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[str] = mapped_column(Text, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(Text, nullable=False, default="manual", server_default="manual")


class AiProfileCheckRequestRow(Base):
    __tablename__ = "ai_profile_check_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_ai_profile_check_requests_status"),
        Index("idx_ai_profile_check_requests_status_requested", "status", "requested_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    profile_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_superuser: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class LlmExecutionRow(Base):
    __tablename__ = "llm_executions"
    __table_args__ = (
        Index("idx_llm_executions_project_started", "project_id", "started_at"),
        # Supports the retention sweep, which filters on started_at alone
        # (no project_id) and therefore cannot use the composite index above.
        Index("idx_llm_executions_started", "started_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    intent_id: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    worker: Mapped[str] = mapped_column(Text, nullable=False)
    process_state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(Text)
    last_event_at: Mapped[str | None] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bytes_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    returncode: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_kind: Mapped[str | None] = mapped_column(Text)
    produced_fact_id: Mapped[str | None] = mapped_column(Text)
    created_intent_ids: Mapped[str | None] = mapped_column(Text)


class LlmExecutionEventRow(Base):
    __tablename__ = "llm_execution_events"
    __table_args__ = (
        Index("idx_llm_execution_events_project_sequence", "project_id", "sequence"),
        Index("idx_llm_execution_events_execution_sequence", "execution_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    intent_id: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    worker: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    event_kind: Mapped[str] = mapped_column(Text, nullable=False)
    stream: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    truncated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    redacted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
