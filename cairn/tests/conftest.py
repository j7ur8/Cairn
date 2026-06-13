from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    cache: dict[Path, bool] = {}
    for item in items:
        path = Path(str(item.fspath))
        needs_db = cache.get(path)
        if needs_db is None:
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                source = ""
            needs_db = "reset_postgres_db(" in source
            cache[path] = needs_db
        if needs_db:
            item.add_marker(pytest.mark.db)
