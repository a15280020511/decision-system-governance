from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "control-plane" / "governed_expert_roster.py"


def load_module():
    spec = importlib.util.spec_from_file_location("governed_expert_roster_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load governed expert roster module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load_module()


def ticket(*, recovery: int = 1, calls: int = 4):
    return {
        "route": "expert-team",
        "task": {
            "question": "Assess one governed scenario.",
            "requirements": ["Use only supplied evidence."],
            "language": "zh-CN",
        },
        "team_plan": {
            "schema_version": "expert-team-plan-v1",
            "expected_prompt_tokens_per_call": 10_000,
            "expected_completion_tokens_per_call": 2_000,
            "work_items": [
                {
                    "work_id": "analysis",
                    "objective": "Produce the primary assessment.",
                    "role": "primary-analysis",
                    "dependencies": [],
                    "required_outputs": ["findings"],
                },
                {
                    "work_id": "challenge",
                    "objective": "Challenge assumptions and failure modes.",
                    "role": "adversarial-review",
                    "dependencies": [],
                    "required_outputs": ["counterpoints"],
                },
                {
                    "work_id": "synthesis",
                    "objective": "Synthesize the final report.",
                    "role": "final-synthesis",
                    "dependencies": ["analysis", "challenge"],
                    "required_outputs": ["final-report"],
                },
            ],
            "final_work_id": "synthesis",
        },
        "approved_budget": {
            "calls": calls,
            "maximum_recovery_calls": recovery,
            "cost_policy": "prompt_led_soft_governance",
        },
    }


def candidate(model_id: str, company: str, cost: float, score: float):
    return {
        "model_id": model_id,
        "company": company,
        "estimated_task_cost_usd": cost,
        "prompt_usd_per_million": cost * 10,
        "completion_usd_per_million": cost * 20,
        "request_usd": None,
        "balanced_score": score,
        "intelligence_index": score,
        "coding_index": score,
        "agentic_index": score,
    }


def ranking(rows):
    return {
        "schema_version": "governance-openrouter-task-cost-ranking-v1",
        "task_cost_profile": {
            "expected_prompt_tokens": 10_000,
            "expected_completion_tokens": 2_000,
        },
        "ranked_paid_flagship_candidates": rows,
        "source_selector_schema_version": "selector-v1",
        "source_catalog_snapshot_sha256": "a" * 64,
    }


class GovernedExpertRosterTests(unittest.TestCase):
    def rows(self):
        return [
            candidate("openai/a", "openai", 0.0010, 50),
            candidate("openai/b", "openai", 0.0011, 70),
            candidate("deepseek/a", "deepseek", 0.0012, 55),
            candidate("qwen/a", "qwen", 0.0013, 60),
            candidate("anthropic/a", "anthropic", 0.0014, 58),
            candidate("z-ai/a", "z-ai", 0.0015, 57),
        ]

    def test_selects_cheapest_distinct_companies(self):
        result = mod.build_governed_expert_roster(
            ticket(), ranking(self.rows()), governance_commit_sha="b" * 40
        )
        roster = result["governance_roster"]
        primary = roster["primary_members"]
        recovery = roster["recovery_members"]
        self.assertEqual(
            [row["model_id"] for row in primary],
            ["openai/a", "deepseek/a", "qwen/a"],
        )
        self.assertEqual([row["model_id"] for row in recovery], ["anthropic/a"])
        companies = [row["company"] for row in primary + recovery]
        self.assertEqual(len(companies), len(set(companies)))
        self.assertTrue(roster["all_companies_unique"])
        self.assertEqual(roster["model_calls_for_selection"], 0)
        self.assertEqual(roster["selection_cost_usd"], 0)

    def test_assigns_strongest_selected_primary_to_final_synthesis(self):
        result = mod.build_governed_expert_roster(
            ticket(), ranking(self.rows()), governance_commit_sha="b" * 40
        )
        primary = result["governance_roster"]["primary_members"]
        final_member = next(
            row for row in primary if row["assigned_work_id"] == "synthesis"
        )
        self.assertEqual(final_member["model_id"], "qwen/a")
        non_final = [
            row["estimated_task_cost_usd"]
            for row in primary
            if row["assigned_work_id"] != "synthesis"
        ]
        self.assertEqual(non_final, sorted(non_final))

    def test_roster_hash_is_deterministic_and_bound_to_plan(self):
        first = mod.build_governed_expert_roster(
            ticket(), ranking(self.rows()), governance_commit_sha="b" * 40
        )
        second = mod.build_governed_expert_roster(
            ticket(), ranking(self.rows()), governance_commit_sha="b" * 40
        )
        self.assertEqual(
            first["governance_roster"]["roster_sha256"],
            second["governance_roster"]["roster_sha256"],
        )
        changed = ticket()
        changed["team_plan"]["work_items"][0]["objective"] = "Changed objective."
        third = mod.build_governed_expert_roster(
            changed, ranking(self.rows()), governance_commit_sha="b" * 40
        )
        self.assertNotEqual(
            first["governance_roster"]["roster_sha256"],
            third["governance_roster"]["roster_sha256"],
        )

    def test_rejects_duplicate_or_preinjected_roster(self):
        bad = ticket()
        bad["governance_roster"] = {}
        with self.assertRaisesRegex(
            mod.GovernedExpertRosterError, "must not supply governance_roster"
        ):
            mod.build_governed_expert_roster(
                bad, ranking(self.rows()), governance_commit_sha="b" * 40
            )

    def test_rejects_budget_not_equal_to_team_plus_recovery(self):
        with self.assertRaisesRegex(
            mod.GovernedExpertRosterError, "must equal work item count"
        ):
            mod.build_governed_expert_roster(
                ticket(calls=5), ranking(self.rows()), governance_commit_sha="b" * 40
            )

    def test_rejects_dependency_cycle(self):
        bad = ticket()
        bad["team_plan"]["work_items"][0]["dependencies"] = ["synthesis"]
        with self.assertRaisesRegex(mod.GovernedExpertRosterError, "cycle"):
            mod.build_governed_expert_roster(
                bad, ranking(self.rows()), governance_commit_sha="b" * 40
            )

    def test_rejects_work_not_connected_to_final(self):
        bad = ticket()
        bad["team_plan"]["work_items"][-1]["dependencies"] = ["analysis"]
        with self.assertRaisesRegex(
            mod.GovernedExpertRosterError, "disconnected work"
        ):
            mod.build_governed_expert_roster(
                bad, ranking(self.rows()), governance_commit_sha="b" * 40
            )

    def test_rejects_insufficient_distinct_companies(self):
        rows = [
            candidate("a/1", "same", 0.001, 60),
            candidate("a/2", "same", 0.002, 70),
            candidate("b/1", "other", 0.003, 80),
        ]
        with self.assertRaisesRegex(
            mod.GovernedExpertRosterError, "distinct model companies"
        ):
            mod.build_governed_expert_roster(
                ticket(), ranking(rows), governance_commit_sha="b" * 40
            )

    def test_json_round_trip(self):
        result = mod.build_governed_expert_roster(
            ticket(), ranking(self.rows()), governance_commit_sha="b" * 40
        )
        payload = json.loads(json.dumps(result, ensure_ascii=False))
        self.assertEqual(
            payload["governance_roster"]["status"],
            "GOVERNED_EXPERT_ROSTER_READY",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
