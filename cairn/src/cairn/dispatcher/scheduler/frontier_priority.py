from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from cairn.shared.contracts import Fact, Intent

DEFAULT_INTENT_PRIORITY = 0.5
EXPECTED_VALUE_BONUS = 0.15
NOVELTY_BONUS = 0.02
EVIDENCE_STRENGTH_BONUS = 0.10
COVERAGE_GAP_BONUS = 0.08
MECHANISM_PROXIMITY_BONUS = 0.07
MAX_EVIDENCE_COVERAGE_BONUS = 0.16
SAME_BRANCH_RUNNING_PENALTY = 1.0
BRANCH_DEPTH_PENALTY = 0.08
REPEATED_BRANCH_OPEN_PENALTY = 0.05

STRONG_EVIDENCE_TERMS = (
    "strong evidence",
    "high confidence",
    "high-confidence",
    "credible evidence",
    "direct evidence",
    "confirmed clue",
    "confirmed signal",
    "strong signal",
)
WEAK_EVIDENCE_TERMS = (
    "evidence",
    "clue",
    "signal",
    "indicator",
    "confirmed",
    "supports",
)
NEGATIVE_EVIDENCE_TERMS = (
    "failed",
    "failure",
    "no evidence",
    "no supporting",
    "not found",
    "ruled out",
    "excluded",
    "unsupported",
    "without support",
    "without supporting",
)
COVERAGE_GAP_TERMS = (
    "coverage gap",
    "partial coverage",
    "partially covered",
    "only partially tested",
    "uncovered",
    "not covered",
    "untested",
    "not tested",
    "not ruled out",
    "not excluded",
    "sibling",
    "new leaf",
)
NEGATION_BOUNDARY_TERMS = (
    "not ruled out",
    "not excluded",
    "partial coverage",
    "partially covered",
    "only partially tested",
    "coverage gap",
    "untested sibling",
    "sibling untested",
    "uncovered sibling",
)
MECHANISM_PROXIMITY_TERMS = (
    "direct gate",
    "goal gate",
    "state transition",
    "data sink",
    "data source",
    "sink",
    "credential check",
    "authorization check",
    "auth check",
    "stored secret",
    "confirmed primitive",
    "causal mechanism",
    "direct mechanism",
    "direct path",
)


@dataclass(frozen=True, slots=True)
class IntentEffectiveScore:
    intent_id: str
    effective_score: float
    priority_score: float
    expected_value_bonus: float = 0.0
    novelty_bonus: float = 0.0
    evidence_strength_bonus: float = 0.0
    coverage_gap_bonus: float = 0.0
    mechanism_proximity_bonus: float = 0.0
    negative_scope: str = "none"
    same_branch_running_penalty: float = 0.0
    branch_depth_penalty: float = 0.0
    repeated_branch_open_penalty: float = 0.0


def intent_priority_score(intent: Intent) -> float:
    if intent.priority_score is None:
        return DEFAULT_INTENT_PRIORITY
    return intent.priority_score


def intent_priority_key(intent: Intent) -> tuple[float, str, str]:
    return (intent_priority_score(intent), intent.created_at, intent.id)


def select_next_intent(
    *,
    project_intents: list[Intent],
    unclaimed_intents: list[Intent],
    running_intent_ids: set[str],
    project_facts: list[Fact] | None = None,
) -> Intent | None:
    if not unclaimed_intents:
        return None
    if all(intent.branch_key is None for intent in unclaimed_intents):
        return max(unclaimed_intents, key=intent_priority_key)

    selectable = selectable_intents(
        project_intents=project_intents,
        candidate_intents=unclaimed_intents,
        running_intent_ids=running_intent_ids,
    )
    if not selectable:
        return None

    score_by_id = effective_score_by_intent(
        project_intents=project_intents,
        candidate_intents=selectable,
        running_intent_ids=running_intent_ids,
        project_facts=project_facts,
    )
    return max(selectable, key=lambda intent: (score_by_id[intent.id].effective_score, intent.created_at, intent.id))


def selectable_intents(
    *,
    project_intents: list[Intent],
    candidate_intents: list[Intent],
    running_intent_ids: set[str],
) -> list[Intent]:
    if not candidate_intents:
        return []
    if all(intent.branch_key is None for intent in candidate_intents):
        return list(candidate_intents)
    running_branch_keys = _running_branch_keys(project_intents, running_intent_ids)
    return [
        intent
        for intent in candidate_intents
        if intent.branch_key is None or intent.branch_key not in running_branch_keys
    ]


def effective_score_by_intent(
    *,
    project_intents: list[Intent],
    candidate_intents: list[Intent],
    running_intent_ids: set[str],
    project_facts: list[Fact] | None = None,
) -> dict[str, IntentEffectiveScore]:
    running_branch_keys = _running_branch_keys(project_intents, running_intent_ids)
    source_fact_text_by_id = {fact.id: fact.description for fact in project_facts or []}
    open_count_by_branch = Counter(
        intent.branch_key
        for intent in project_intents
        if intent.to is None and intent.branch_key is not None
    )
    completed_branch_keys = {
        intent.branch_key
        for intent in project_intents
        if intent.to is not None and intent.branch_key is not None
    }
    return {
        intent.id: _effective_score(
            intent,
            running_branch_keys=running_branch_keys,
            open_count_by_branch=open_count_by_branch,
            completed_branch_keys=completed_branch_keys,
            source_fact_text_by_id=source_fact_text_by_id,
        )
        for intent in candidate_intents
    }


def _effective_score(
    intent: Intent,
    *,
    running_branch_keys: set[str],
    open_count_by_branch: Counter[str | None],
    completed_branch_keys: set[str],
    source_fact_text_by_id: dict[str, str],
) -> IntentEffectiveScore:
    priority = intent_priority_score(intent)
    if intent.branch_key is None:
        return IntentEffectiveScore(
            intent_id=intent.id,
            effective_score=priority,
            priority_score=priority,
        )

    expected_value_bonus = EXPECTED_VALUE_BONUS * intent.expected_value if intent.expected_value is not None else 0.0
    novelty_bonus = NOVELTY_BONUS if intent.branch_key not in completed_branch_keys else 0.0
    evidence_strength_bonus, coverage_gap_bonus, mechanism_proximity_bonus, negative_scope = _evidence_coverage_bonus(
        intent,
        source_fact_text_by_id,
    )
    same_branch_running_penalty = SAME_BRANCH_RUNNING_PENALTY if intent.branch_key in running_branch_keys else 0.0
    branch_depth_penalty = BRANCH_DEPTH_PENALTY * intent.branch_depth
    repeated_branch_open_penalty = REPEATED_BRANCH_OPEN_PENALTY * max(
        0,
        open_count_by_branch[intent.branch_key] - 1,
    )
    score = (
        priority
        + expected_value_bonus
        + novelty_bonus
        + evidence_strength_bonus
        + coverage_gap_bonus
        + mechanism_proximity_bonus
        - same_branch_running_penalty
        - branch_depth_penalty
        - repeated_branch_open_penalty
    )
    return IntentEffectiveScore(
        intent_id=intent.id,
        effective_score=score,
        priority_score=priority,
        expected_value_bonus=expected_value_bonus,
        novelty_bonus=novelty_bonus,
        evidence_strength_bonus=evidence_strength_bonus,
        coverage_gap_bonus=coverage_gap_bonus,
        mechanism_proximity_bonus=mechanism_proximity_bonus,
        negative_scope=negative_scope,
        same_branch_running_penalty=same_branch_running_penalty,
        branch_depth_penalty=branch_depth_penalty,
        repeated_branch_open_penalty=repeated_branch_open_penalty,
    )


def _running_branch_keys(project_intents: list[Intent], running_intent_ids: set[str]) -> set[str]:
    return {
        intent.branch_key
        for intent in project_intents
        if intent.branch_key is not None
        and intent.to is None
        and (intent.worker is not None or intent.id in running_intent_ids)
    }


def _evidence_coverage_bonus(intent: Intent, source_fact_text_by_id: dict[str, str]) -> tuple[float, float, float, str]:
    text = _intent_evidence_text(intent, source_fact_text_by_id)
    negative_scope = _negative_evidence_scope(text)
    evidence_bonus = 0.0
    negative_evidence = negative_scope == "leaf"
    if not negative_evidence and any(term in text for term in STRONG_EVIDENCE_TERMS):
        evidence_bonus = EVIDENCE_STRENGTH_BONUS
    elif not negative_evidence and any(term in text for term in WEAK_EVIDENCE_TERMS):
        evidence_bonus = EVIDENCE_STRENGTH_BONUS / 2

    coverage_bonus = COVERAGE_GAP_BONUS if any(term in text for term in COVERAGE_GAP_TERMS) else 0.0
    proximity_bonus = MECHANISM_PROXIMITY_BONUS if any(term in text for term in MECHANISM_PROXIMITY_TERMS) else 0.0
    combined = evidence_bonus + coverage_bonus
    if combined <= MAX_EVIDENCE_COVERAGE_BONUS:
        return evidence_bonus, coverage_bonus, proximity_bonus, negative_scope
    scale = MAX_EVIDENCE_COVERAGE_BONUS / combined
    return evidence_bonus * scale, coverage_bonus * scale, proximity_bonus, negative_scope


def _negative_evidence_scope(text: str) -> str:
    has_negative = any(term in text for term in NEGATIVE_EVIDENCE_TERMS)
    if not has_negative:
        return "none"
    if any(term in text for term in NEGATION_BOUNDARY_TERMS):
        return "bounded"
    return "leaf"


def _intent_evidence_text(intent: Intent, source_fact_text_by_id: dict[str, str]) -> str:
    parts = [
        intent.description,
        intent.score_reason or "",
        " ".join(intent.tags),
    ]
    parts.extend(source_fact_text_by_id.get(fact_id, "") for fact_id in intent.from_)
    return " ".join(parts).lower()
