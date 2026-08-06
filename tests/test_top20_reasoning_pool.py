from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "governance-copilot" / "top20_reasoning_pool.py"
    spec = importlib.util.spec_from_file_location("top20_reasoning_pool_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    index: int,
    *,
    reasoning: bool = True,
    company: str | None = None,
) -> dict:
    parameters = ["max_tokens", "reasoning"] if reasoning else ["max_tokens"]
    owner = company or f"company{index}"
    return {
        "id": f"{owner}/model-{index}",
        "name": f"Model {index}",
        "canonical_slug": f"{owner}/model-{index}",
        "context_length": 32768,
        "supported_parameters": parameters,
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        "top_provider": {"max_completion_tokens": 4096},
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "expiration_date": None,
    }


def _pool_row(index: int, company: str | None = None) -> dict:
    owner = company or f"company{index}"
    return {
        "popularity_rank": index,
        "source_rank": index,
        "model": f"{owner}/model-{index}",
        "company": owner,
        "name": f"Model {index}",
        "canonical_slug": f"{owner}/model-{index}",
        "context_length": 32768,
        "max_completion_tokens": 4096,
        "prompt_usd_per_million": 1.0,
        "completion_usd_per_million": 2.0,
        "request_usd": 0.0,
        "expiration_date": None,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "supported_parameters": ["reasoning"],
        "reasoning_supported": True,
        "pool_source": "openrouter-most-popular-last-week-token-volume",
    }


class Top20ReasoningPoolTests(unittest.TestCase):
    def test_raw_pool_keeps_first_twenty_reasoning_rows_in_server_order(self) -> None:
        module = _load_module()
        rows = [_row(0, reasoning=False)] + [
            _row(index) for index in range(1, 23)
        ]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                assert "sort=most-popular" in url
                assert "supported_parameters=reasoning" in url
                assert token == "token"
                return {"data": rows}

        pool, payload = module._raw_pool_rows(FakeSelector, "token")
        self.assertEqual(payload, {"data": rows})
        self.assertEqual(len(pool), 20)
        self.assertEqual(
            [row["popularity_rank"] for row in pool], list(range(1, 21))
        )
        self.assertEqual(
            [row["model"] for row in pool],
            [f"company{index}/model-{index}" for index in range(1, 21)],
        )
        self.assertTrue(all(row["reasoning_supported"] is True for row in pool))
        self.assertTrue(all(row["pool_source"] == module.POOL_SOURCE for row in pool))

    def test_eligible_pool_uses_top20_rows_directly_and_keeps_same_company_models(self) -> None:
        module = _load_module()
        raw = [
            _pool_row(1, "shared"),
            _pool_row(2, "shared"),
            *[_pool_row(index) for index in range(3, 11)],
        ]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                assert "intelligence-high-to-low" in url
                return {"data": [{"id": row["model"]} for row in raw]}

            @staticmethod
            def _required_context_tokens(ticket):
                return 9000

            @staticmethod
            def _qualify_candidate(candidate, token, required_context):
                assert "flagship_basis" not in candidate
                assert "benchmark_evidence_sha256" not in candidate
                assert required_context == 9000
                return {
                    **candidate,
                    "qualified_provider_count": 1,
                    "endpoint_inventory_sha256": "a" * 64,
                    "required_context_tokens": required_context,
                    "minimum_completion_tokens": 1024,
                }

            @staticmethod
            def _catalog_candidates(*args, **kwargs):
                raise AssertionError("old flagship catalog must not be called")

            @staticmethod
            def _model_record(*args, **kwargs):
                raise AssertionError("old flagship record builder must not be called")

        eligible = module._eligible_records(FakeSelector, {}, "token", raw)
        self.assertEqual(len(eligible), 10)
        self.assertEqual(
            [row["company"] for row in eligible].count("shared"), 2
        )
        self.assertEqual(len({row["company"] for row in eligible}), 9)
        self.assertTrue(
            all(row["reasoning_rank_verified"] is True for row in eligible)
        )
        self.assertTrue(
            all(
                row["selection_evidence"] == module.SELECTION_EVIDENCE
                for row in eligible
            )
        )

    def test_eligible_pool_requires_eight_distinct_companies_not_eight_rows(self) -> None:
        module = _load_module()
        raw = [
            _pool_row(index, f"company{index % 7}")
            for index in range(1, 21)
        ]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                return {"data": [{"id": row["model"]} for row in raw]}

            @staticmethod
            def _required_context_tokens(ticket):
                return 9000

            @staticmethod
            def _qualify_candidate(candidate, token, required_context):
                return {
                    **candidate,
                    "qualified_provider_count": 1,
                    "endpoint_inventory_sha256": "b" * 64,
                    "required_context_tokens": required_context,
                    "minimum_completion_tokens": 1024,
                }

        with self.assertRaisesRegex(
            module.Top20ReasoningPoolError,
            "need 8, found 7",
        ):
            module._eligible_records(FakeSelector, {}, "token", raw)


if __name__ == "__main__":
    unittest.main()
