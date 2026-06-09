from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Generator, Iterable

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cairn.server.orm import Base, CounterRow, SettingRow
DEFAULT_DATABASE_URL_ENV = "CAIRN_DATABASE_URL"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_database_url: str | None = None
_db_path: object | None = object()


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    url = _database_url or os.environ.get(DEFAULT_DATABASE_URL_ENV, "").strip()
    if not url:
        raise DatabaseUnavailable(f"{DEFAULT_DATABASE_URL_ENV} is required")
    if url.startswith("sqlite"):
        raise DatabaseUnavailable("SQLite URLs are not supported; configure PostgreSQL")
    return url


def configure(url: str | os.PathLike[str] | None = None, *, run_migrations: bool = True) -> None:
    global _engine, _SessionLocal, _database_url, _db_path
    legacy_test_path = False
    if url is not None:
        candidate = str(url)
        legacy_test_path = not candidate.startswith(("postgresql://", "postgresql+"))
    if _engine is not None and not legacy_test_path:
        return
    if legacy_test_path:
        _database_url = database_url()
    elif url is not None:
        candidate = str(url)
        _database_url = candidate
    resolved = database_url()
    if _engine is None:
        _engine = create_engine(
            resolved,
            pool_pre_ping=True,
            pool_size=int(os.environ.get("CAIRN_DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("CAIRN_DB_MAX_OVERFLOW", "10")),
            pool_timeout=float(os.environ.get("CAIRN_DB_POOL_TIMEOUT", "30")),
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    if legacy_test_path:
        drop_all_for_tests()
        Base.metadata.create_all(engine())
        seed_defaults()
        _db_path = url
        return
    if run_migrations:
        upgrade_head()
        seed_defaults()
    _db_path = url if legacy_test_path else object()


def reset_for_tests() -> None:
    global _engine, _SessionLocal, _database_url, _db_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _database_url = None
    _db_path = object()


def engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session


def alembic_config() -> Config:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url())
    return cfg


def upgrade_head() -> None:
    command.upgrade(alembic_config(), "head")


def create_all_for_tests() -> None:
    Base.metadata.create_all(engine())
    seed_defaults()


def drop_all_for_tests() -> None:
    with engine().begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def seed_defaults() -> None:
    with session_scope() as session:
        if session.get(SettingRow, 1) is None:
            session.add(SettingRow(id=1, intent_timeout=15, reason_timeout=15))
        if session.get(CounterRow, "project") is None:
            session.add(CounterRow(name="project", value=0))


def postgres_status() -> dict[str, Any]:
    with session_scope() as session:
        session.execute(text("SELECT 1")).scalar_one()
        try:
            revision = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        except SQLAlchemyError:
            revision = None
    return {"database": "postgresql", "ok": True, "alembic_revision": revision}


def close_thread_conn() -> None:
    return None


class RowAdapter(dict[str, Any]):
    def keys(self):  # type: ignore[override]
        return super().keys()


class ResultAdapter:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self) -> RowAdapter | None:
        row = self._result.mappings().fetchone()
        return RowAdapter(row) if row is not None else None

    def fetchall(self) -> list[RowAdapter]:
        return [RowAdapter(row) for row in self._result.mappings().fetchall()]


class SessionSqlAdapter:
    """Temporary SQLAlchemy-backed adapter while routers move to ORM calls."""

    def __init__(self, session: Session):
        self.session = session

    def execute(self, sql: str, params: Iterable[Any] | dict[str, Any] = ()) -> ResultAdapter:
        sql, bound = _translate_sql(sql, params)
        return ResultAdapter(self.session.execute(text(sql), bound))

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


def _translate_sql(sql: str, params: Iterable[Any] | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_sql(sql)
    if isinstance(params, dict):
        return normalized, params
    values = list(params)
    bound = {f"p{i}": value for i, value in enumerate(values)}
    for i in range(len(values)):
        normalized = normalized.replace("?", f":p{i}", 1)
    return normalized, bound


def _normalize_sql(sql: str) -> str:
    normalized = sql.strip()
    normalized = normalized.replace("WHERE rowid = 1", "WHERE id = 1")
    normalized = normalized.replace("ORDER BY rowid", "ORDER BY fact_id")
    normalized = normalized.replace("INSERT OR IGNORE INTO scoped_counters", "INSERT INTO scoped_counters")
    if normalized.startswith("INSERT INTO scoped_counters") and "ON CONFLICT" not in normalized:
        normalized += " ON CONFLICT (project_id, kind) DO NOTHING"
    normalized = normalized.replace("INSERT OR IGNORE INTO counters", "INSERT INTO counters")
    if normalized.startswith("INSERT INTO counters") and "ON CONFLICT" not in normalized:
        normalized += " ON CONFLICT (name) DO NOTHING"
    normalized = re.sub(r"\bTRUE\b", "true", normalized)
    normalized = re.sub(r"\bFALSE\b", "false", normalized)
    return normalized


@contextmanager
def get_conn() -> Generator[SessionSqlAdapter, None, None]:
    with session_scope() as session:
        yield SessionSqlAdapter(session)


@contextmanager
def with_immediate_tx() -> Generator[SessionSqlAdapter, None, None]:
    with get_conn() as conn:
        yield conn
