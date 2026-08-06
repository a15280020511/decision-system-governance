from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
SPEC = importlib.util.spec_from_file_location(
    "simple_expert_plan_test", COPILOT / "select_expert_team_plan.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load expert plan selector")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def per_token(usd_per_million: float) -> str:
    return f"{usd_per_million / 1_000_000:.12f}"


def model(
    model_id: str,
    prompt: float,
    completion: float,
    *,
    name: str | None = None,
) -> dict[str, object]:
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": name or model_id,
        "pricing": {
            "prompt": per_token(prompt),
            "completion": per_token(completion),
        },
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    }


def candidate(
    model_id: str,
    prompt: float,
    completion: float,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "company": model_id.split("/", 1)[0],
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": 0.0,
        "price_rank_usd_per_million": prompt + completion,
        "estimated_task_cost_usd": prompt + completion,
        "flagship_basis": "explicit-product-tier",
    }


def ticket() -> dict[str, object]:
    return {
        "route": "expert-team",
        "task": {
            "question": "Select the cheapest flagship experts.",
            "requirements": [],
            "language": "zh-CN",
        },
        "approved_budget": {
            "calls": 4,
            "maximum_recovery_calls": 1,
            "cost_policy": "prompt_led_soft_governance",
        },
        "private_output": False,
    }


class SimpleFlagshipPriceSelectionTests(unittest.TestCase):
    def test_catalog_is_filtered_then_sorted_only_by_price(self) -> None:
        payload = {
            "data": [
                model("openai/gpt-5.6-luna", 0.01, 0.02),
                model("vendor/expensive-pro", 4.0, 8.0),
                model("vendor/cheap-pro", 0.2, 0.4),
                model("vendor/mini-pro", 0.01, 0.01),
                model("vendor/coder-pro", 0.01, 0.01),
                model("vendor/mid-max", 0.5, 0.5),
            ]
        }

        rows = planner._catalog_candidates(payload)
        ids = [row["model_id"] for row in rows]

        self.assertNotIn("openai/gpt-5.6-luna", ids)
        self.assertNotIn("vendor/mini-pro", ids)
        self.assertNotIn("vendor/coder-pro", ids)
        self.assertEqual(
            ids,
            ["vendor/cheap-pro", "vendor/mid-max", "vendor/expensive-pro"],
        )
        prices = [row["price_rank_usd_per_million"] for row in rows]
        self.assertEqual(prices, sorted(prices))

    def test_plan_takes_cheapest_models_from_different_companies(self) -> None:
        rows = [
            candidate("openai/gpt-5-pro", 0.1, 0.2),
            candidate("openai/gpt-6-pro", 0.11, 0.21),
            candidate("deepseek/deepseek-v4-pro", 0.2, 0.3),
            candidate("nex-agi/nex-n2-pro", 0.3, 0.4),
            candidate("anthropic/claude-opus", 0.4, 0.5),
        ]

        with mock.patch.object(planner, "_live_flagship_rows", return_value=rows):
            plan = planner.build_plan(ticket(), token="fixture")

        selected = [row["model"] for row in plan["selected_models"]]
        recovery = [row["model"] for row in plan["recovery_models"]]
        self.assertEqual(
            selected,
            [
                "openai/gpt-5-pro",
                "deepseek/deepseek-v4-pro",
                "nex-agi/nex-n2-pro",
            ],
        )
        self.assertEqual(recovery, ["anthropic/claude-opus"])
        self.assertEqual(
            plan["selection_policy"],
            "openrouter-paid-general-purpose-flagships "
            "-> combined-token-price-ascending -> distinct-model-companies",
        )
        self.assertEqual(
            plan["price_rank_basis"],
            "prompt_usd_per_million + completion_usd_per_million",
        )
        self.assertNotIn("task_cost_profile", plan)
        self.assertEqual(plan["model_calls"], 0)

    def test_missing_distinct_flagship_companies_fails_closed(self) -> None:
        rows = [
            candidate("vendor/a-pro", 0.1, 0.2),
            candidate("vendor/b-max", 0.2, 0.3),
            candidate("vendor/c-opus", 0.3, 0.4),
        ]
        with mock.patch.object(planner, "_live_flagship_rows", return_value=rows):
            with self.assertRaisesRegex(
                planner.ExpertPlanError,
                "not enough distinct-company flagship models",
            ):
                planner.build_plan(ticket(), token="fixture")

    def test_expert_selector_has_no_benchmark_or_capability_ranking_dependency(self) -> None:
        source = (
            COPILOT / "select_expert_team_plan.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("BENCHMARKS_API", source)
        self.assertNotIn("rank_flagships_by_task_cost", source)
        self.assertNotIn("balanced_score", source)
        self.assertNotIn("natural_high", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
