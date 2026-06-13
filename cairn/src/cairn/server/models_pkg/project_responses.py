from __future__ import annotations

from pydantic import BaseModel

from cairn.shared.contracts import Fact, Intent, ProjectMeta


class ReopenResponse(BaseModel):
    project: ProjectMeta
    fact: Fact
    intent: Intent
