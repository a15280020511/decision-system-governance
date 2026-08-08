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
            _row("same/model-b", reasoning=True),
            _row("other/model-c", reasoning=True),
        ]
        user_rows = [rows[0], rows[2]]

        class FakeSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                del token
                self.urls.append(url)
                parsed = urlparse(url)
                if parsed.path.endswith("/models/user"):
                    return {"data": user_rows}
                query = parse_qs(parsed.query)
                if query.get("sort") == ["intelligence-high-to-low"]:
                    return {"data": [rows[0]]}
                return {"data": rows}

        self.selector = FakeSelector

    def test_live_source_is_reasoning_popularity_sequence(self):
        rows = self.module._fetch_rows(self.selector, "token")
        self.assertEqual(len(rows), 3)
        query = parse_qs(urlparse(self.urls[0]).query)
        self.assertEqual(query.get("sort"), ["most-popular"])
        self.assertEqual(query.get("supported_parameters"), ["reasoning"])
        self.assertEqual(query.get("output_modalities"), ["text"])

    def test_full_reasoning_sequence_is_selectable_without_topn_or_company_gate(self):
        plan = self.module.attach_pool(
            self.selector, {}, {"plan_sha256": "old"}, "token"
        )
        candidates = plan["expert_candidate_pool"]
        self.assertEqual(
            [row["model"] for row in candidates],
            ["same/model-a", "same/model-b", "other/model-c"],
        )
        self.assertEqual(plan["expert_candidate_pool_size"], 3)
        self.assertEqual(plan["expert_candidate_pool_distinct_company_count"], 2)
        self.assertFalse(plan["expert_candidate_pool_top50_only"])
        self.assertTrue(plan["expert_candidate_pool_reasoning_popularity_source"])
        self.assertFalse(plan["expert_candidate_pool_company_diversity_required"])
        self.assertFalse(plan["company_uniqueness_required"])

    def test_user_policy_view_is_advisory_metadata_not_candidate_gate(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        candidates = plan["expert_candidate_pool"]
        self.assertEqual(len(candidates), 3)
        compatibility = {
            row["model"]: row["user_policy_compatible"] for row in candidates
        }
        self.assertEqual(
            compatibility,
            {
                "same/model-a": True,
                "same/model-b": False,
                "other/model-c": True,
            },
        )
        audit = plan["user_policy_compatibility_telemetry"]
        self.assertTrue(audit["available"])
        self.assertEqual(audit["candidate_pool_compatible_count"], 2)
        self.assertEqual(audit["candidate_pool_incompatible_count"], 1)
        self.assertFalse(audit["used_as_normal_candidate_gate"])
        self.assertFalse(plan["user_policy_compatibility_normal_candidate_gate_required"])
        self.assertFalse(plan["provider_endpoint_qualification_required"])
        self.assertFalse(plan["provider_restrictions_applied"])

    def test_user_policy_fetch_failure_leaves_unknown_and_never_filters(self):
        module = self.module
        rows = [
            _row("same/model-a", reasoning=True),
            _row("same/model-b", reasoning=True),
        ]

        class FailingUserSelector:
            MODELS_API = "https://example.invalid/models"

            @staticmethod
            def _fetch_json(url: str, token: str):
                del token
                parsed = urlparse(url)
                if parsed.path.endswith("/models/user"):
                    raise RuntimeError("user view unavailable")
                return {"data": rows}

        plan = module.attach_pool(FailingUserSelector, {}, {}, "token")
        self.assertEqual(len(plan["expert_candidate_pool"]), 2)
        self.assertTrue(
            all(
                row["user_policy_compatible"] is None
                for row in plan["expert_candidate_pool"]
            )
        )
        self.assertFalse(plan["user_policy_compatibility_telemetry"]["available"])
        self.assertFalse(plan["provider_restrictions_applied"])

    def test_only_hard_model_boundary_is_no_tools(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        self.assertTrue(plan["tool_use_forbidden"])
        self.assertFalse(plan["tools_allowed"])
        self.assertEqual(plan["only_hard_model_boundary"], "no-tools")
        self.assertTrue(all(row["tool_use_forbidden"] for row in plan["expert_candidate_pool"]))
        self.assertTrue(all(not row["tools_allowed"] for row in plan["expert_candidate_pool"]))

    def test_provider_and_other_qualification_gates_are_disabled(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        self.assertEqual(plan["provider_routing_mode"], "unrestricted-openrouter")
        self.assertFalse(plan["provider_restrictions_applied"])
        self.assertFalse(plan["provider_endpoint_qualification_required"])
        self.assertFalse(plan["zdr_provider_qualification_required"])
        self.assertFalse(plan["user_policy_compatibility_normal_candidate_gate_required"])
        self.assertFalse(plan["fixed_team_size_required"])
        self.assertFalse(plan["fixed_four_plus_four_required"])
        self.assertFalse(plan["optimizer_optimality_required"])
        self.assertFalse(plan["free_first_required"])
        self.assertFalse(plan["canary_required_before_execution"])
        self.assertFalse(plan["price_filter_required"])
        self.assertFalse(plan["flagship_filter_required"])
        self.assertFalse(plan["intelligence_rank_required"])

    def test_top50_named_fields_are_compatibility_aliases_not_size_limits(self):
        plan = self.module.attach_pool(self.selector, {}, {}, "token")
        self.assertEqual(plan["top50_reasoning_pool_size"], 3)
        self.assertEqual(
            plan["top50_reasoning_models"], plan["expert_candidate_pool"]
        )
        self.assertFalse(plan["expert_candidate_pool_top50_only"])


if __name__ == "__main__":
    unittest.main()
