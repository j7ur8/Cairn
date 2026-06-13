from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml
from fastapi import HTTPException


@dataclass(slots=True)
class ConfigStore:
    dispatch_path: Path
    resources_path: Path

    def load_dispatch(self) -> dict[str, Any]:
        return self._read_yaml(self.dispatch_path)

    def load_resources(self) -> dict[str, Any]:
        return self._read_yaml(self.resources_path)

    def save_dispatch(self, data: dict[str, Any]) -> None:
        self._write_yaml(self.dispatch_path, data)

    def save_resources(self, data: dict[str, Any]) -> None:
        self._write_yaml(self.resources_path, data)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise HTTPException(500, f"config file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise HTTPException(500, f"config file must contain a mapping: {path}")
        return data

    @staticmethod
    def _write_yaml(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            tmp_path.replace(path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            if exc.errno != errno.EBUSY:
                raise
            # Docker single-file bind mounts cannot be atomically replaced.
            ConfigStore._overwrite_text(path, text)

    @staticmethod
    def _overwrite_text(path: Path, text: str) -> None:
        with path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
