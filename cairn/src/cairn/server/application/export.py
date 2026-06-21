from __future__ import annotations

from datetime import datetime
from typing import Any

import yaml

from cairn.server.repositories.export import ProjectExportQuery


def format_export_timestamp(value: str | None) -> str | None:
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def export_project_yaml(conn: Any, project_id: str) -> str:
    data = ProjectExportQuery(conn).load_project_data(project_id)
    facts = data.facts
    hints = data.hints
    intents = data.intents
    sources_by_intent = data.sources_by_intent

    origin_desc = ""
    goal_desc = ""
    for fact in facts:
        if fact["id"] == "origin":
            origin_desc = fact["description"]
        elif fact["id"] == "goal":
            goal_desc = fact["description"]

    payload: dict = {
        "project": {
            "title": data.project["title"],
            "origin": origin_desc,
            "goal": goal_desc,
        }
    }

    if hints:
        payload["hints"] = [
            {
                "content": hint["content"],
                "creator": hint["creator"],
                "created_at": format_export_timestamp(hint["created_at"]),
            }
            for hint in hints
        ]

    payload["facts"] = [{"id": fact["id"], "description": fact["description"]} for fact in facts]

    intent_list = []
    for intent in intents:
        intent_list.append(
            {
                "from": sources_by_intent.get(intent["id"], []),
                "to": intent["to_fact_id"],
                "description": intent["description"],
                "creator": intent["creator"],
                "worker": intent["worker"],
                "created_at": format_export_timestamp(intent["created_at"]),
                "concluded_at": format_export_timestamp(intent["concluded_at"]),
                "priority_score": intent["priority_score"],
                "intent_kind": intent["intent_kind"],
                "tags": intent["tags"],
                "score_reason": intent["score_reason"],
            }
        )

    if intent_list:
        payload["intents"] = intent_list

    return yaml.dump(payload, allow_unicode=True, default_flow_style=False, sort_keys=False)


def export_project_timeline(conn: Any, project_id: str) -> str:
    data = ProjectExportQuery(conn).load_project_data(project_id)
    facts = data.facts
    hints = data.hints
    intents = data.intents
    sources_by_intent = data.sources_by_intent

    facts_by_id = {fact["id"]: fact["description"] for fact in facts}

    events: list[tuple[str, int, str]] = []
    order = 0

    origin_desc = facts_by_id.get("origin", "")
    goal_desc = facts_by_id.get("goal", "")
    ts = format_export_timestamp(data.project["created_at"]) or ""
    block = f"[{ts}] PROJECT CREATED\n  origin: {origin_desc}\n  goal: {goal_desc}"
    events.append((data.project["created_at"] or "", order, block))
    order += 1

    for hint in hints:
        ts = format_export_timestamp(hint["created_at"]) or ""
        block = f"[{ts}] HINT by {hint['creator']}\n  {hint['content']}"
        events.append((hint["created_at"] or "", order, block))
        order += 1

    for intent in intents:
        source_ids = sources_by_intent.get(intent["id"], [])
        from_str = ", ".join(source_ids)

        ts = format_export_timestamp(intent["created_at"]) or ""
        meta = f"  from: {from_str}"
        if intent["worker"] and not intent["concluded_at"]:
            meta += f"\n  worker: {intent['worker']} (in progress)"
        block = f"[{ts}] INTENT DECLARED {intent['id']} by {intent['creator']}\n{meta}\n  {intent['description']}"
        events.append((intent["created_at"] or "", order, block))
        order += 1

        if not intent["concluded_at"] or not intent["to_fact_id"]:
            continue

        ts = format_export_timestamp(intent["concluded_at"]) or ""
        actor = intent["worker"] or intent["creator"]

        if intent["to_fact_id"] == "goal":
            block = f"[{ts}] PROJECT COMPLETED by {actor}\n  via: {intent['id']} from {from_str}"
        else:
            fact_desc = facts_by_id.get(intent["to_fact_id"], "")
            block = (
                f"[{ts}] INTENT CONCLUDED {intent['id']} by {actor}\n"
                f"  from: {from_str}\n"
                f"  produced: {intent['to_fact_id']}\n"
                f"  {fact_desc}"
            )

        events.append((intent["concluded_at"] or "", order, block))
        order += 1

    events.sort(key=lambda item: (item[0], item[1]))
    return "\n\n".join(item[2] for item in events) + "\n"


def export_project_text(conn: Any, project_id: str, format: str) -> str:
    if format == "timeline":
        return export_project_timeline(conn, project_id)
    return export_project_yaml(conn, project_id)
