from __future__ import annotations

import hashlib
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


def benchmark_payload(scores: dict[str, float]) -> dict[str, object]:
    return {
        "data": [
            {
                "model_permaslug": model_id,
                "intelligence_index": score,
                "coding_index": score,
                "agentic_index": score,
            }
            for model_id, score in scores.items()
        ],
        "meta": {"source": "artificial-analysis", "version": "fixture"},
    }


def candidate(
    model_id: str,
    prompt: float,
    completion: float,
    *,
    rank: int,
    basis: str = "strict-product-tier",
) -> dict[str, object]:
    benchmark_hash = hashlib.sha256(model_id.encode("utf-8")).hexdigest()
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
        "flagship_verified": True,
        "flagship_basis": basis,
        "company_flagship_method": "fixture-natural-top",
        "benchmark_source": "artificial-analysis-via-openrouter",
        "intelligence_index": 50.0,
        "coding_index": 50.0,
        "agentic_index": 50.0,
        "balanced_score": 50.0,
        "benchmark_evidence_sha256": benchmark_hash,
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
    def test_company_natural_top_selects_sol_and_rejects_luna(self) -> None:
        rows = [
            model("openai/gpt-5.6-sol", 5.0, 30.0),
            model("openai/gpt-5.6-terra", 1.0, 6.0),
            model("anthropic/claude-opus-5", 5.0, 25.0),
            model("deepseek/deepseek-v4-pro", 0.435, 0.87),
            model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
        ]
        scores = {
            "openai/gpt-5.6-sol": 95,
            "openai/gpt-5.6-terra": 70,
            "anthropic/claude-opus-5": 92,
            "deepseek/deepseek-v4-pro": 90,
            "openai/gpt-5.6-luna-pro": 60,
        }
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        ids = [row["model_id"] for row in filtered]
        self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
        self.assertNotIn("openai/gpt-5.6-terra", ids)
        self.assertIn("openai/gpt-5.6-sol", ids)
        self.assertEqual(
            ids,
            [
                "deepseek/deepseek-v4-pro",
                "anthropic/claude-opus-5",
                "openai/gpt-5.6-sol",
            ],
        )
        sol = next(row for row in filtered if row["company"] == "openai")
        self.assertEqual(sol["flagship_basis"], "company-local-natural-top-layer")

    def test_singleton_company_requires_strict_product_tier(self) -> None:
        rows = [
            model("singleton/frontier-reasoner", 0.1, 0.2),
            model("strict/reasoning-max", 0.2, 0.4),
        ]
        scores = {
            "singleton/frontier-reasoner": 90,
            "strict/reasoning-max": 90,
        }
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["strict/reasoning-max"],
        )

    def test_luna_pro_is_rejected_even_without_another_openai_model(self) -> None:
        rows = [
            model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
            model("other/reasoning-max", 0.2, 0.4),
            model("third/reasoning-pro", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertNotIn(
            "openai/gpt-5.6-luna-pro",
            [row["model_id"] for row in filtered],
        )
    def test_non_reasoning_pro_model_is_rejected(self) -> None:
        rows = [
            model("vendor/cheap-pro", 0.01, 0.02, reasoning=False),
            model("other/reasoning-max", 0.2, 0.4),
            model("third/reasoning-pro", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertNotIn(
            "vendor/cheap-pro",
            [row["model_id"] for row in filtered],
        )
    def test_economy_and_specialized_models_are_rejected(self) -> None:
        rows = [
            model("vendor/mini-pro", 0.01, 0.01),
            model("other/coder-max", 0.01, 0.01),
            model("perplexity/sonar-pro-search", 3.0, 15.0),
            model("google/gemini-2.5-pro", 1.25, 10.0),
            model("third/general-max", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["third/general-max", "google/gemini-2.5-pro"],
        )

    def test_live_catalog_fetches_reasoning_models_and_benchmarks(self) -> None:
        observed: list[str] = []
        rows = [
            model("vendor/reasoning-pro", 0.2, 0.4),
            model("other/reasoning-max", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}

        def fake_fetch(url: str, token: str):
            del token
            observed.append(url)
            if "/benchmarks?" in url:
                return benchmark_payload(scores)
            return {"data": rows}

        with mock.patch.object(planner, "_fetch_json", side_effect=fake_fetch):
            planner._live_flagship_rows("fixture")
        model_query = parse_qs(urlparse(observed[0]).query)
        benchmark_query = parse_qs(urlparse(observed[1]).query)
        self.assertEqual(model_query["sort"], ["intelligence-high-to-low"])
        self.assertEqual(model_query["supported_parameters"], ["reasoning"])
        self.assertEqual(benchmark_query["source"], ["artificial-analysis"])

    def test_endpoint_inventory_requires_real_native_capacity(self) -> None:
        row = candidate("vendor/reasoning-pro", 0.2, 0.4, rank=7)
        payload = {
            "data": {
                "endpoints": [
                    endpoint("too-small", max_completion_tokens=512),
                    endpoint("short-context", context_length=4_096),
                    endpoint("usable", context_length=32_768, max_completion_tokens=4_096),
                ]
            }
        }
        compatible = planner._compatible_endpoint_inventory(row, payload, 10_000)
        self.assertEqual([item["provider"] for item in compatible], ["usable"])

    def test_plan_keeps_price_order_and_company_uniqueness(self) -> None:
        rows = [
            candidate("deepseek/deepseek-v4-pro", 0.2, 0.3, rank=5),
            candidate("nex-agi/nex-n2-pro", 0.3, 0.4, rank=9),
            candidate("minimax/minimax-m3", 0.4, 0.5, rank=15, basis="company-local-natural-top-layer"),
            candidate("xiaomi/mimo-v2.5-pro", 0.5, 0.6, rank=20),
        ]
        with mock.patch.object(
            planner,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            plan = planner.build_plan(ticket(), token="fixture")
        all_rows = [*plan["selected_models"], *plan["recovery_models"]]
        self.assertEqual(len({row["company"] for row in all_rows}), len(all_rows))
        self.assertIn("reasoning-parameter-required", plan["selection_policy"])
        self.assertIn("artificial-analysis-complete-benchmarks-required", plan["selection_policy"])
        self.assertIn("strict-product-tier-or-company-natural-top-layer", plan["selection_policy"])
        self.assertEqual(
            plan["company_model_policy"],
            "one-highest-intelligence-verified-reasoning-flagship-per-company-then-price-rank",
        )
        self.assertEqual(
            plan["flagship_definition"],
            "strict-product-tier-or-benchmarked-company-natural-top-layer",
        )
        self.assertTrue(plan["reasoning_model_required"])
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

    def test_selector_uses_live_benchmarks_without_task_specific_reranking(self) -> None:
        source = (COPILOT / "select_expert_team_plan.py").read_text(encoding="utf-8")
        self.assertIn("BENCHMARKS_API", source)
        self.assertIn("select_from_catalog", source)
        self.assertIn("balanced_score", source)
        self.assertNotIn("rank_flagships_by_task_cost", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
