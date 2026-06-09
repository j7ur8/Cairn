from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from cairn.server import db as main_db


def configure(*args: Any, **kwargs: Any) -> None:
    main_db.configure(*args, **kwargs)


def postgres_status() -> dict[str, Any]:
    return main_db.postgres_status()


@contextmanager
def get_conn() -> Generator[main_db.SessionSqlAdapter, None, None]:
    with main_db.get_conn() as conn:
        yield conn


def quick_check() -> list[str]:
    return ["ok"]


def integrity_check() -> list[str]:
    return ["ok"]
