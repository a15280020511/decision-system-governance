from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
import expert_task_envelope as envelope  # noqa: E402


def load_selector():
    name = f"zdr_selector_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name, COPILOT / "select_expert_team_plan.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load expert plan selector")
    selector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector)
    envelope.patch_selector(selector)
    return selector


def per_token(usd_per_million: float) -> str:
    return f"{usd_per_million / 1_000_000:.12f}"


def candidate(model_id: str, rank: int) -> dict[str, object]:
    return {
        "model_id": model_id,
        "company": model_id.split("/", 1)[0],
        "official_intelligence_rank": rank,
        "context_length": 131_072,
        "max_completion_tokens": 8_192,
        "prompt_usd_per_million": float(rank) / 10,
        "completion_usd_per_million": float(rank) / 5,
        "request_usd": 0.0,
        "price_rank_usd_per_million": float(rank) * 0.3,
        "estimated_task_cost_usd": float(rank) * 0.3,
        "flagship_verified": True,
        "flagship_basis": "strict-product-tier",
        "company_flagship_method": "fixture-strict-tier",
        "benchmark_source": "artificial-analysis-via-openrouter",
        "intelligence_index": 50.0,
        "coding_index": 50.0,
        "agentic_index": 50.0,
        "balanced_score": 50.0,
        "benchmark_evidence_sha256": hashlib.sha256(
            (model_id + "-benchmark").encode("utf-8")
        ).hexdigest(),
    }


def qualified_candidate(model_id: str, rank: int) -> dict[str, object]:
    row = candidate(model_id, rank)
    row.update(
        {
            "exact_endpoint_qualified": True,
            "zdr_endpoint_qualified": True,
            "qualified_provider_count": 2,
            "endpoint_inventory_sha256": hashlib.sha256(
                model_id.encode("utf-8")
            ).hexdigest(),
            "required_context_tokens": 16_384,
            "minimum_completion_tokens": 1_024,
        }
    )
    return row


def endpoint(provider: str) -> dict[str, object]:
    return {
        "tag": provider,
        "context_length": 131_072,
        "max_completion_tokens": 8_192,
        "pricing": {
            "prompt": per_token(0.2),
            "completion": per_token(0.4),
        },
    }


def ticket() -> dict[str, object]:
    return {
        "route": "expert-team",
        "task": {
            "question": "Use only governance-selected executable experts.",
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


class ExpertZdrEndpointParityTests(unittest.TestCase):
    def test_public_only_model_is_skipped_and_two_zdr_routes_are_accepted(self) -> None:
        selector = load_selector()
        calls: list[str] = []

        def fake_fetch(url: str, token: str):
            self.assertEqual(token, "secret")
            calls.append(url)
            if url == envelope.ZDR_ENDPOINTS_API:
                return {
                    "data": [
                        {
                            "model_id": "nex-agi/nex-n2-pro",
                            "tag": "zdr-provider-a",
                        },
                        {
                            "model_id": "nex-agi/nex-n2-pro",
                            "tag": "zdr-provider-b",
                        },
                    ]
                }
            if "solar-pro-3" in url:
                return {
                    "data": {
                        "endpoints": [
                            endpoint("ordinary-provider-a"),
                            endpoint("ordinary-provider-b"),
                        ]
                    }
                }
            return {
                "data": {
                    "endpoints": [
                        endpoint("zdr-provider-a"),
                        endpoint("zdr-provider-b"),
                    ]
                }
            }

        selector._fetch_json = fake_fetch
        solar = selector._qualify_candidate(
            candidate("upstage/solar-pro-3", 1), "secret", 16_384
        )
        nex = selector._qualify_candidate(
            candidate("nex-agi/nex-n2-pro", 2), "secret", 16_384
        )

        self.assertIsNone(solar)
        self.assertIsNotNone(nex)
        assert nex is not None
        self.assertTrue(nex["zdr_endpoint_qualified"])
        self.assertEqual(nex["qualified_provider_count"], 2)
        self.assertEqual(calls.count(envelope.ZDR_ENDPOINTS_API), 1)

    def test_single_zdr_route_satisfies_provider_floor(self) -> None:
        selector = load_selector()

        def fake_fetch(url: str, token: str):
            self.assertEqual(token, "secret")
            if url == envelope.ZDR_ENDPOINTS_API:
                return {
                    "data": [
                        {
                            "model_id": "vendor/model-pro",
                            "tag": "zdr-provider-a",
                        }
                    ]
                }
            return {
                "data": {
                    "endpoints": [
                        endpoint("zdr-provider-a"),
                        endpoint("ordinary-provider-b"),
                    ]
                }
            }

        selector._fetch_json = fake_fetch
        qualified = selector._qualify_candidate(
            candidate("vendor/model-pro", 1), "secret", 16_384
        )
        self.assertIsNotNone(qualified)
        assert qualified is not None
        self.assertEqual(qualified["qualified_provider_count"], 1)

    def test_empty_or_missing_zdr_inventory_fails_closed(self) -> None:
        selector = load_selector()
        selector._fetch_json = lambda url, token: {"data": []}
        with self.assertRaisesRegex(
            envelope.ExpertTaskEnvelopeError,
            "ZDR endpoint inventory is empty",
        ):
            selector._qualify_candidate(
                candidate("vendor/model-pro", 1), "secret", 16_384
            )

        selector = load_selector()
        selector._fetch_json = lambda url, token: {"unexpected": []}
        with self.assertRaisesRegex(
            envelope.ExpertTaskEnvelopeError,
            "ZDR endpoint inventory is unavailable",
        ):
            selector._qualify_candidate(
                candidate("vendor/model-pro", 1), "secret", 16_384
            )

    def test_missing_authentication_token_fails_before_endpoint_selection(self) -> None:
        selector = load_selector()
        with self.assertRaisesRegex(
            envelope.ExpertTaskEnvelopeError,
            "OPENROUTER_API_KEY is required",
        ):
            selector._qualify_candidate(
                candidate("vendor/model-pro", 1), "", 16_384
            )

    def test_plan_records_zdr_provider_floor_and_recomputes_digest(self) -> None:
        selector = load_selector()
        rows = [
            qualified_candidate("deepseek/deepseek-v4-pro", 1),
            qualified_candidate("nex-agi/nex-n2-pro", 2),
            qualified_candidate("xiaomi/mimo-v2.5-pro", 3),
            qualified_candidate("amazon/nova-pro-v1", 4),
            qualified_candidate("google/gemini-pro", 5),
            qualified_candidate("mistralai/mistral-pro", 6),
            qualified_candidate("qwen/qwen-pro", 7),
            qualified_candidate("baidu/ernie-pro", 8),
        ]
        with mock.patch.object(
            selector,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            plan = selector.build_plan(ticket(), token="secret")

        self.assertEqual(plan["expert_count"], 4)
        self.assertEqual(plan["recovery_count"], 4)
        self.assertEqual(len(plan["selected_models"]), 4)
        self.assertEqual(len(plan["recovery_models"]), 4)
        self.assertEqual(
            [row["model"] for row in plan["recovery_models"]],
            [
                "google/gemini-pro",
                "mistralai/mistral-pro",
                "qwen/qwen-pro",
                "baidu/ernie-pro",
            ],
        )
        companies = {
            row["company"]
            for row in plan["selected_models"] + plan["recovery_models"]
        }
        self.assertEqual(len(companies), 8)
        self.assertEqual(
            plan["recovery_order_policy"],
            envelope.RECOVERY_ORDER_POLICY,
        )
        self.assertTrue(plan["recovery_models_are_price_ranked"])
        self.assertTrue(plan["recovery_models_are_sequential"])
        self.assertTrue(plan["zdr_endpoint_qualification_required"])
        self.assertEqual(
            plan["zdr_endpoint_inventory_source"],
            envelope.ZDR_ENDPOINTS_API,
        )
        self.assertEqual(
            plan["minimum_qualified_provider_count"],
            envelope.MINIMUM_QUALIFIED_PROVIDER_COUNT,
        )
        self.assertEqual(
            plan["source_selector_schema_version"],
            envelope.ZDR_SELECTOR_SCHEMA_VERSION,
        )
        self.assertIn("authenticated-zdr-endpoint-qualified", plan["selection_policy"])
        self.assertIn("minimum-one-zdr-provider-route", plan["selection_policy"])
        for row in plan["selected_models"] + plan["recovery_models"]:
            self.assertGreaterEqual(row["qualified_provider_count"], 1)
            self.assertIn(
                "authenticated-zdr-endpoint-qualified",
                row["selection_evidence"],
            )
            self.assertIn(
                "minimum-one-zdr-provider-route",
                row["selection_evidence"],
            )

        material = dict(plan)
        digest = material.pop("plan_sha256")
        expected = hashlib.sha256(
            json.dumps(
                material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
