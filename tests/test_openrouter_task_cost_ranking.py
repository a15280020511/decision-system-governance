from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "governance-copilot" / "rank_flagships_by_task_cost.py"


def load_module():
    spec = importlib.util.spec_from_file_location("task_cost_ranker", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load task cost ranker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ranker = load_module()


def candidate(
    model_id: str,
    prompt: float,
    completion: float,
    *,
    request: float | None = None,
    score: float = 50,
):
    return {
        "model_id": model_id,
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": request,
        "balanced_score": score,
    }


def receipt(rows):
    return {
        "schema_version": "fixture-selector-v1",
        "cheapest_paid_flagship_candidates": rows,
    }


class TaskCostRankingTests(unittest.TestCase):
    def test_lower_actual_cost_wins_even_when_catalog_order_differs(self):
        payload = receipt(
            [
                candidate("nex-agi/nex-n2-pro", 0.25, 1.0),
                candidate("openai/gpt-5.6-luna", 0.10, 0.60),
            ]
        )
        result = ranker.rank_flagships_by_task_cost(payload)
        self.assertEqual(
            result["selected_model"]["model_id"], "openai/gpt-5.6-luna"
        )
        self.assertAlmostEqual(
            result["selected_model"]["estimated_task_cost_usd"], 0.0022
        )

    def test_request_fee_is_included(self):
        payload = receipt(
            [
                candidate("vendor/cheap-token-pro", 0.01, 0.01, request=0.10),
                candidate("vendor/no-request-pro", 1.0, 1.0),
            ]
        )
        result = ranker.rank_flagships_by_task_cost(
            payload, expected_prompt_tokens=1_000, expected_completion_tokens=1_000
        )
        self.assertEqual(
            result["selected_model"]["model_id"], "vendor/no-request-pro"
        )

    def test_task_profile_can_change_winner(self):
        payload = receipt(
            [
                candidate("vendor/input-cheap-pro", 0.01, 10.0),
                candidate("vendor/output-cheap-pro", 1.0, 0.01),
            ]
        )
        input_heavy = ranker.rank_flagships_by_task_cost(
            payload, expected_prompt_tokens=100_000, expected_completion_tokens=100
        )
        output_heavy = ranker.rank_flagships_by_task_cost(
            payload, expected_prompt_tokens=100, expected_completion_tokens=100_000
        )
        self.assertEqual(
            input_heavy["selected_model"]["model_id"],
            "vendor/input-cheap-pro",
        )
        self.assertEqual(
            output_heavy["selected_model"]["model_id"],
            "vendor/output-cheap-pro",
        )

    def test_tie_break_is_deterministic(self):
        payload = receipt(
            [
                candidate("vendor/b-pro", 1.0, 1.0, score=50),
                candidate("vendor/a-pro", 1.0, 1.0, score=60),
            ]
        )
        outputs = [ranker.rank_flagships_by_task_cost(payload) for _ in range(20)]
        self.assertEqual(
            {row["selected_model"]["model_id"] for row in outputs},
            {"vendor/a-pro"},
        )

    def test_duplicate_model_fails_closed(self):
        payload = receipt(
            [
                candidate("vendor/pro", 1.0, 1.0),
                candidate("vendor/pro", 2.0, 2.0),
            ]
        )
        with self.assertRaises(ranker.CostRankingError):
            ranker.rank_flagships_by_task_cost(payload)

    def test_invalid_price_or_zero_task_fails_closed(self):
        with self.assertRaises(ranker.CostRankingError):
            ranker.rank_flagships_by_task_cost(
                receipt([candidate("vendor/pro", float("nan"), 1.0)])
            )
        with self.assertRaises(ranker.CostRankingError):
            ranker.rank_flagships_by_task_cost(
                receipt([candidate("vendor/pro", 1.0, 1.0)]),
                expected_prompt_tokens=0,
                expected_completion_tokens=0,
            )

    def test_receipt_contains_profile_and_no_secret(self):
        result = ranker.rank_flagships_by_task_cost(
            receipt([candidate("vendor/pro", 1.0, 1.0)]),
            expected_prompt_tokens=12_345,
            expected_completion_tokens=678,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ranker.write_receipts(result, Path(tmp))
            saved = json.loads(
                (Path(tmp) / "cost-selection.json").read_text("utf-8")
            )
        self.assertEqual(
            saved["task_cost_profile"],
            {
                "expected_prompt_tokens": 12_345,
                "expected_completion_tokens": 678,
            },
        )
        self.assertEqual(saved["model_calls"], 0)
        self.assertFalse(saved["secret_values_exposed"])
        self.assertNotIn("OPENROUTER_API_KEY", json.dumps(saved))


if __name__ == "__main__":
    unittest.main(verbosity=2)
