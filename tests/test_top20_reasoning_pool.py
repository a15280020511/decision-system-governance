from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "governance-copilot" / "top20_reasoning_pool.py"
    spec = importlib.util.spec_from_file_location("top20_reasoning_pool_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(index: int, *, reasoning: bool = True) -> dict:
    parameters = ["max_tokens", "reasoning"] if reasoning else ["max_tokens"]
    return {
        "id": f"company{index}/model-{index}",
        "name": f"Model {index}",
        "canonical_slug": f"company{index}/model-{index}",
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


def test_raw_pool_keeps_first_twenty_reasoning_rows_in_server_order() -> None:
    module = _load_module()
    rows = [_row(0, reasoning=False)] + [_row(index) for index in range(1, 23)]

    class FakeSelector:
        MODELS_API = "https://example.invalid/models"

        @staticmethod
        def _fetch_json(url: str, token: str):
            assert "sort=most-popular" in url
            assert "supported_parameters=reasoning" in url
            assert token == "token"
            return {"data": rows}

    pool, payload = module._raw_pool_rows(FakeSelector, "token")
    assert payload == {"data": rows}
    assert len(pool) == 20
    assert [row["popularity_rank"] for row in pool] == list(range(1, 21))
    assert [row["model"] for row in pool] == [
        f"company{index}/model-{index}" for index in range(1, 21)
    ]
    assert all(row["reasoning_supported"] is True for row in pool)
    assert all(row["pool_source"] == module.POOL_SOURCE for row in pool)
