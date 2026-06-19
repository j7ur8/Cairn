"""Compatibility re-export for the former server DTO package.

New code should import server-only request/response DTOs from
``cairn.server.schemas``. This package remains during the migration window so
older imports continue to work.
"""

from cairn.server.schemas import *  # noqa: F403
