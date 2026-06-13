from __future__ import annotations

from pydantic import BaseModel

from cairn.server.models_pkg.projects import Fact, Intent, ProjectMeta


class ReopenResponse(BaseModel):
    project: ProjectMeta
    fact: Fact
    intent: Intent
