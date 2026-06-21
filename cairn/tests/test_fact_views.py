from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _ts(value: int = 0) -> str:
    return f"2026-06-06T00:00:{value:02d}Z"


def _project(*, facts=None, intents=None, hints=None):
    from cairn.shared.contracts import Fact, Hint, ProjectDetail, ProjectMeta

    return ProjectDetail(
        project=ProjectMeta(id="proj_001", title="T", status="active", created_at=_ts()),
        facts=facts
        or [
            Fact(id="origin", description="origin fact"),
            Fact(id="goal", description="goal fact"),
            Fact(id="f001", description="first result"),
        ],
        intents=intents or [],
        hints=hints or [Hint(id="h001", content="use hint", creator="user", created_at=_ts())],
        proxy=None,
    )


def _intent(intent_id: str, *, from_ids=None, to=None, description="intent", priority_score=None):
    from cairn.shared.contracts import Intent

    return Intent(
        id=intent_id,
        **{"from": from_ids or ["origin"]},
        to=to,
        description=description,
        creator="reason",
        worker=None,
        created_at=_ts(int(intent_id[-1]) if intent_id[-1].isdigit() else 0),
        concluded_at=_ts(int(intent_id[-1]) if to else 0) if to else None,
        priority_score=priority_score,
    )


class FactViewTests(unittest.TestCase):
    def test_reason_view_includes_origin_goal_hints_and_full_graph_reference(self) -> None:
        from cairn.dispatcher.tasks.fact_views import FactViewRenderer

        view = FactViewRenderer().render_reason_view(_project(), full_graph_reference="/tmp/graph.yaml")
        data = yaml.safe_load(view.yaml_text)

        fact_ids = {fact["id"] for fact in data["facts"]}
        self.assertIn("origin", fact_ids)
        self.assertIn("goal", fact_ids)
        self.assertEqual(data["hints"][0]["content"], "use hint")
        self.assertEqual(data["view"]["full_graph_reference"], "/tmp/graph.yaml")

    def test_worker_view_includes_current_intent_source_facts(self) -> None:
        from cairn.dispatcher.tasks.fact_views import FactViewRenderer
        from cairn.shared.contracts import Fact

        intent = _intent("i002", from_ids=["f001"], priority_score=0.7)
        project = _project(
            facts=[
                Fact(id="origin", description="origin fact"),
                Fact(id="goal", description="goal fact"),
                Fact(id="f001", description="source fact"),
            ],
            intents=[intent],
        )

        view = FactViewRenderer().render_worker_view(project, intent=intent, full_graph_reference="/tmp/graph.yaml")
        data = yaml.safe_load(view.yaml_text)

        fact_ids = {fact["id"] for fact in data["facts"]}
        self.assertIn("f001", fact_ids)
        self.assertEqual(data["current_intent"]["id"], "i002")
        self.assertEqual(data["current_intent"]["priority_score"], 0.7)

    def test_large_reason_view_reports_omitted_facts(self) -> None:
        from cairn.dispatcher.tasks.fact_views import FactViewRenderer
        from cairn.shared.contracts import Fact

        facts = [
            Fact(id="origin", description="origin fact"),
            Fact(id="goal", description="goal fact"),
        ]
        facts.extend(Fact(id=f"f{i:03d}", description="x" * 1200) for i in range(80))
        project = _project(facts=facts, intents=[_intent("i001", to="f001")])

        view = FactViewRenderer().render_reason_view(project, full_graph_reference="/tmp/graph.yaml")
        data = yaml.safe_load(view.yaml_text)

        self.assertGreater(data["statistics"]["omitted_fact_count"], 0)
        self.assertEqual(data["view"]["full_graph_reference"], "/tmp/graph.yaml")


if __name__ == "__main__":
    unittest.main()
