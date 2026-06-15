"""Shared test bootstrap."""
from __future__ import annotations

from pathlib import Path

from cairn.server import runtime_config

runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.test.yaml"
runtime_config.reset_runtime_config_cache()
