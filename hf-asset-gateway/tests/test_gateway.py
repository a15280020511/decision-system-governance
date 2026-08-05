from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hf_asset_gateway", ROOT / "gateway.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AssetGatewayTests(unittest.TestCase):
    def test_contract_is_production_control(self) -> None:
        contract = MODULE.validate_contract()
        self.assertEqual(contract["status"], "production-control")
        self.assertEqual(
            set(contract["repositories"]),
            {"evaluation_results", "managed_models", "readonly_space"},
        )
        self.assertFalse(contract["boundaries"]["inference_allowed"])
        self.assertFalse(contract["boundaries"]["training_allowed"])
        self.assertFalse(contract["boundaries"]["space_backend_execution_allowed"])

    def test_evaluation_payload_is_empty_and_sanitized(self) -> None:
        files = MODULE._evaluation_files()
        ledger = json.loads(files["evaluation-results/v1/version-ledger.json"])
        schema = json.loads(files["evaluation-results/v1/schema.json"])
        self.assertEqual(ledger["entries"], [])
        self.assertFalse(ledger["raw_prompts_stored"])
        self.assertFalse(ledger["raw_business_data_stored"])
        self.assertFalse(ledger["personal_data_stored"])
        self.assertFalse(ledger["secrets_stored"])
        self.assertIn("raw_prompt", schema["forbidden_fields"])
        self.assertTrue(schema["append_only"])

    def test_model_registry_does_not_enable_binary_ingestion(self) -> None:
        registry = json.loads(MODULE._model_files()["registry.json"])
        self.assertEqual(registry["models"], [])
        self.assertFalse(registry["binary_asset_ingestion_enabled"])
        self.assertTrue(registry["separate_approval_required"])
        self.assertFalse(registry["inference_allowed"])
        self.assertFalse(registry["training_allowed"])

    def test_space_is_static_and_non_control(self) -> None:
        files = MODULE._space_files()
        readme = files["README.md"].decode("utf-8")
        status = json.loads(files["status.json"])
        self.assertIn("sdk: static", readme)
        self.assertTrue(status["display_only"])
        self.assertFalse(status["production_control"])
        self.assertFalse(status["write_actions"])
        self.assertFalse(status["backend_execution"])
        self.assertFalse(status["model_inference"])

    def test_contract_rejects_enabled_inference(self) -> None:
        original = json.loads((ROOT / "contract.json").read_text(encoding="utf-8"))
        mutated = copy.deepcopy(original)
        mutated["boundaries"]["inference_allowed"] = True
        with mock.patch.object(MODULE, "_load", return_value=mutated):
            with self.assertRaises(MODULE.AssetGatewayError):
                MODULE.validate_contract()

    def test_repository_override_must_match_authenticated_owner(self) -> None:
        row = {
            "repository_variable": "HF_EVALUATION_RESULTS_DATASET_REPO",
            "default_repository_name": "evaluation-results",
        }
        with mock.patch.dict(
            MODULE.os.environ,
            {"HF_EVALUATION_RESULTS_DATASET_REPO": "other/evaluation-results"},
            clear=False,
        ):
            with self.assertRaises(MODULE.AssetGatewayError):
                MODULE._repo_id("expected", row)


if __name__ == "__main__":
    unittest.main()
