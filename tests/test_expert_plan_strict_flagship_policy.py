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
    context_length: int = 131_072,
    max_completion_tokens: int = 8_192,
) -> dict[str, object]:
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": name or model_id,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
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
        "flagship_basis": "explicit-product-tier",
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
            "question": "Select the cheapest executable flagship experts.",
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
    prompt: float = 0.2,
    completion: float = 0.4,
) -> dict[str, object]:
    return {
        "tag": provider,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
        "pricing": {
            "prompt": per_token(prompt),
            "completion": per_token(completion),
        },
    }


class ExecutableFlagshipPriceSelectionTests(unittest.TestCase):
    def test_catalog_uses_official_top_150_and_excludes_governance_companies(self) -> None:
        rows = [
            model("openai/gpt-5-pro", 0.01, 0.02),
            model("anthropic/claude-opus", 0.02, 0.03),
            model("vendor/expensive-pro", 4.0, 8.0),
            model("vendor/cheap-pro", 0.2, 0.4),
            model("vendor/mini-pro", 0.01, 0.01),
            model("vendor/coder-pro", 0.01, 0.01),
            model("other/mid-max", 0.5, 0.5),
        ]
        rows.extend(
            model(f"filler/model-{index}", 9.0, 9.0)
            for index in range(7, 150)
        )
        rows.append(model("late/too-late-pro", 0.01, 0.01))

        filtered = planner._catalog_candidates({"data": rows})
        ids = [row["model_id"] for row in filtered]

        self.assertNotIn("openai/gpt-5-pro", ids)
        self.assertNotIn("anthropic/claude-opus", ids)
        self.assertNotIn("vendor/mini-pro", ids)
        self.assertNotIn("vendor/coder-pro", ids)
        self.assertNotIn("late/too-late-pro", ids)
        self.assertEqual(
            ids,
            ["vendor/cheap-pro", "other/mid-max", "vendor/expensive-pro"],
        )
        prices = [row["price_rank_usd_per_million"] for row in filtered]
        self.assertEqual(prices, sorted(prices))

    def test_endpoint_inventory_requires_real_native_capacity(self) -> None:
        row = candidate("vendor/cheap-pro", 0.2, 0.4, rank=7)
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
        self.assertEqual(
            compatible[0]["provider_endpoint"],
            "vendor/cheap-pro@usable",
        )

    def test_live_qualification_skips_unexecutable_cheaper_model(self) -> None:
        rows = [
            candidate("vendor/cheap-pro", 0.1, 0.2, rank=1),
            candidate("other/mid-pro", 0.2, 0.3, rank=2),
            candidate("third/usable-pro", 0.3, 0.4, rank=3),
        ]
        for row in rows:
            row["exact_endpoint_qualified"] = False

        def fake_fetch(url: str, token: str):
            del token
            if "vendor/cheap-pro" in url:
                return {"data": {"endpoints": [endpoint("tiny", max_completion_tokens=128)]}}
            return {"data": {"endpoints": [endpoint("provider-a")]}}

        with (
            mock.patch.object(planner, "_live_flagship_rows", return_value=rows),
            mock.patch.object(planner, "_fetch_json", side_effect=fake_fetch),
        ):
            qualified = planner._live_executable_flagship_rows(
                ticket(), "fixture", 2
            )

        self.assertEqual(
            [row["model_id"] for row in qualified],
            ["other/mid-pro", "third/usable-pro"],
        )
        self.assertTrue(all(row["exact_endpoint_qualified"] for row in qualified))

    def test_plan_takes_cheapest_executable_models_from_different_companies(self) -> None:
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

        selected = [row["model"] for row in plan["selected_models"]]
        recovery = [row["model"] for row in plan["recovery_models"]]
        self.assertEqual(
            selected,
            [
                "deepseek/deepseek-v4-pro",
                "nex-agi/nex-n2-pro",
                "upstage/solar-pro-3",
            ],
        )
        self.assertEqual(recovery, ["xiaomi/mimo-v2.5-pro"])
        self.assertTrue(plan["endpoint_qualification_performed_by_governance"])
        self.assertEqual(plan["governance_companies_excluded"], ["anthropic", "openai"])
        self.assertIn("live-exact-endpoint-qualified", plan["selection_policy"])
        self.assertEqual(
            plan["price_rank_basis"],
            "prompt_usd_per_million + completion_usd_per_million",
        )
        self.assertNotIn("task_cost_profile", plan)
        self.assertEqual(plan["model_calls"], 0)

    def test_missing_distinct_executable_companies_fails_closed(self) -> None:
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

    def test_unqualified_model_cannot_enter_plan(self) -> None:
        row = candidate("vendor/a-pro", 0.1, 0.2, rank=1)
        row["exact_endpoint_qualified"] = False
        with self.assertRaisesRegex(
            planner.ExpertPlanError,
            "no executable endpoint qualification",
        ):
            planner._finite_cost(row)

    def test_selector_has_no_benchmark_or_capability_ranking_dependency(self) -> None:
        source = (
            COPILOT / "select_expert_team_plan.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("BENCHMARKS_API", source)
        self.assertNotIn("rank_flagships_by_task_cost", source)
        self.assertNotIn("balanced_score", source)
        self.assertNotIn("natural_high", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
