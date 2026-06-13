from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from cairn.dispatcher.models import ReasonCheckpoint
from cairn.shared.contracts import Intent, ProjectDetail, ProjectWorkSummary

BOOTSTRAP_INTENT_DESCRIPTION = "bootstrap"
BOOTSTRAP_INTENT_CREATOR = "dispatcher.bootstrap"


@dataclass(frozen=True, slots=True)
class ReasonTrigger:
    trigger: str
    trigger_hash: str


def is_bootstrap_intent(intent: Intent) -> bool:
    return (
        intent.description == BOOTSTRAP_INTENT_DESCRIPTION
        and intent.creator == BOOTSTRAP_INTENT_CREATOR
        and intent.from_ == ["origin"]
        and intent.to is None
    )


def bootstrap_intent(project: ProjectDetail) -> Intent | None:
    intents = [intent for intent in project.intents if is_bootstrap_intent(intent)]
    if not intents:
        return None
    intents.sort(key=lambda intent: (intent.worker is not None, intent.created_at, intent.id))
    return intents[0]


def bootstrap_intent_count(project: ProjectDetail) -> int:
    return sum(1 for intent in project.intents if is_bootstrap_intent(intent))


def is_initial_project(project: ProjectDetail) -> bool:
    fact_ids = {fact.id for fact in project.facts}
    if fact_ids != {"origin", "goal"} or len(project.facts) != 2:
        return False
    if not project.intents:
        return True
    return all(is_bootstrap_intent(intent) for intent in project.intents)


def project_open_intent_count(project: ProjectDetail) -> int:
    return sum(1 for intent in project.intents if intent.to is None)


def reason_trigger(project: ProjectDetail, checkpoint: ReasonCheckpoint | None) -> ReasonTrigger | None:
    open_intent_count = project_open_intent_count(project)
    if checkpoint is None:
        return _reason_trigger("initial")
    changes: list[str] = []
    if len(project.facts) > checkpoint.fact_count:
        changes.append(f"facts:{checkpoint.fact_count}->{len(project.facts)}")
    if len(project.hints) > checkpoint.hint_count:
        changes.append(f"hints:{checkpoint.hint_count}->{len(project.hints)}")
    if checkpoint.open_intent_count > 0 and open_intent_count == 0:
        changes.append(f"open_intents:{checkpoint.open_intent_count}->0")
    if not changes:
        return None
    return _reason_trigger(",".join(changes))


def summary_reason_might_run(
    summary: ProjectWorkSummary,
    checkpoint: ReasonCheckpoint | None,
) -> bool:
    open_intent_count = summary.working_intent_count + summary.unclaimed_intent_count
    if checkpoint is None:
        return True
    if summary.fact_count > checkpoint.fact_count:
        return True
    if summary.hint_count > checkpoint.hint_count:
        return True
    return checkpoint.open_intent_count > 0 and open_intent_count == 0


def _reason_trigger(trigger: str) -> ReasonTrigger:
    return ReasonTrigger(
        trigger=trigger,
        trigger_hash=sha256(trigger.encode("utf-8")).hexdigest(),
    )
