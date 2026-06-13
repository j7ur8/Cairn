from __future__ import annotations

from pydantic import BaseModel


class ReasonState(BaseModel):
    project_id: str
    trigger: str
    trigger_hash: str
    fact_count: int
    hint_count: int
    open_intent_count: int
    outcome: str
    failure_count: int
    last_error: str
    next_retry_at: str | None = None
    updated_at: str
