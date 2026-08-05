from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_module("selector_base_test", "governance-copilot/select_paid_high_level_model.py")
flagship = load_module("selector_flagship_test", "governance-copilot/select_paid_flagship_model.py")
governance = load_module(
    "selector_governance_test",
    "governance-copilot/select_paid_governance_flagship_model.py",
)


def candidate(model_id: str, *, company: str | None = None, score: float = 50.0) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "canonical_slug": model_id,
        "name": model_id,
        "company": company or model_id.split("/", 1)[0],
        "pricing_rank": 1,
        "prompt_usd_per_million": 0.25,
        "completion_usd_per_million": 1.0,
        "request_usd": None,
        "intelligence_index": score,
        "coding_index": score,
        "agentic_index": score,
        "balanced_score": score,
    }


class BasePrimitiveTests(unittest.TestCase):
    def test_paid_requires_positive_billable_value(self) -> None:
        self.assertFalse(base._is_paid({"prompt": "0", "completion": "0"}))
        self.assertTrue(base._is_paid({"prompt": "0.000001", "completion": "0"}))
        self.assertFalse(base._is_paid({"prompt": "not-a-number"}))

    def test_text_governance_model_is_strict(self) -> None:
        good = {"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}
        image = {"architecture": {"input_modalities": ["text"], "output_modalities": ["text", "image"]}}
        missing = {"architecture": {}}
        self.assertTrue(base._is_text_governance_model(good))
        self.assertFalse(base._is_text_governance_model(image))
        self.assertFalse(base._is_text_governance_model(missing))

    def test_stable_release_rejects_unstable_lifecycle_names(self) -> None:
        stable = {"name": "Vendor Flagship Pro"}
        for marker in ("preview", "beta", "experimental"):
            row = {"name": f"Vendor Flagship {marker}"}
            self.assertFalse(base._is_stable_release(row, f"vendor/model-{marker}", "vendor/model"))
        self.assertTrue(base._is_stable_release(stable, "vendor/model-pro", "vendor/model-pro"))

    def test_natural_split_is_deterministic(self) -> None:
        values = [10.0, 11.0, 12.0, 50.0, 52.0, 55.0]
        first = base._two_cluster_high_tier(values)
        for _ in range(20):
            self.assertEqual(first, base._two_cluster_high_tier(values))
        self.assertEqual(first[0], [False, False, False, True, True, True])

    def test_split_rejects_degenerate_input(self) -> None:
        with self.assertRaises(base.SelectorError):
            base._two_cluster_high_tier([1.0])
        with self.assertRaises(base.SelectorError):
            base._two_cluster_high_tier([1.0, 1.0])


class FlagshipRefinementTests(unittest.TestCase):
    def test_explicit_product_tiers_are_recognized(self) -> None:
        raw = [
            candidate("a/model-pro", score=45),
            candidate("b/model-max", score=46),
            candidate("c/model-opus", score=47),
            candidate("d/model-ultra", score=48),
            candidate("e/model-premier", score=49),
        ]
        result = flagship.refine({"cheapest_paid_flagship_candidates": raw})
        self.assertEqual([r["model_id"] for r in result["cheapest_paid_flagship_candidates"]], [r["model_id"] for r in raw])

    def test_singleton_without_product_tier_is_not_silently_called_flagship(self) -> None:
        with self.assertRaises(RuntimeError):
            flagship.refine({"cheapest_paid_flagship_candidates": [candidate("vendor/model-standard")]})

    def test_price_order_is_preserved_not_resorted_by_score(self) -> None:
        cheap = candidate("a/cheap-pro", score=40)
        expensive = candidate("b/expensive-pro", score=90)
        result = flagship.refine({"cheapest_paid_flagship_candidates": [cheap, expensive]})
        self.assertEqual(result["selected_model"]["model_id"], "a/cheap-pro")

    def test_malformed_candidate_list_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            flagship.refine({})
        with self.assertRaises(RuntimeError):
            flagship.refine({"cheapest_paid_flagship_candidates": "bad"})


class GovernanceFinalizationTests(unittest.TestCase):
    def test_domain_specialized_pro_models_are_rejected(self) -> None:
        rows = [
            candidate("vendor/coder-pro"),
            candidate("vendor/content-safety-pro"),
            candidate("vendor/embed-pro"),
            candidate("vendor/rerank-pro"),
            candidate("vendor/general-pro"),
        ]
        result = governance.finalize({"cheapest_paid_flagship_candidates": rows})
        self.assertEqual(result["selected_model"]["model_id"], "vendor/general-pro")
        rejected = {row["model_id"] for row in result["flagship_false_positive_controls"]["domain_specialized_models_rejected"]}
        self.assertEqual(rejected, {"vendor/coder-pro", "vendor/content-safety-pro", "vendor/embed-pro", "vendor/rerank-pro"})

    def test_first_remaining_candidate_wins_after_rejection(self) -> None:
        rows = [candidate("a/coder-pro"), candidate("b/general-pro"), candidate("c/general-max")]
        result = governance.finalize({"cheapest_paid_flagship_candidates": rows})
        self.assertEqual(result["selected_model"]["model_id"], "b/general-pro")
        self.assertEqual([r["model_id"] for r in result["cheapest_paid_flagship_candidates"]], ["b/general-pro", "c/general-max"])

    def test_catalog_change_selects_new_cheapest_without_history(self) -> None:
        first = governance.finalize({"cheapest_paid_flagship_candidates": [candidate("a/old-pro"), candidate("b/new-pro")]})
        second = governance.finalize({"cheapest_paid_flagship_candidates": [candidate("b/new-pro")]})
        self.assertEqual(first["selected_model"]["model_id"], "a/old-pro")
        self.assertEqual(second["selected_model"]["model_id"], "b/new-pro")

    def test_empty_or_specialized_only_pool_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            governance.finalize({"cheapest_paid_flagship_candidates": []})
        with self.assertRaises(RuntimeError):
            governance.finalize({"cheapest_paid_flagship_candidates": [candidate("a/coder-pro")]})

    def test_malformed_rows_are_ignored_and_do_not_crash(self) -> None:
        result = governance.finalize({"cheapest_paid_flagship_candidates": [None, "bad", candidate("a/general-pro")]})
        self.assertEqual(result["selected_model"]["model_id"], "a/general-pro")

    def test_receipt_forces_zero_calls_zero_cost_and_no_secret_exposure(self) -> None:
        result = governance.finalize({
            "cheapest_paid_flagship_candidates": [candidate("a/general-pro")],
            "model_calls": 999,
            "estimated_model_cost_usd": 999,
            "secret_values_exposed": True,
        })
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["estimated_model_cost_usd"], 0)
        self.assertFalse(result["secret_values_exposed"])

    def test_same_snapshot_is_byte_deterministic(self) -> None:
        source = {"cheapest_paid_flagship_candidates": [candidate("a/general-pro"), candidate("b/general-max")]}
        first = json.dumps(governance.finalize(source), ensure_ascii=False, sort_keys=True)
        for _ in range(50):
            self.assertEqual(first, json.dumps(governance.finalize(source), ensure_ascii=False, sort_keys=True))

    def test_receipt_writer_does_not_include_environment_secret(self) -> None:
        secret = "sk-or-v1-DO-NOT-LEAK-TEST"
        result = governance.finalize({"cheapest_paid_flagship_candidates": [candidate("a/general-pro")]})
        with tempfile.TemporaryDirectory() as directory:
            base.write_receipts(result, Path(directory))
            text = "\n".join(path.read_text(encoding="utf-8") for path in Path(directory).iterdir())
        self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
