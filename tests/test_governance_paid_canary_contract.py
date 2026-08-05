from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "governance-canary" / "run_paid_governance_copilot_canary.py"


def load_module():
    spec = importlib.util.spec_from_file_location("paid_canary", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load paid canary module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = load_module()


def valid_payload():
    return {
        "verdict": "REVISE",
        "recommended_route": ["decision-system-governance"],
        "critical_findings": [
            {
                "category": "permission",
                "evidence": "contents: write",
                "remediation": "use contents: read",
            },
            {
                "category": "secret",
                "evidence": "prints OPENROUTER_API_KEY",
                "remediation": "remove secret logging",
            },
            {
                "category": "loop",
                "evidence": "while True",
                "remediation": "use bounded execution",
            },
            {
                "category": "topology",
                "evidence": "direct evidence to compute dispatch",
                "remediation": "route only through governance",
            },
        ],
        "minimal_patch_plan": ["reduce permission", "remove print", "bound loop"],
        "required_tests": ["permission test", "secret test", "topology test"],
        "rollback_plan": ["revert the workflow commit"],
        "confidence": 0.94,
    }


class CanaryContractTests(unittest.TestCase):
    def test_valid_json_passes(self):
        result = canary.validate_model_content(json.dumps(valid_payload()))
        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(
            {row["category"] for row in result["critical_findings"]},
            canary.REQUIRED_CATEGORIES,
        )

    def test_markdown_json_fence_is_tolerated(self):
        content = "```json\n" + json.dumps(valid_payload()) + "\n```"
        self.assertEqual(
            canary.validate_model_content(content)["verdict"], "REVISE"
        )

    def test_missing_category_fails_closed(self):
        payload = valid_payload()
        payload["critical_findings"] = payload["critical_findings"][:-1]
        with self.assertRaises(canary.CanaryError):
            canary.validate_model_content(json.dumps(payload))

    def test_wrong_route_fails_closed(self):
        payload = valid_payload()
        payload["recommended_route"] = ["evidence-data-center"]
        with self.assertRaises(canary.CanaryError):
            canary.validate_model_content(json.dumps(payload))

    def test_pass_verdict_fails_closed(self):
        payload = valid_payload()
        payload["verdict"] = "PASS"
        with self.assertRaises(canary.CanaryError):
            canary.validate_model_content(json.dumps(payload))

    def test_invalid_confidence_fails_closed(self):
        payload = valid_payload()
        payload["confidence"] = 1.1
        with self.assertRaises(canary.CanaryError):
            canary.validate_model_content(json.dumps(payload))

    def test_non_json_fails_closed(self):
        with self.assertRaises(canary.CanaryError):
            canary.validate_model_content("not json")

    def test_source_contains_one_post_and_no_retry_loop(self):
        source = MODULE_PATH.read_text("utf-8")
        self.assertEqual(source.count("method=\"POST\""), 1)
        self.assertNotIn("for attempt in", source)
        self.assertNotIn("while True", source.replace("while True:", "synthetic-case"))
        self.assertIn("fallback_model_calls\": 0", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
