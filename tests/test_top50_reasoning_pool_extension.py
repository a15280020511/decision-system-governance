from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "governance-copilot" / "top50_reasoning_pool_extension.py"
    spec = importlib.util.spec_from_file_location("top50_reasoning_pool_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(index: int) -> dict:
    owner = f"company{index}"
    return {
        "id": f"{owner}/model-{index}",
        "name": f"Model {index}",
        "canonical_slug": f"{owner}/model-{index}",
        "context_length": 32768,
        "supported_parameters": ["reasoning"],
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "top_provider": {"max_completion_tokens": 4096},
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "expiration_date": None,
    }


class Top50ReasoningPoolExtensionTests(unittest.TestCase):
    def test_raw_pool_keeps_fifty_weekly_reasoning_models(self) -> None:
        module = _load_module()
        rows = [_row(index) for index in range(1, 56)]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                self.assertIn("sort=most-popular", url)
                self.assertIn("supported_parameters=reasoning", url)
                return {"data": rows}

        pool, _ = module._raw_pool_rows(FakeSelector, "token")
        self.assertEqual(len(pool), 50)
        self.assertEqual(pool[0]["popularity_rank"], 1)
        self.assertEqual(pool[-1]["popularity_rank"], 50)
        self.assertTrue(all(row["popularity_period"] == "week" for row in pool))
        self.assertTrue(all(row["provider_routing_mode"] == "unrestricted-openrouter" for row in pool))

    def test_patch_uses_model_metadata_without_provider_qualification(self) -> None:
        module = _load_module()
        rows = [_row(index) for index in range(1, 56)]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def build_plan(ticket, token=""):
                return {"legacy_top20_marker": True, "plan_sha256": "old"}

            @staticmethod
            def _fetch_json(url: str, token: str):
                if "intelligence-high-to-low" in url:
                    return {"data": [{"id": row["id"]} for row in rows]}
                return {"data": rows}

            @staticmethod
            def _required_context_tokens(ticket):
                return 8192

            @staticmethod
            def _stable_model_id(model_id):
                return True

            @staticmethod
            def _qualify_candidate(*args, **kwargs):
                raise AssertionError("provider qualification must not be called")

        module.patch_selector(FakeSelector)
        plan = FakeSelector.build_plan({}, "token")
        candidates = plan["top50_expert_selectable_candidates"]
        self.assertTrue(plan["legacy_top20_marker"])
        self.assertEqual(plan["top50_reasoning_pool_size"], 50)
        self.assertEqual(len(plan["top50_reasoning_models"]), 50)
        self.assertEqual(len(candidates), 50)
        self.assertEqual(plan["top50_model_assignment_authority"], "expert-assessment-center-ortools")
        self.assertEqual(plan["top50_provider_routing_mode"], "unrestricted-openrouter")
        self.assertFalse(plan["top50_provider_restrictions_applied"])
        self.assertFalse(plan["top50_provider_endpoint_qualification_required"])
        self.assertFalse(plan["top50_zdr_provider_qualification_required"])
        self.assertTrue(all(row["provider_restrictions_applied"] is False for row in candidates))
        provider_qualification_fields = {
            "qualified_provider_count",
            "endpoint_inventory_sha256",
            "provider",
            "provider_endpoint",
            "zdr",
            "data_collection",
        }
        self.assertTrue(
            all(provider_qualification_fields.isdisjoint(row) for row in candidates)
        )


if __name__ == "__main__":
    unittest.main()
