from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "governance-copilot" / "top50_reasoning_pool_extension.py"


def _load():
    spec = importlib.util.spec_from_file_location("dynamic_model_pool_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(model: str, *, reasoning: bool, output: list[str] | None = None) -> dict:
    return {
        "id": model,
        "name": model,
        "canonical_slug": model,
        "context_length": 8192,
        "supported_parameters": ["reasoning"] if reasoning else [],
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": output or ["text"],
        },
        "top_provider": {"max_completion_tokens": 2048},
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    }


class DynamicCandidatePoolTests(unittest.TestCase):
    def setUp(self):
        self.module = _load()
        self.urls: list[str] = []
        rows = [
            _row("same/model-a", reasoning=True),
            _row("same/model-b", reasoning=False),
            _row("other/model-c", reasoning=False, output=["image"]),
        ]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                del token
                self.urls.append(url)
                query = parse_qs(urlparse(url).query)
                if query.get("sort") == ["intelligence-high-to-low"]:
                    return {"data": [rows[0]]}
                return {"data": rows}

        self.selector = FakeSelector

    def test_live_catalog_has_no_reasoning_or_text_eligibility_filter(self):
        rows = self.module._fetch_rows(self.selector, "token")
        self.assertEqual(len(rows), 3)
        query = parse_qs(urlparse(self.urls[0]).query)
        self.assertNotIn("supported_parameters", query)
        self.assertNotIn("output_modalities", query)

    def test_all_model_identities_are_selectable_even_same_company(self):
        plan = self.module.attach_pool(self.selector, {}, {"plan_sha256": "old"}, "token")
        candidates = plan["expert_candidate_pool"]
        self.assertEqual([row["model"] for row in candidates], [
            "same/model-a", "same/model-b", "other/model-c"
        ])
        self.assertEqual(plan["expert_candidate_pool_size"], 3)
        self.assertEqual(plan["expert_candidate_pool_distinct_company_count"], 2)
        self.assertFalse(plan["expert_candidate_pool_reasoning_only_required"])
        self.assertFalse(plan["expert_candidate_pool_text_only_required"])
        self.assertFalse(plan["expert_candidate_pool_company_diversity_required"])
        self.assertFalse(plan["company_uniqueness_required"])

    def test_provider_and_other_qualification_gates_are_disabled(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        self.assertEqual(plan["provider_routing_mode"], "unrestricted-openrouter")
        self.assertFalse(plan["provider_restrictions_applied"])
        self.assertFalse(plan["provider_endpoint_qualification_required"])
        self.assertFalse(plan["zdr_provider_qualification_required"])
        self.assertFalse(plan["fixed_team_size_required"])
        self.assertFalse(plan["fixed_four_plus_four_required"])
        self.assertFalse(plan["optimizer_optimality_required"])
        self.assertFalse(plan["free_first_required"])
        self.assertFalse(plan["canary_required_before_execution"])

    def test_top50_named_fields_are_compatibility_aliases_not_size_limits(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        self.assertEqual(plan["top50_reasoning_pool_size"], 3)
        self.assertEqual(plan["top50_reasoning_models"], plan["expert_candidate_pool"])
        self.assertFalse(plan["expert_candidate_pool_top50_only"])


if __name__ == "__main__":
    unittest.main()
