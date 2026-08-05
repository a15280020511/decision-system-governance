from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "control-plane"
if str(CONTROL) not in sys.path:
    sys.path.insert(0, str(CONTROL))


def load_module():
    path = CONTROL / "governed_expert_admission.py"
    spec = importlib.util.spec_from_file_location("governed_expert_admission_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load governed expert admission")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load_module()


def ticket():
    return {
        "route": "expert-team",
        "team_plan": {
            "schema_version": "expert-team-plan-v1",
            "expected_prompt_tokens_per_call": 10_000,
            "expected_completion_tokens_per_call": 2_000,
            "work_items": [
                {
                    "work_id": "analysis",
                    "objective": "Analyze.",
                    "role": "analysis",
                    "dependencies": [],
                    "required_outputs": ["findings"],
                },
                {
                    "work_id": "synthesis",
                    "objective": "Synthesize.",
                    "role": "synthesis",
                    "dependencies": ["analysis"],
                    "required_outputs": ["report"],
                },
            ],
            "final_work_id": "synthesis",
        },
        "approved_budget": {
            "calls": 2,
            "maximum_recovery_calls": 0,
            "cost_policy": "prompt_led_soft_governance",
        },
    }


def ranking():
    return {
        "schema_version": "governance-openrouter-task-cost-ranking-v1",
        "ranked_paid_flagship_candidates": [
            {"model_id": "openai/a", "company": "openai", "estimated_task_cost_usd": 0.001},
            {"model_id": "deepseek/b", "company": "deepseek", "estimated_task_cost_usd": 0.002},
            {"model_id": "qwen/c", "company": "qwen", "estimated_task_cost_usd": 0.003},
        ],
    }


class GovernedExpertAdmissionTests(unittest.TestCase):
    def test_filters_ranked_models_to_live_zdr_inventory_before_roster_build(self):
        captured = {}

        def build(ticket_value, ranking_value, *, governance_commit_sha):
            captured["ranking"] = ranking_value
            captured["sha"] = governance_commit_sha
            return {
                **ticket_value,
                "governance_roster": {
                    "schema_version": "governed-expert-roster-v1",
                    "status": "GOVERNED_EXPERT_ROSTER_READY",
                    "roster_sha256": "a" * 64,
                },
            }

        with mock.patch.object(mod.roster_core, "select_flagships", return_value={}), mock.patch.object(
            mod.roster_core,
            "rank_flagships_by_task_cost",
            return_value=ranking(),
        ), mock.patch.object(
            mod,
            "_fetch_json",
            return_value={
                "data": [
                    {"model_id": "deepseek/b", "provider": "p1"},
                    {"model_id": "qwen/c", "provider": "p2"},
                ]
            },
        ), mock.patch.object(
            mod.roster_core,
            "build_governed_expert_roster",
            side_effect=build,
        ):
            result = mod.enrich_expert_ticket_live(
                ticket(),
                governance_commit_sha="b" * 40,
                token="test-token",
            )

        ids = [
            row["model_id"]
            for row in captured["ranking"]["ranked_paid_flagship_candidates"]
        ]
        self.assertEqual(ids, ["deepseek/b", "qwen/c"])
        self.assertEqual(captured["sha"], "b" * 40)
        self.assertNotIn("zdr_snapshot_sha256", result["governance_roster"])
        self.assertEqual(
            captured["ranking"]["zdr_filter"]["model_calls"],
            0,
        )
        self.assertEqual(captured["ranking"]["zdr_filter"]["cost_usd"], 0)
        self.assertFalse(
            captured["ranking"]["zdr_filter"]["secret_values_exposed"]
        )

    def test_no_zdr_eligible_flagship_fails_closed(self):
        with mock.patch.object(mod.roster_core, "select_flagships", return_value={}), mock.patch.object(
            mod.roster_core,
            "rank_flagships_by_task_cost",
            return_value=ranking(),
        ), mock.patch.object(
            mod,
            "_fetch_json",
            return_value={"data": [{"model_id": "other/not-ranked"}]},
        ):
            with self.assertRaisesRegex(
                mod.GovernedExpertAdmissionError,
                "no paid general-purpose flagship",
            ):
                mod.enrich_expert_ticket_live(
                    ticket(),
                    governance_commit_sha="b" * 40,
                    token="test-token",
                )

    def test_missing_key_fails_closed_before_catalog_requests(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False), mock.patch.object(
            mod.roster_core, "select_flagships"
        ) as selector:
            with self.assertRaisesRegex(
                mod.GovernedExpertAdmissionError,
                "OPENROUTER_API_KEY",
            ):
                mod.enrich_expert_ticket_live(
                    ticket(),
                    governance_commit_sha="b" * 40,
                )
        selector.assert_not_called()

    def test_zdr_inventory_hash_is_deterministic(self):
        payload = {
            "data": [
                {"model_id": "a/model", "provider": "p"},
                {"model_id": "b/model", "provider": "q"},
            ]
        }
        first = mod._zdr_model_ids(payload)
        second = mod._zdr_model_ids(payload)
        self.assertEqual(first, second)
        self.assertEqual(first[0], {"a/model", "b/model"})
        self.assertEqual(len(first[1]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
