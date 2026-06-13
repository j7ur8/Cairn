from __future__ import annotations

from cairn.dispatcher.prompting import format_hints
from cairn.shared.contracts import ProjectDetail


def bootstrap_prompt_replacements(project: ProjectDetail) -> dict[str, str]:
    facts = {fact.id: fact.description for fact in project.facts}
    hints = [
        {
            "id": hint.id,
            "content": hint.content,
            "creator": hint.creator,
            "created_at": hint.created_at,
        }
        for hint in project.hints
    ]
    return {
        "origin": facts.get("origin", ""),
        "goal": facts.get("goal", ""),
        "hints": format_hints(hints),
    }
