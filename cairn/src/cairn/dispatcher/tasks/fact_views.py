from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import yaml

from cairn.dispatcher.scheduler.frontier_priority import intent_priority_key
from cairn.shared.contracts import Fact, Intent, ProjectDetail

REASON_VIEW_CHAR_BUDGET = 16_000
WORKER_VIEW_CHAR_BUDGET = 10_000
CONCLUDE_VIEW_CHAR_BUDGET = 8_000

ANCHOR_FACT_IDS = ("origin", "goal")


class FactViewType(StrEnum):
    REASON = "reason"
    WORKER = "worker"
    CONCLUDE = "conclude"


@dataclass(frozen=True, slots=True)
class FactView:
    yaml_text: str
    included_fact_count: int
    omitted_fact_count: int
    full_graph_reference: str


class FactViewRenderer:
    def render_reason_view(
        self,
        project: ProjectDetail,
        *,
        full_graph_reference: str,
    ) -> FactView:
        return self._render(
            project,
            FactViewType.REASON,
            budget=REASON_VIEW_CHAR_BUDGET,
            full_graph_reference=full_graph_reference,
        )

    def render_worker_view(
        self,
        project: ProjectDetail,
        *,
        intent: Intent,
        full_graph_reference: str,
    ) -> FactView:
        return self._render(
            project,
            FactViewType.WORKER,
            budget=WORKER_VIEW_CHAR_BUDGET,
            intent=intent,
            full_graph_reference=full_graph_reference,
        )

    def render_conclude_view(
        self,
        project: ProjectDetail,
        *,
        intent: Intent,
        full_graph_reference: str,
    ) -> FactView:
        return self._render(
            project,
            FactViewType.CONCLUDE,
            budget=CONCLUDE_VIEW_CHAR_BUDGET,
            intent=intent,
            full_graph_reference=full_graph_reference,
        )

    def _render(
        self,
        project: ProjectDetail,
        view_type: FactViewType,
        *,
        budget: int,
        full_graph_reference: str,
        intent: Intent | None = None,
    ) -> FactView:
        facts_by_id = {fact.id: fact for fact in project.facts}
        included_fact_ids = self._initial_fact_ids(project, view_type, intent)
        included_fact_ids = [fact_id for fact_id in included_fact_ids if fact_id in facts_by_id]
        included_fact_ids = _dedupe(included_fact_ids)

        payload = self._payload(
            project,
            view_type,
            included_fact_ids,
            full_graph_reference=full_graph_reference,
            intent=intent,
        )
        yaml_text = _dump_yaml(payload)
        if len(yaml_text) > budget:
            included_fact_ids = self._fit_fact_ids(
                project,
                view_type,
                included_fact_ids,
                budget=budget,
                full_graph_reference=full_graph_reference,
                intent=intent,
            )
            payload = self._payload(
                project,
                view_type,
                included_fact_ids,
                full_graph_reference=full_graph_reference,
                intent=intent,
            )
            yaml_text = _dump_yaml(payload)

        included_count = len(included_fact_ids)
        omitted_count = max(0, len(project.facts) - included_count)
        payload["statistics"]["included_fact_count"] = included_count
        payload["statistics"]["omitted_fact_count"] = omitted_count
        yaml_text = _dump_yaml(payload)
        return FactView(
            yaml_text=yaml_text,
            included_fact_count=included_count,
            omitted_fact_count=omitted_count,
            full_graph_reference=full_graph_reference,
        )

    def _initial_fact_ids(
        self,
        project: ProjectDetail,
        view_type: FactViewType,
        intent: Intent | None,
    ) -> list[str]:
        fact_ids = [fact_id for fact_id in ANCHOR_FACT_IDS if any(fact.id == fact_id for fact in project.facts)]
        if view_type == FactViewType.REASON:
            fact_ids.extend(self._recent_completed_fact_ids(project, limit=24))
            fact_ids.extend(self._completed_chain_fact_ids(project, limit=40))
            return fact_ids
        if intent is None:
            return fact_ids
        fact_ids.extend(intent.from_)
        fact_ids.extend(self._upstream_one_hop_fact_ids(project, intent.from_))
        if view_type == FactViewType.CONCLUDE:
            fact_ids.extend(self._related_fact_ids(project, intent.from_, limit=12))
        return fact_ids

    def _payload(
        self,
        project: ProjectDetail,
        view_type: FactViewType,
        included_fact_ids: list[str],
        *,
        full_graph_reference: str,
        intent: Intent | None,
    ) -> dict[str, Any]:
        facts_by_id = {fact.id: fact for fact in project.facts}
        payload: dict[str, Any] = {
            "view": {
                "type": view_type.value,
                "full_graph_reference": full_graph_reference,
            },
            "project": {
                "id": project.project.id,
                "title": project.project.title,
                "goal": facts_by_id.get("goal", Fact(id="goal", description="")).description,
                "origin": facts_by_id.get("origin", Fact(id="origin", description="")).description,
            },
            "statistics": {
                "total_fact_count": len(project.facts),
                "included_fact_count": len(included_fact_ids),
                "omitted_fact_count": max(0, len(project.facts) - len(included_fact_ids)),
            },
            "hints": [
                {"id": hint.id, "content": hint.content, "creator": hint.creator, "created_at": hint.created_at}
                for hint in project.hints
            ],
            "facts": [self._fact_item(facts_by_id[fact_id]) for fact_id in included_fact_ids if fact_id in facts_by_id],
        }

        if view_type == FactViewType.REASON:
            payload["branch_coverage"] = self._branch_coverage_items(project)
            payload["open_intents"] = [
                self._intent_item(open_intent)
                for open_intent in sorted(
                    [item for item in project.intents if item.to is None],
                    key=intent_priority_key,
                    reverse=True,
                )[:12]
            ]
            payload["completed_intents"] = [
                self._intent_chain_item(item)
                for item in sorted(
                    [item for item in project.intents if item.to is not None],
                    key=lambda item: item.concluded_at or item.created_at,
                    reverse=True,
                )[:24]
            ]
        elif intent is not None:
            payload["current_intent"] = self._intent_item(intent)
            payload["related_intents"] = [
                self._intent_chain_item(item)
                for item in project.intents
                if item.id != intent.id and (set(item.from_) & set(intent.from_) or item.to in intent.from_)
            ][:16]
        return payload

    def _fit_fact_ids(
        self,
        project: ProjectDetail,
        view_type: FactViewType,
        fact_ids: list[str],
        *,
        budget: int,
        full_graph_reference: str,
        intent: Intent | None,
    ) -> list[str]:
        required = set(ANCHOR_FACT_IDS)
        if intent is not None:
            required.update(intent.from_)
        fitted = list(fact_ids)
        while len(fitted) > len(required):
            yaml_text = _dump_yaml(
                self._payload(
                    project,
                    view_type,
                    fitted,
                    full_graph_reference=full_graph_reference,
                    intent=intent,
                )
            )
            if len(yaml_text) <= budget:
                break
            removable_index = next((idx for idx in range(len(fitted) - 1, -1, -1) if fitted[idx] not in required), None)
            if removable_index is None:
                break
            fitted.pop(removable_index)
        return fitted

    def _recent_completed_fact_ids(self, project: ProjectDetail, *, limit: int) -> list[str]:
        completed = [intent for intent in project.intents if intent.to and intent.to not in ANCHOR_FACT_IDS]
        completed.sort(key=lambda item: item.concluded_at or item.created_at, reverse=True)
        return [intent.to for intent in completed[:limit] if intent.to]

    def _completed_chain_fact_ids(self, project: ProjectDetail, *, limit: int) -> list[str]:
        fact_ids: list[str] = []
        for intent in project.intents:
            if intent.to is None:
                continue
            fact_ids.extend(intent.from_)
            if intent.to:
                fact_ids.append(intent.to)
            if len(fact_ids) >= limit:
                break
        return fact_ids[:limit]

    def _upstream_one_hop_fact_ids(self, project: ProjectDetail, source_fact_ids: list[str]) -> list[str]:
        upstream: list[str] = []
        source_set = set(source_fact_ids)
        for intent in project.intents:
            if intent.to in source_set:
                upstream.extend(intent.from_)
        return upstream

    def _related_fact_ids(self, project: ProjectDetail, source_fact_ids: list[str], *, limit: int) -> list[str]:
        source_set = set(source_fact_ids)
        related: list[str] = []
        for intent in project.intents:
            if set(intent.from_) & source_set and intent.to is not None:
                related.append(intent.to)
        return related[:limit]

    def _fact_item(self, fact: Fact) -> dict[str, str]:
        return {"id": fact.id, "description": fact.description}

    def _intent_item(self, intent: Intent) -> dict[str, Any]:
        return {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "creator": intent.creator,
            "worker": intent.worker,
            "priority_score": intent.priority_score,
            "intent_kind": intent.intent_kind,
            "tags": intent.tags,
            "score_reason": intent.score_reason,
            "branch_key": intent.branch_key,
            "branch_depth": intent.branch_depth,
            "expected_value": intent.expected_value,
            "created_at": intent.created_at,
            "concluded_at": intent.concluded_at,
        }

    def _branch_coverage_items(self, project: ProjectDetail) -> list[dict[str, Any]]:
        facts_by_id = {fact.id: fact for fact in project.facts}
        by_family: dict[str, list[Intent]] = defaultdict(list)
        for intent in project.intents:
            family = _branch_family(intent.branch_key)
            if family is None:
                continue
            by_family[family].append(intent)

        items: list[dict[str, Any]] = []
        for family, intents in by_family.items():
            sorted_intents = sorted(intents, key=lambda item: item.concluded_at or item.created_at, reverse=True)
            open_intents = [intent for intent in sorted_intents if intent.to is None]
            running_intents = [intent for intent in open_intents if intent.worker is not None]
            completed_intents = [intent for intent in sorted_intents if intent.to is not None]
            latest = sorted_intents[0]
            negative_scopes = _negative_scope_items(completed_intents, facts_by_id)
            items.append(
                {
                    "family": family,
                    "leaf_count": len({intent.branch_key for intent in intents if intent.branch_key}),
                    "covered_leaf_ids": sorted(
                        {intent.branch_key for intent in completed_intents if intent.branch_key}
                    ),
                    "latest_result": self._branch_latest_result(latest),
                    "latest_negative_scope": negative_scopes[0] if negative_scopes else None,
                    "open_coverage_gaps": _open_coverage_gaps(sorted_intents, facts_by_id),
                    "family_supporting_facts": _family_supporting_facts(sorted_intents, facts_by_id),
                    "positive_clues": _branch_clues(sorted_intents, positive=True),
                    "negative_clues": _branch_clues(sorted_intents, positive=False),
                    "open_intent_ids": [intent.id for intent in open_intents[:6]],
                    "running_intent_ids": [intent.id for intent in running_intents[:6]],
                    "completed_intent_ids": [intent.id for intent in completed_intents[:6]],
                }
            )
        return sorted(items, key=lambda item: item["family"])[:12]

    def _branch_latest_result(self, intent: Intent) -> dict[str, Any]:
        return {
            "intent_id": intent.id,
            "branch_key": intent.branch_key,
            "status": "open" if intent.to is None else "completed",
            "to": intent.to,
            "summary": intent.score_reason or intent.description,
        }

    def _intent_chain_item(self, intent: Intent) -> dict[str, Any]:
        return {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "branch_key": intent.branch_key,
            "branch_depth": intent.branch_depth,
            "expected_value": intent.expected_value,
            "priority_score": intent.priority_score,
            "score_reason": intent.score_reason,
            "created_at": intent.created_at,
            "concluded_at": intent.concluded_at,
        }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dump_yaml(payload: dict[str, Any]) -> str:
    return yaml.dump(payload, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _branch_family(branch_key: str | None) -> str | None:
    if branch_key is None:
        return None
    parts = [part for part in branch_key.split(".") if part]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ".".join(parts[:-1])


def _intent_fact_text(intent: Intent, facts_by_id: dict[str, Fact]) -> str:
    parts = [intent.description, intent.score_reason or "", " ".join(intent.tags)]
    if intent.to is not None and intent.to in facts_by_id:
        parts.append(facts_by_id[intent.to].description)
    return " ".join(parts)


def _negative_scope_item(intent: Intent, facts_by_id: dict[str, Fact]) -> dict[str, str] | None:
    text = _intent_fact_text(intent, facts_by_id)
    lowered = text.lower()
    if not any(term in lowered for term in _NEGATIVE_CLUE_TERMS):
        return None
    scope = _excerpt_for_terms(text, _TESTED_SCOPE_TERMS) or intent.description
    limits = _excerpt_for_terms(text, _NEGATIVE_LIMIT_TERMS) or text
    return {
        "intent_id": intent.id,
        "branch_key": intent.branch_key or "",
        "tested_scope": scope,
        "failure_limit": limits,
    }


def _negative_scope_items(intents: list[Intent], facts_by_id: dict[str, Fact]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for intent in intents:
        item = _negative_scope_item(intent, facts_by_id)
        if item is not None:
            items.append(item)
    return items


def _open_coverage_gaps(intents: list[Intent], facts_by_id: dict[str, Fact]) -> list[str]:
    gaps: list[str] = []
    for intent in intents:
        text = _intent_fact_text(intent, facts_by_id)
        lowered = text.lower()
        if any(term in lowered for term in _COVERAGE_GAP_TERMS):
            gaps.append(_excerpt_for_terms(text, _COVERAGE_GAP_TERMS) or text)
        if len(gaps) >= 4:
            break
    return gaps


def _family_supporting_facts(intents: list[Intent], facts_by_id: dict[str, Fact]) -> list[dict[str, str]]:
    supporting: list[dict[str, str]] = []
    for intent in intents:
        if intent.to is None or intent.to not in facts_by_id:
            continue
        fact = facts_by_id[intent.to]
        lowered = fact.description.lower()
        if any(term in lowered for term in _POSITIVE_CLUE_TERMS):
            supporting.append({"fact_id": fact.id, "description": fact.description})
        if len(supporting) >= 4:
            break
    return supporting


def _excerpt_for_terms(text: str, terms: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for term in terms:
        index = lowered.find(term)
        if index < 0:
            continue
        start = max(0, index - 80)
        end = min(len(text), index + len(term) + 160)
        return text[start:end].strip()
    return None


def _branch_clues(intents: list[Intent], *, positive: bool) -> list[str]:
    terms = _POSITIVE_CLUE_TERMS if positive else _NEGATIVE_CLUE_TERMS
    clues: list[str] = []
    for intent in intents:
        text = " ".join([intent.description, intent.score_reason or "", " ".join(intent.tags)]).lower()
        if positive and any(term in text for term in _NEGATIVE_CLUE_TERMS):
            continue
        if any(term in text for term in terms):
            clues.append(intent.score_reason or intent.description)
        if len(clues) >= 4:
            break
    return clues


_POSITIVE_CLUE_TERMS = (
    "evidence",
    "confirmed",
    "signal",
    "clue",
    "supports",
    "positive",
)

_NEGATIVE_CLUE_TERMS = (
    "failed",
    "failure",
    "negative",
    "not found",
    "no evidence",
    "ruled out",
    "excluded",
    "blocked",
)

_TESTED_SCOPE_TERMS = (
    "tested",
    "method",
    "scope",
    "covered",
    "attempted",
)

_NEGATIVE_LIMIT_TERMS = (
    "failed",
    "failure",
    "not found",
    "no evidence",
    "blocked",
    "negative",
)

_COVERAGE_GAP_TERMS = (
    "coverage gap",
    "partial coverage",
    "partially covered",
    "untested",
    "not tested",
    "not ruled out",
    "not excluded",
    "uncovered",
    "sibling",
)
