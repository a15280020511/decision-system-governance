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

    def test_primary_excludes_governance_vendors_and_recovery_may_use_them(self) -> None:
        selector = load_selector()
        rows = [
            qualified("deepseek/deepseek-v4-pro", 23, 1.305),
            qualified("xiaomi/mimo-v2.5-pro", 25, 1.305),
            qualified("amazon/nova-pro-v1", 129, 4.0),
            qualified("nvidia/nemotron-3-ultra", 38, 4.2),
            qualified("google/gemini-2.5-pro", 63, 11.25),
            qualified("anthropic/claude-opus-5", 1, 30.0),
            qualified("anthropic/claude-opus-4.8", 5, 30.0),
            qualified("anthropic/claude-opus-4.7", 9, 30.0),
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
        self.assertEqual(len({row["company"] for row in selected}), 4)
        self.assertFalse(
            {"openai", "anthropic"}
            & {row["company"] for row in selected}
        )
        self.assertEqual(
            [row["model"] for row in recovery],
            [
                "google/gemini-2.5-pro",
                "anthropic/claude-opus-5",
                "anthropic/claude-opus-4.8",
                "anthropic/claude-opus-4.7",
            ],
        )
        self.assertEqual(
            [row["price_rank_usd_per_million"] for row in recovery],
            [11.25, 30.0, 30.0, 30.0],
        )
        models = [row["model"] for row in selected + recovery]
        self.assertEqual(len(models), 8)
        self.assertEqual(len(set(models)), 8)
        self.assertEqual(
            plan["governance_companies_excluded_from_primary"],
            ["anthropic", "openai"],
        )
        self.assertTrue(plan["governance_companies_allowed_in_recovery"])
        self.assertTrue(plan["recovery_models_are_price_ranked"])
        self.assertTrue(plan["recovery_models_are_sequential"])
        self.assertIn(
            "primary-excludes-governance-vendors",
            plan["selection_policy"],
        )
        self.assertIn(
            "unique-recovery-models",
            plan["selection_policy"],
        )


if __name__ == "__main__":
    unittest.main()
