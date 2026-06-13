from __future__ import annotations

SCOPED_ID_PREFIXES = {
    "fact": "f",
    "intent": "i",
    "hint": "h",
}


def project_id_from_counter(value: int) -> str:
    return f"proj_{value:03d}"


def scoped_id_from_counter(prefix: str, value: int) -> str:
    return f"{prefix}{value:03d}"
