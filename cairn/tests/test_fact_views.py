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


def _intent(
    intent_id: str,
    *,
    from_ids=None,
    to=None,
    description="intent",
    priority_score=None,
    branch_key=None,
    branch_depth=0,
    expected_value=None,
    score_reason=None,
):
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
        score_reason=score_reason,
        branch_key=branch_key,
        branch_depth=branch_depth,
        expected_value=expected_value,
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

        intent = _intent(
            "i002",
            from_ids=["f001"],
            priority_score=0.7,
            branch_key="area.family.method_a",
            branch_depth=1,
            expected_value=0.8,
        )
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
        self.assertEqual(data["current_intent"]["branch_key"], "area.family.method_a")
        self.assertEqual(data["current_intent"]["branch_depth"], 1)
        self.assertEqual(data["current_intent"]["expected_value"], 0.8)

    def test_reason_view_includes_branch_coverage_summary(self) -> None:
        from cairn.dispatcher.tasks.fact_views import FactViewRenderer
        from cairn.shared.contracts import Fact

        completed = _intent(
            "i001",
            to="f001",
            description="method A produced no evidence",
            branch_key="area.family.method_a",
            score_reason="method A failed and left method B untested",
        )
        open_sibling = _intent(
            "i002",
            description="method B has confirmed signal and coverage gap",
            branch_key="area.family.method_b",
            score_reason="strong evidence remains; sibling coverage gap is open",
        )

        view = FactViewRenderer().render_reason_view(
            _project(
                facts=[
                    Fact(id="origin", description="origin fact"),
                    Fact(id="goal", description="goal fact"),
                    Fact(
                        id="f001",
                        description=(
                            "Tested method A parser path failed at the input boundary. "
                            "The broader family still has confirmed signal and method B is not ruled out."
                        ),
                    ),
                ],
                intents=[completed, open_sibling],
            ),
            full_graph_reference="/tmp/graph.yaml",
        )
        data = yaml.safe_load(view.yaml_text)

        coverage = data["branch_coverage"][0]
        self.assertEqual(coverage["family"], "area.family")
        self.assertEqual(coverage["leaf_count"], 2)
        self.assertEqual(coverage["covered_leaf_ids"], ["area.family.method_a"])
        self.assertEqual(coverage["latest_result"]["branch_key"], "area.family.method_b")
        self.assertEqual(coverage["latest_negative_scope"]["branch_key"], "area.family.method_a")
        self.assertIn("Tested method A", coverage["latest_negative_scope"]["tested_scope"])
        self.assertTrue(coverage["open_coverage_gaps"])
        self.assertEqual(coverage["family_supporting_facts"][0]["fact_id"], "f001")
        self.assertEqual(coverage["open_intent_ids"], ["i002"])
        self.assertEqual(coverage["completed_intent_ids"], ["i001"])
        self.assertTrue(coverage["positive_clues"])
        self.assertTrue(coverage["negative_clues"])

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
