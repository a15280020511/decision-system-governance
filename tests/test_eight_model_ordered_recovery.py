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
        "task_id": "eight-company-policy-001",
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


def qualified(model_id: str, rank: int, price: float, providers: int = 1) -> dict:
    return {
        "model_id": model_id,
        "company": model_id.split("/", 1)[0],
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
        "qualified_provider_count": providers,
        "endpoint_inventory_sha256": hashlib.sha256(model_id.encode()).hexdigest(),
        "required_context_tokens": 16_384,
        "minimum_completion_tokens": 1_024,
    }


class EightCompanyOrderedRecoveryTests(unittest.TestCase):
    def test_four_zero_budget_normalizes_to_eight_four(self) -> None:
        normalized = envelope.normalize_recovery_budget(ticket())
        self.assertEqual(normalized["approved_budget"]["calls"], 8)
        self.assertEqual(normalized["approved_budget"]["maximum_recovery_calls"], 4)

    def test_live_price_ranking_contains_one_model_per_company(self) -> None:
        selector = load_selector()
        rows = [
            qualified("openai/gpt-5.6-luna-pro", 251, 0.7, 2),
            qualified("nex-agi/nex-n2-pro", 28, 1.25),
            qualified("deepseek/deepseek-v4-pro", 23, 1.305, 8),
            qualified("xiaomi/mimo-v2.5-pro", 25, 1.305, 2),
            qualified("amazon/nova-pro-v1", 129, 4.0, 2),
            qualified("nvidia/nemotron-3-ultra", 38, 4.2, 3),
            qualified("google/gemini-2.5-pro", 63, 11.25, 5),
            qualified("perplexity/sonar-pro", 274, 18.0),
            qualified("anthropic/claude-opus-5", 1, 30.0, 5),
        ]
        with mock.patch.object(
            selector, "_live_executable_flagship_rows", return_value=rows
        ):
            plan = selector.build_plan(ticket(), token="fixture")

        ranked = plan["price_ranked_models"]
        self.assertEqual([row["price_rank"] for row in ranked], list(range(1, 9)))
        self.assertEqual(
            [row["model"] for row in ranked],
            [
                "openai/gpt-5.6-luna-pro",
                "nex-agi/nex-n2-pro",
                "deepseek/deepseek-v4-pro",
                "xiaomi/mimo-v2.5-pro",
                "amazon/nova-pro-v1",
                "nvidia/nemotron-3-ultra",
                "google/gemini-2.5-pro",
                "perplexity/sonar-pro",
            ],
        )
        companies = [row["company"] for row in ranked]
        self.assertEqual(len(companies), len(set(companies)))
        prices = [row["price_rank_usd_per_million"] for row in ranked]
        self.assertEqual(prices, sorted(prices))
        selected_companies = {row["company"] for row in plan["selected_models"]}
        recovery_companies = {row["company"] for row in plan["recovery_models"]}
        self.assertFalse(selected_companies & recovery_companies)
        self.assertEqual(plan["company_uniqueness_scope"], "selected-and-recovery")
        self.assertEqual(
            plan["catalog_fetch_mode"], "live-per-task-no-cross-task-cache"
        )
        self.assertEqual(plan["minimum_qualified_provider_count"], 1)


if __name__ == "__main__":
    unittest.main()
