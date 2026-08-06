from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
SPEC = importlib.util.spec_from_file_location(
    "reasoning_expert_plan_test",
    COPILOT / "select_expert_team_plan.py",
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
    reasoning: bool = True,
    context_length: int = 131_072,
    max_completion_tokens: int = 8_192,
) -> dict[str, object]:
    parameters = ["max_tokens"]
    if reasoning:
        parameters.append("reasoning")
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": model_id,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
        "supported_parameters": parameters,
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
    *,
    rank: int,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "company": model_id.split("/", 1)[0],
        "official_intelligence_rank": rank,
        "context_length": 131_072,
        "max_completion_tokens": 8_192,
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": 0.0,
        "price_rank_usd_per_million": prompt + completion,
        "estimated_task_cost_usd": prompt + completion,
        "flagship_basis": (
            "company-highest-intelligence-stable-paid-general-reasoning-model"
        ),
        "reasoning_parameter_required": True,
        "exact_endpoint_qualified": True,
        "qualified_provider_count": 1,
        "endpoint_inventory_sha256": f"{'a' * 63}{rank % 10}",
        "required_context_tokens": 9_000,
        "minimum_completion_tokens": 1_024,
    }


def ticket() -> dict[str, object]:
    return {
        "route": "expert-team",
        "task": {
            "question": "Select reasoning flagships in price order.",
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


def endpoint(
    provider: str,
    *,
    context_length: int = 131_072,
    max_completion_tokens: int = 8_192,
) -> dict[str, object]:
    return {
        "tag": provider,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
        "pricing": {
            "prompt": per_token(0.2),
            "completion": per_token(0.4),
        },
    }


class ReasoningFlagshipPriceSelectionTests(unittest.TestCase):
    def test_company_strongest_reasoning_model_wins_before_price_sort(self) -> None:
        rows = [
            model("openai/gpt-5", 1.0, 4.0),
            model("anthropic/claude-opus", 2.0, 5.0),
            model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
            model("deepseek/deepseek-v4-pro", 0.4, 0.9),
        ]
        filtered = planner._catalog_candidates({"data": rows})
        ids = [row["model_id"] for row in filtered]
        self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
        self.assertIn("openai/gpt-5", ids)
        self.assertEqual(
            ids,
            [
                "deepseek/deepseek-v4-pro",
                "openai/gpt-5",
                "anthropic/claude-opus",
            ],
        )
        self.assertEqual(
            [row["price_rank_usd_per_million"] for row in filtered],
            sorted(row["price_rank_usd_per_million"] for row in filtered),
        )

    def test_non_reasoning_pro_model_is_rejected(self) -> None:
        rows = [
            model("vendor/cheap-pro", 0.01, 0.02, reasoning=False),
            model("other/reasoning-max", 0.2, 0.4),
        ]
        filtered = planner._catalog_candidates({"data": rows})
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["other/reasoning-max"],
        )

    def test_economy_and_specialized_reasoning_models_are_rejected(self) -> None:
        rows = [
            model("vendor/mini-pro", 0.01, 0.01),
            model("other/coder-max", 0.01, 0.01),
            model("third/general-reasoner", 0.3, 0.5),
        ]
        filtered = planner._catalog_candidates({"data": rows})
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["third/general-reasoner"],
        )

    def test_live_catalog_request_requires_reasoning_parameter(self) -> None:
        observed: list[str] = []

        def fake_fetch(url: str, token: str):
            del token
            observed.append(url)
            return {
                "data": [model("vendor/reasoning-pro", 0.2, 0.4)]
            }

        with mock.patch.object(planner, "_fetch_json", side_effect=fake_fetch):
            planner._live_flagship_rows("fixture")
        query = parse_qs(urlparse(observed[0]).query)
        self.assertEqual(query["sort"], ["intelligence-high-to-low"])
        self.assertEqual(query["output_modalities"], ["text"])
        self.assertEqual(query["supported_parameters"], ["reasoning"])

    def test_endpoint_inventory_requires_real_native_capacity(self) -> None:
        row = candidate("vendor/reasoning-pro", 0.2, 0.4, rank=7)
        payload = {
            "data": {
                "endpoints": [
                    endpoint("too-small", max_completion_tokens=512),
                    endpoint("short-context", context_length=4_096),
                    endpoint(
                        "usable",
                        context_length=32_768,
                        max_completion_tokens=4_096,
                    ),
                ]
            }
        }
        compatible = planner._compatible_endpoint_inventory(
            row,
            payload,
            10_000,
        )
        self.assertEqual(
            [item["provider"] for item in compatible],
            ["usable"],
        )

    def test_plan_keeps_price_order_and_company_uniqueness(self) -> None:
        rows = [
            candidate("deepseek/deepseek-v4-pro", 0.2, 0.3, rank=5),
            candidate("nex-agi/nex-n2-pro", 0.3, 0.4, rank=9),
            candidate("upstage/solar-pro-3", 0.4, 0.5, rank=15),
            candidate("xiaomi/mimo-v2.5-pro", 0.5, 0.6, rank=20),
        ]
        with mock.patch.object(
            planner,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            plan = planner.build_plan(ticket(), token="fixture")
        all_rows = [
            *plan["selected_models"],
            *plan["recovery_models"],
        ]
        self.assertEqual(
            len({row["company"] for row in all_rows}),
            len(all_rows),
        )
        self.assertIn(
            "reasoning-parameter-required",
            plan["selection_policy"],
        )
        self.assertIn(
            "highest-intelligence-model-per-company-as-flagship",
            plan["selection_policy"],
        )
        self.assertEqual(
            plan["company_model_policy"],
            "one-highest-intelligence-reasoning-flagship-per-company-then-price-rank",
        )
        self.assertEqual(
            plan["price_rank_basis"],
            "prompt_usd_per_million + completion_usd_per_million",
        )
        self.assertEqual(plan["model_calls"], 0)

    def test_missing_distinct_companies_fails_closed(self) -> None:
        rows = [
            candidate("vendor/a-pro", 0.1, 0.2, rank=1),
            candidate("vendor/b-max", 0.2, 0.3, rank=2),
            candidate("vendor/c-opus", 0.3, 0.4, rank=3),
        ]
        with mock.patch.object(
            planner,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(
                planner.ExpertPlanError,
                "not enough distinct-company executable flagship models",
            ):
                planner.build_plan(ticket(), token="fixture")

    def test_selector_has_no_benchmark_or_local_task_ranking_dependency(self) -> None:
        source = (
            COPILOT / "select_expert_team_plan.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("BENCHMARKS_API", source)
        self.assertNotIn("rank_flagships_by_task_cost", source)
        self.assertNotIn("balanced_score", source)
        self.assertNotIn("natural_high", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
