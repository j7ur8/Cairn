from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cairn.server.orm import Base, CounterRow, SettingRow

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_database_url: str | None = None
_pool_size: int | None = None
_max_overflow: int | None = None
_pool_timeout: float | None = None


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    if _database_url:
        url = _database_url
    else:
        from cairn.server.runtime_config import system_config
        url = system_config().database.url
    if not url:
        raise DatabaseUnavailable("dispatch.yaml system.database.url is required")
    if url.startswith("sqlite"):
        raise DatabaseUnavailable("SQLite URLs are not supported; configure PostgreSQL")
    return url


def configure(url: str | os.PathLike[str] | None = None, *, run_migrations: bool = True) -> None:
    global _engine, _SessionLocal, _database_url, _pool_size, _max_overflow, _pool_timeout
    if url is not None:
        candidate = str(url)
        if not candidate.startswith(("postgresql://", "postgresql+")):
            raise DatabaseUnavailable("configure() requires a PostgreSQL URL")
        _database_url = candidate
    if _engine is not None:
        return
    resolved = database_url()
    if _engine is None:
        if _pool_size is None or _max_overflow is None or _pool_timeout is None:
            if _database_url:
                _pool_size = 5
                _max_overflow = 10
                _pool_timeout = 30
            else:
                from cairn.server.runtime_config import system_config
                database = system_config().database
                _pool_size = database.pool_size
                _max_overflow = database.max_overflow
                _pool_timeout = database.pool_timeout
        _engine = create_engine(
            resolved,
            pool_pre_ping=True,
            pool_size=_pool_size,
            max_overflow=_max_overflow,
            pool_timeout=_pool_timeout,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    if run_migrations:
        upgrade_head()
        seed_defaults()


def reset_for_tests() -> None:
    global _engine, _SessionLocal, _database_url, _pool_size, _max_overflow, _pool_timeout
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _database_url = None
    _pool_size = None
    _max_overflow = None
    _pool_timeout = None


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
