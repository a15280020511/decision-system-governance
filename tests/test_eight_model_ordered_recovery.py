from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
import expert_task_envelope as envelope  # noqa: E402


def load_selector():
    spec = importlib.util.spec_from_file_location(
        "eight_model_ordered_recovery_selector",
        COPILOT / "select_expert_team_plan.py",
    )
    assert spec is not None and spec.loader is not None
    selector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector)
    envelope.patch_selector(selector)
    return selector


def ticket() -> dict:
    return {
        "task_id": "eight-model-policy-001",
        "route": "expert-team",
        "task": {
            "question": "Analyze one decision with four active experts.",
            "requirements": [],
            "language": "zh-CN",
        },
        "approved_budget": {
            "calls": 4,
            "maximum_recovery_calls": 0,
            "cost_policy": "prompt_led_soft_governance",
        },
        "private_output": False,
    }


def qualified(model_id: str, rank: int, price: float) -> dict:
    company = model_id.split("/", 1)[0]
    return {
        "model_id": model_id,
        "company": company,
        "official_intelligence_rank": rank,
        "context_length": 131_072,
        "max_completion_tokens": 8_192,
        "prompt_usd_per_million": price / 3,
        "completion_usd_per_million": price * 2 / 3,
        "request_usd": 0.0,
        "price_rank_usd_per_million": price,
        "estimated_task_cost_usd": price,
        "flagship_basis": "explicit-product-tier",
        "exact_endpoint_qualified": True,
        "zdr_endpoint_qualified": True,
        "qualified_provider_count": 2,
        "endpoint_inventory_sha256": hashlib.sha256(
            model_id.encode("utf-8")
        ).hexdigest(),
        "required_context_tokens": 16_384,
        "minimum_completion_tokens": 1_024,
    }


class EightModelOrderedRecoveryTests(unittest.TestCase):
    def test_four_zero_budget_normalizes_to_eight_four(self) -> None:
        normalized = envelope.normalize_recovery_budget(ticket())
        self.assertEqual(normalized["approved_budget"]["calls"], 8)
        self.assertEqual(
            normalized["approved_budget"]["maximum_recovery_calls"],
            4,
        )

    def test_primary_companies_are_distinct_and_recovery_companies_may_repeat(self) -> None:
        selector = load_selector()
        rows = [
            qualified("alpha/alpha-pro", 10, 1.0),
            qualified("beta/beta-pro", 11, 2.0),
            qualified("gamma/gamma-pro", 12, 3.0),
            qualified("delta/delta-pro", 13, 4.0),
            qualified("alpha/alpha-max", 14, 5.0),
            qualified("beta/beta-max", 15, 6.0),
            qualified("epsilon/epsilon-pro", 16, 7.0),
            qualified("alpha/alpha-ultra", 17, 8.0),
        ]
        with mock.patch.object(
            selector,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            plan = selector.build_plan(ticket(), token="fixture")

        selected = plan["selected_models"]
        recovery = plan["recovery_models"]
        self.assertEqual(len(selected), 4)
        self.assertEqual(len(recovery), 4)
        self.assertEqual(
            len({row["company"] for row in selected}),
            4,
        )
        self.assertEqual(
            [row["model"] for row in recovery],
            [
                "alpha/alpha-max",
                "beta/beta-max",
                "epsilon/epsilon-pro",
                "alpha/alpha-ultra",
            ],
        )
        self.assertEqual(
            [row["price_rank_usd_per_million"] for row in recovery],
            [5.0, 6.0, 7.0, 8.0],
        )
        models = [row["model"] for row in selected + recovery]
        self.assertEqual(len(models), 8)
        self.assertEqual(len(set(models)), 8)
        self.assertLess(
            len({row["company"] for row in selected + recovery}),
            8,
        )
        self.assertTrue(plan["recovery_models_are_price_ranked"])
        self.assertTrue(plan["recovery_models_are_sequential"])
        self.assertIn(
            "unique-recovery-models",
            plan["selection_policy"],
        )


if __name__ == "__main__":
    unittest.main()
