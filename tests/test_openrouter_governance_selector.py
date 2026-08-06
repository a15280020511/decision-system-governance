from __future__ import annotations

import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = (
    ROOT / "governance-copilot" / "select_paid_governance_flagship_model.py"
)


def load_selector():
    spec = importlib.util.spec_from_file_location("governance_selector_test", SELECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load governance selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = load_selector()


def per_token(usd_per_million: float) -> str:
    return f"{usd_per_million / 1_000_000:.12f}"


def model(
    model_id: str,
    *,
    prompt: float,
    completion: float,
    name: str | None = None,
    description: str = "",
    canonical: str | None = None,
    expiration: str | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    request: float | None = None,
    reasoning: bool = True,
) -> dict[str, Any]:
    pricing: dict[str, str] = {
        "prompt": per_token(prompt),
        "completion": per_token(completion),
    }
    if request is not None:
        pricing["request"] = str(request)
    row: dict[str, Any] = {
        "id": model_id,
        "canonical_slug": canonical or model_id,
        "name": name or model_id,
        "description": description,
        "supported_parameters": (["max_tokens", "reasoning"] if reasoning else ["max_tokens"]),
        "pricing": pricing,
        "architecture": {
            "input_modalities": inputs or ["text"],
            "output_modalities": outputs or ["text"],
        },
    }
    if expiration is not None:
        row["expiration_date"] = expiration
    return row


def benchmark(
    slug: str,
    score: float,
    *,
    coding: float | None = None,
    agentic: float | None = None,
) -> dict[str, Any]:
    return {
        "model_permaslug": slug,
        "intelligence_index": score,
        "coding_index": coding if coding is not None else score,
        "agentic_index": agentic if agentic is not None else score,
    }


def run_pipeline(
    models: list[dict[str, Any]], benchmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    return selector.select_from_catalog(
        models,
        {"data": benchmarks, "meta": {"source": "fixture", "version": "test"}},
    )


class SelectorPipelineTests(unittest.TestCase):
    def standard_fixture(self):
        models = [
            model("free/free-pro", prompt=0, completion=0),
            model("unstable/alpha-pro-preview", prompt=0.01, completion=0.02),
            model("economy/vendor-mini-pro", prompt=0.02, completion=0.03),
            model("regular/a", prompt=0.03, completion=0.04),
            model("regular/b", prompt=0.04, completion=0.05),
            model("kwaipilot/kat-coder-pro-v2", prompt=0.10, completion=0.20),
            model("nex-agi/nex-n2-pro", prompt=0.25, completion=1.00),
            model("deepseek/deepseek-v4-pro", prompt=0.435, completion=0.87),
        ]
        benchmarks = [
            benchmark("free/free-pro", 90),
            benchmark("unstable/alpha-pro-preview", 90),
            benchmark("economy/vendor-mini-pro", 90),
            benchmark("regular/a", 10),
            benchmark("regular/b", 12),
            benchmark("kwaipilot/kat-coder-pro-v2", 44),
            benchmark("nex-agi/nex-n2-pro", 42),
            benchmark("deepseek/deepseek-v4-pro", 46),
        ]
        return models, benchmarks

    def test_end_to_end_selects_first_general_flagship_in_price_order(self):
        models, benchmarks = self.standard_fixture()
        result = run_pipeline(models, benchmarks)
        self.assertEqual(result["selected_model"]["model_id"], "nex-agi/nex-n2-pro")
        ids = [row["model_id"] for row in result["cheapest_paid_flagship_candidates"]]
        self.assertEqual(ids, ["nex-agi/nex-n2-pro", "deepseek/deepseek-v4-pro"])
        rejected = result["flagship_false_positive_controls"][
            "domain_specialized_models_rejected"
        ]
        self.assertEqual(rejected[0]["model_id"], "kwaipilot/kat-coder-pro-v2")

    def test_price_order_drift_changes_winner_without_code_change(self):
        models, benchmarks = self.standard_fixture()
        deep = next(row for row in models if row["id"] == "deepseek/deepseek-v4-pro")
        nex = next(row for row in models if row["id"] == "nex-agi/nex-n2-pro")
        models.remove(deep)
        models.insert(models.index(nex), deep)
        result = run_pipeline(models, benchmarks)
        self.assertEqual(result["selected_model"]["model_id"], "deepseek/deepseek-v4-pro")

    def test_free_unstable_economy_expired_and_non_text_are_excluded(self):
        models, benchmarks = self.standard_fixture()
        models[3] = model(
            "expired/old-pro",
            prompt=0.01,
            completion=0.01,
            expiration="2000-01-01",
        )
        benchmarks[3] = benchmark("expired/old-pro", 99)
        models[4] = model(
            "image/image-pro",
            prompt=0.01,
            completion=0.01,
            outputs=["image"],
        )
        benchmarks[4] = benchmark("image/image-pro", 99)
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("free/free-pro", ids)
        self.assertNotIn("unstable/alpha-pro-preview", ids)
        self.assertNotIn("economy/vendor-mini-pro", ids)
        self.assertNotIn("expired/old-pro", ids)
        self.assertNotIn("image/image-pro", ids)

    def test_incomplete_or_invalid_pricing_is_excluded(self):
        models, benchmarks = self.standard_fixture()
        bad = model("bad/missing-price-pro", prompt=0.01, completion=0.02)
        del bad["pricing"]["completion"]
        models.insert(5, bad)
        negative = model("bad/negative-price-pro", prompt=0.01, completion=0.02)
        negative["pricing"]["prompt"] = "-1"
        models.insert(6, negative)
        benchmarks.extend(
            [
                benchmark("bad/missing-price-pro", 99),
                benchmark("bad/negative-price-pro", 99),
            ]
        )
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("bad/missing-price-pro", ids)
        self.assertNotIn("bad/negative-price-pro", ids)

    def test_missing_or_invalid_benchmarks_are_ignored(self):
        models, benchmarks = self.standard_fixture()
        models.insert(5, model("bad/missing-pro", prompt=0.05, completion=0.06))
        models.insert(6, model("bad/zero-pro", prompt=0.05, completion=0.06))
        benchmarks.append(
            {
                "model_permaslug": "bad/zero-pro",
                "intelligence_index": 0,
                "coding_index": 50,
                "agentic_index": 50,
            }
        )
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("bad/missing-pro", ids)
        self.assertNotIn("bad/zero-pro", ids)

    def test_generic_marketing_description_does_not_define_flagship(self):
        models, benchmarks = self.standard_fixture()
        models.insert(
            5,
            model(
                "marketing/ordinary",
                prompt=0.08,
                completion=0.09,
                description="A flagship frontier top-tier state-of-the-art model",
            ),
        )
        benchmarks.insert(5, benchmark("marketing/ordinary", 43))
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("marketing/ordinary", ids)

    def test_specialized_markers_are_case_insensitive(self):
        for model_id in (
            "vendor/CODER-PRO",
            "vendor/content-SAFETY-pro",
            "vendor/Embed-Pro",
            "vendor/RERANK-Pro",
            "vendor/moderation-pro",
            "perplexity/sonar-pro-search",
        ):
            self.assertFalse(selector._is_general_governance_identity(model_id))
        self.assertTrue(
            selector._is_general_governance_identity("deepseek/deepseek-v4-pro")
        )

    def test_luna_and_non_reasoning_models_are_excluded(self):
        models, benchmarks = self.standard_fixture()
        models.insert(5, model("openai/gpt-5.6-luna-pro", prompt=0.01, completion=0.02))
        models.insert(6, model("vendor/nonreasoning-pro", prompt=0.01, completion=0.02, reasoning=False))
        benchmarks.extend(
            [
                benchmark("openai/gpt-5.6-luna-pro", 99),
                benchmark("vendor/nonreasoning-pro", 99),
            ]
        )
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
        self.assertNotIn("vendor/nonreasoning-pro", ids)
        self.assertTrue(
            result["flagship_false_positive_controls"]["native_reasoning_required"]
        )

    def test_duplicate_model_ids_are_deduplicated_in_first_seen_order(self):
        models, benchmarks = self.standard_fixture()
        duplicate = dict(next(row for row in models if row["id"] == "nex-agi/nex-n2-pro"))
        models.append(duplicate)
        result = run_pipeline(models, benchmarks)
        ids = [row["model_id"] for row in result["cheapest_paid_flagship_candidates"]]
        self.assertEqual(ids.count("nex-agi/nex-n2-pro"), 1)

    def test_equal_score_company_group_is_stable(self):
        models, benchmarks = self.standard_fixture()
        models.extend(
            [
                model("equal/equal-pro", prompt=2, completion=2),
                model("equal/equal-max", prompt=3, completion=3),
            ]
        )
        benchmarks.extend(
            [benchmark("equal/equal-pro", 44), benchmark("equal/equal-max", 44)]
        )
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertIn("equal/equal-pro", ids)
        self.assertIn("equal/equal-max", ids)

    def test_deterministic_for_same_snapshot(self):
        models, benchmarks = self.standard_fixture()
        outputs = [run_pipeline(models, benchmarks) for _ in range(20)]
        selections = {result["selected_model"]["model_id"] for result in outputs}
        candidate_lists = {
            tuple(row["model_id"] for row in result["cheapest_paid_flagship_candidates"])
            for result in outputs
        }
        self.assertEqual(selections, {"nex-agi/nex-n2-pro"})
        self.assertEqual(len(candidate_lists), 1)

    def test_irrelevant_catalog_noise_does_not_change_winner(self):
        models, benchmarks = self.standard_fixture()
        baseline = run_pipeline(models, benchmarks)["selected_model"]["model_id"]
        noise_models = [
            model(f"noise/free-{index}", prompt=0, completion=0)
            for index in range(100)
        ]
        noise_benchmarks = [benchmark(f"noise/free-{index}", 100) for index in range(100)]
        random.Random(20260805).shuffle(noise_models)
        result = run_pipeline(noise_models + models, noise_benchmarks + benchmarks)
        self.assertEqual(result["selected_model"]["model_id"], baseline)

    def test_no_general_flagship_fails_closed(self):
        models = [
            model("regular/a", prompt=0.1, completion=0.1),
            model("regular/b", prompt=0.2, completion=0.2),
            model("vendor/code-pro", prompt=0.3, completion=0.3),
            model("vendor/safety-pro", prompt=0.4, completion=0.4),
        ]
        benchmarks = [
            benchmark("regular/a", 10),
            benchmark("regular/b", 12),
            benchmark("vendor/code-pro", 45),
            benchmark("vendor/safety-pro", 46),
        ]
        with self.assertRaisesRegex(
            selector.SelectorError, "no general-purpose paid flagship"
        ):
            run_pipeline(models, benchmarks)

    def test_receipt_is_valid_json_and_contains_no_token(self):
        models, benchmarks = self.standard_fixture()
        result = run_pipeline(models, benchmarks)
        with tempfile.TemporaryDirectory() as tmp:
            selector.write_receipts(result, Path(tmp))
            payload = json.loads((Path(tmp) / "selection.json").read_text("utf-8"))
            self.assertEqual(payload["model_calls"], 0)
            self.assertFalse(payload["secret_values_exposed"])
            self.assertNotIn("fixture-token", json.dumps(payload))


class NetworkAndParserTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self._payload = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload

    def test_temporary_network_failure_is_retried_once(self):
        response = self.FakeResponse({"data": [{"id": "ok"}]})
        with mock.patch.object(
            selector.urllib.request,
            "urlopen",
            side_effect=[OSError("temporary"), response],
        ) as urlopen, mock.patch.object(selector.time, "sleep") as sleep:
            payload = selector._fetch_json("https://example.invalid", "secret")
        self.assertEqual(payload["data"][0]["id"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_permanent_network_failure_has_bounded_retry(self):
        with mock.patch.object(
            selector.urllib.request, "urlopen", side_effect=OSError("down")
        ) as urlopen, mock.patch.object(selector.time, "sleep"):
            with self.assertRaises(selector.SelectorError):
                selector._fetch_json("https://example.invalid", "secret")
        self.assertEqual(urlopen.call_count, 2)

    def test_empty_and_malformed_catalogs_fail_closed(self):
        for payload in ({}, {"data": []}, {"data": "wrong"}):
            with mock.patch.object(selector, "_fetch_json", return_value=payload):
                with self.assertRaises(selector.SelectorError):
                    selector._fetch_rows("https://example.invalid", "secret")

    def test_numeric_parser_rejects_nan_inf_and_negative_price(self):
        self.assertIsNone(selector._number("nan"))
        self.assertIsNone(selector._number("inf"))
        self.assertIsNone(
            selector._price_per_million({"prompt": "-0.1"}, "prompt")
        )
        self.assertEqual(
            selector._price_per_million({"prompt": "0.000001"}, "prompt"), 1.0
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
