from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))

spec = importlib.util.spec_from_file_location(
    "select_expert_team_models",
    COPILOT / "select_expert_team_models.py",
)
selector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(selector)


class GovernanceExpertSelectionTests(unittest.TestCase):
    def _ticket(self) -> dict:
        return {
            "route": "expert-team",
            "task": {
                "question": "比较三个城市公共投资方案并给出风险排序。",
                "requirements": ["区分事实、假设和推断", "给出可执行建议"],
                "language": "zh-CN",
            },
            "approved_budget": {
                "calls": 8,
                "maximum_recovery_calls": 1,
                "cost_policy": "prompt_led_soft_governance",
            },
        }

    def _receipt(self) -> dict:
        rows = []
        for index, company in enumerate(
            ("vendor-a", "vendor-b", "vendor-c", "vendor-d", "vendor-e"),
            1,
        ):
            rows.append(
                {
                    "model_id": f"{company}/flagship-{index}",
                    "prompt_usd_per_million": float(index),
                    "completion_usd_per_million": float(index * 2),
                    "request_usd": 0.0,
                    "balanced_score": float(100 - index),
                    "intelligence_index": float(100 - index),
                    "coding_index": float(90 - index),
                    "agentic_index": float(80 - index),
                }
            )
        return {
            "schema_version": "governance-openrouter-paid-governance-flagship-v1",
            "cheapest_paid_flagship_candidates": rows,
        }

    @staticmethod
    def _endpoint(candidate, **kwargs):
        model = candidate["model_id"]
        company = model.split("/", 1)[0]
        provider = f"provider-{company}"
        return {
            "model": model,
            "company": company,
            "official_intelligence_rank": kwargs["intelligence_rank"],
            "provider": provider,
            "provider_endpoint": f"{model}@{provider}",
            "context_length": 131072,
            "max_completion_tokens": 8192,
            "prompt_price_per_million": candidate["prompt_usd_per_million"],
            "completion_price_per_million": candidate[
                "completion_usd_per_million"
            ],
            "supported_parameters": ["reasoning"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "local_token_ceiling_parameter_required": False,
            "native_completion_capacity_checked": True,
            "synthetic_fixture_only": False,
            "estimated_call_cost_usd": float(
                candidate["prompt_usd_per_million"]
            ),
        }

    def test_governance_builds_complete_bound_plan(self) -> None:
        with mock.patch.object(selector, "_exact_endpoint", self._endpoint):
            plan = selector.build_selection_plan(
                self._ticket(),
                self._receipt(),
                source_commit="a" * 40,
            )
        self.assertEqual("PASS", plan["status"])
        self.assertEqual(
            "decision-system-governance", plan["selection_authority"]
        )
        self.assertEqual(4, plan["selected_expert_count"])
        self.assertEqual(4, len(plan["selected_models"]))
        self.assertEqual(1, len(plan["recovery_models"]))
        companies = {
            row["model"].split("/", 1)[0]
            for row in [*plan["selected_models"], *plan["recovery_models"]]
        }
        self.assertEqual(5, len(companies))
        self.assertFalse(plan["expert_center_selection_allowed"])
        self.assertFalse(plan["expert_center_catalog_fetch_allowed"])
        self.assertFalse(plan["local_fallback_allowed"])
        material = dict(plan)
        observed = material.pop("plan_sha256")
        self.assertEqual(selector._sha256(material), observed)

    def test_budget_below_three_initial_experts_fails_closed(self) -> None:
        ticket = self._ticket()
        ticket["approved_budget"] = {
            "calls": 4,
            "maximum_recovery_calls": 2,
            "cost_policy": "prompt_led_soft_governance",
        }
        with self.assertRaises(selector.ExpertModelSelectionError):
            selector.build_selection_plan(ticket, self._receipt())


if __name__ == "__main__":
    unittest.main()
