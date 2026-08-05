from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "control-plane" / "ingress_ack.py"
SPEC = importlib.util.spec_from_file_location("test_ingress_ack", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GPTsIngressAcknowledgementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request_id = "8beae650-3676-4a76-b8a4-e45f76ccf822"
        self.body = json.dumps(
            {
                "schema_version": MODULE.V4,
                "client_request_id": self.request_id,
                "route": "compute",
                "ticket": {
                    "operation": "descriptive_statistics",
                    "inputs": {"data": [1, 2, 3]},
                },
            },
            separators=(",", ":"),
        )

    def test_issue_readback_requires_exact_identity_and_body(self) -> None:
        issue = {"number": 12, "title": "[control]", "body": self.body}
        self.assertTrue(
            MODULE._issue_readback_verified(
                issue,
                issue_number=12,
                expected_body=self.body,
                client_request_id=self.request_id,
            )
        )
        for mutation in (
            {**issue, "number": 13},
            {**issue, "title": "[other]"},
            {**issue, "body": self.body + "x"},
            {"number": 12, "title": "[control]", "body": "{}"},
        ):
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    MODULE._issue_readback_verified(
                        mutation,
                        issue_number=12,
                        expected_body=self.body,
                        client_request_id=self.request_id,
                    )
                )

    def test_control_received_reports_verified_readback_only(self) -> None:
        machine = MODULE._machine_status(
            client_request_id=self.request_id,
            issue_number=12,
            route="compute",
            fingerprint="a" * 64,
            schema_valid=True,
            read_after_write_verified=True,
            observed_at="2026-08-05T00:00:00+00:00",
        )
        receipt = MODULE._receipt(
            client_request_id=self.request_id,
            issue_number=12,
            schema_version=MODULE.V4,
            schema_valid=True,
            fingerprint="a" * 64,
            machine=machine,
        )
        self.assertTrue(machine["read_after_write_verified"])
        self.assertIn("Read-after-write verified: `true`", receipt)
        self.assertIn('"read_after_write_verified": true', receipt)
        self.assertIn("CONTROL_RECEIVED", receipt)

    def test_invalid_schema_is_explicit_not_silently_accepted(self) -> None:
        machine = MODULE._machine_status(
            client_request_id="",
            issue_number=12,
            route="",
            fingerprint="",
            schema_valid=False,
            read_after_write_verified=False,
            observed_at="2026-08-05T00:00:00+00:00",
        )
        self.assertEqual(machine["error_code"], "CONTROL_SCHEMA_REJECTED")
        self.assertFalse(machine["read_after_write_verified"])


if __name__ == "__main__":
    unittest.main()
