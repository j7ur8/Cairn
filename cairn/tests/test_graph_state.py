from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class GraphStateTests(unittest.TestCase):
    def _run_node_json(self, script: str):
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=_REPO,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_build_elements_uses_intent_ids_for_edge_labels(self) -> None:
        script = textwrap.dedent(
            """
            import { pathToFileURL } from 'node:url';

            const mod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-graph.js'));
            const state = mod.createWorkspaceGraphState();
            state.project = {
              facts: [
                { id: 'origin', description: 'Origin fact' },
                { id: 'fact_a', description: 'Fact A' },
              ],
              intents: [
                { id: 'i001', description: 'Concluded intent text', from: ['origin'], to: 'fact_a' },
                { id: 'i002', description: 'Open intent text', from: ['fact_a'], to: '' },
              ],
            };
            state.summarizeFactLabel = fact => fact.id;
            state.factNodeSize = () => ({ width: 10, height: 10 });
            state.isBootstrapIntent = () => false;

            const { edges } = state.buildElements();
            console.log(JSON.stringify(edges.map(edge => edge.data)));
            """
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=_REPO,
            text=True,
            capture_output=True,
            check=True,
        )

        edges = {edge["id"]: edge for edge in json.loads(result.stdout)}
        self.assertEqual(edges["i001_origin"]["source"], "origin")
        self.assertEqual(edges["i001_origin"]["target"], "fact_a")
        self.assertEqual(edges["i001_origin"]["label"], "i001")
        self.assertEqual(edges["i002_fact_a"]["source"], "fact_a")
        self.assertEqual(edges["i002_fact_a"]["target"], "_ph_i002")
        self.assertEqual(edges["i002_fact_a"]["label"], "i002")
        self.assertEqual(edges["i002_fact_a"]["intentId"], "i002")
        self.assertNotIn("Concluded intent text", {edge["label"] for edge in edges.values()})
        self.assertNotIn("Open intent text", {edge["label"] for edge in edges.values()})

    def test_select_intent_selects_matching_llm_execution(self) -> None:
        script = textwrap.dedent(
            """
            import { pathToFileURL } from 'node:url';

            const graphMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-graph.js'));
            const logMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-llm-log.js'));
            const state = { ...graphMod.createWorkspaceGraphState(), ...logMod.createWorkspaceLogState() };
            let resetCount = 0;
            state.resetLlmEventPagination = () => { resetCount++; };
            state.applyLineageHighlightForIntent = () => {};
            state.llmExecutions = [
              { id: 'exec-other', intent_id: 'intent-other' },
              { id: 'exec-target', intent_id: 'intent-target' },
            ];
            state.llmSelectedExecutionId = state.ALL_LLM_EXECUTIONS_VALUE;

            state.selectIntent('intent-target');

            console.log(JSON.stringify({
              selectedNode: state.selectedNode,
              llmSelectedExecutionId: state.llmSelectedExecutionId,
              resetCount,
            }));
            """
        )

        self.assertEqual(
            self._run_node_json(script),
            {
                "selectedNode": {"type": "intent", "id": "intent-target"},
                "llmSelectedExecutionId": "exec-target",
                "resetCount": 1,
            },
        )

    def test_select_intent_uses_first_matching_llm_execution(self) -> None:
        script = textwrap.dedent(
            """
            import { pathToFileURL } from 'node:url';

            const graphMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-graph.js'));
            const logMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-llm-log.js'));
            const state = { ...graphMod.createWorkspaceGraphState(), ...logMod.createWorkspaceLogState() };
            state.resetLlmEventPagination = () => {};
            state.applyLineageHighlightForIntent = () => {};
            state.llmExecutions = [
              { id: 'exec-newest', intent_id: 'intent-target' },
              { id: 'exec-older', intent_id: 'intent-target' },
            ];
            state.llmSelectedExecutionId = state.ALL_LLM_EXECUTIONS_VALUE;

            state.selectIntent({ id: 'intent-target' });

            console.log(JSON.stringify({ llmSelectedExecutionId: state.llmSelectedExecutionId }));
            """
        )

        self.assertEqual(self._run_node_json(script), {"llmSelectedExecutionId": "exec-newest"})

    def test_select_intent_keeps_llm_selection_without_matching_execution(self) -> None:
        script = textwrap.dedent(
            """
            import { pathToFileURL } from 'node:url';

            const graphMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-graph.js'));
            const logMod = await import(pathToFileURL('cairn/src/cairn/server/static/js/workspace/state-llm-log.js'));
            const state = { ...graphMod.createWorkspaceGraphState(), ...logMod.createWorkspaceLogState() };
            let resetCount = 0;
            state.resetLlmEventPagination = () => { resetCount++; };
            state.applyLineageHighlightForIntent = () => {};
            state.llmExecutions = [{ id: 'exec-other', intent_id: 'intent-other' }];
            state.llmSelectedExecutionId = 'exec-current';

            state.selectIntent('intent-target');

            console.log(JSON.stringify({
              llmSelectedExecutionId: state.llmSelectedExecutionId,
              resetCount,
            }));
            """
        )

        self.assertEqual(
            self._run_node_json(script),
            {"llmSelectedExecutionId": "exec-current", "resetCount": 0},
        )
