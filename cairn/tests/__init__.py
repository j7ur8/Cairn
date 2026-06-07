"""Shared test bootstrap."""
from __future__ import annotations

import os
import sys

_DEFAULT_TEST_SECRET = "test-jwt-secret-do-not-use-in-prod-32bytes"

os.environ.setdefault("CAIRN_JWT_SECRET", _DEFAULT_TEST_SECRET)
os.environ.setdefault("CAIRN_SECRETS_KEY", _DEFAULT_TEST_SECRET)

# Print to stderr so we can see when this runs.
print(f"tests/__init__.py loaded; CAIRN_JWT_SECRET={'set' if os.environ.get('CAIRN_JWT_SECRET') else 'unset'}", file=sys.stderr)
