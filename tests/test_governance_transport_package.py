from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = ROOT / "control-plane"
PACKAGE_ROOT = CONTROL_ROOT / "governance_transport"
if str(CONTROL_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_ROOT))

from governance_transport.audit import audit_event
from governance_transport.diagnostics import (
    comment_readback_verified,
    issue_readback_verified,
    repository_metadata_verified,
)
from governance_transport.idempotency import V3, V4, fingerprint_packet
from governance_transport.retry import MAX_BACKOFF_SECONDS, RETRYABLE_HTTP
from governance_transport.status import build_machine_status


class GovernanceTransportPackageTests(unittest.TestCase):
    def test_package_uses_only_standard_library_and_relative_imports(self) -> None:
        stdlib = set(sys.stdlib_module_names)
        for path in sorted(PACKAGE_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], stdlib, path.name)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn((node.module or "").split(".")[0], stdlib, path.name)

    def test_v3_and_v4_share_one_business_fingerprint(self) -> None:
        ticket = {
            "operation": "descriptive_statistics",
            "inputs": {"data": [1, 2, 3]},
        }
        v3 = {"schema_version": V3, "route": "compute", "ticket": ticket}
        v4 = {
            "schema_version": V4,
            "client_request_id": "8beae650-3676-4a76-b8a4-e45f76ccf822",
            "route": "compute",
            "ticket": ticket,
        }
        self.assertEqual(fingerprint_packet(v3), fingerprint_packet(v4))

    def test_readback_diagnostics_are_exact_and_fail_closed(self) -> None:
        body = '{"schema_version":"governance-control-ticket-v4"}'
        issue = {"number": 9, "title": "[control]", "body": body}
        self.assertTrue(
            issue_readback_verified(
                issue,
                issue_number=9,
                expected_body=body,
                client_request_id="",
            )
        )
        self.assertFalse(
            issue_readback_verified(
                {**issue, "body": body + "x"},
                issue_number=9,
                expected_body=body,
                client_request_id="",
            )
        )
        created = {"id": 12}
        comments = [{"id": 12, "body": "receipt"}]
        self.assertTrue(
            comment_readback_verified(created, comments, expected_body="receipt")
        )
        self.assertFalse(
            comment_readback_verified(created, comments, expected_body="other")
        )
        self.assertTrue(
            repository_metadata_verified(
                {
                    "full_name": "a15280020511/decision-system-governance",
                    "archived": False,
                    "disabled": False,
                    "has_issues": True,
                },
                "a15280020511/decision-system-governance",
            )
        )

    def test_machine_status_has_one_stable_schema(self) -> None:
        status = build_machine_status(
            client_request_id="8beae650-3676-4a76-b8a4-e45f76ccf822",
            issue_number=9,
            state="RECEIVED",
            route="compute",
            body_fingerprint="a" * 64,
            read_after_write_verified=True,
            updated_at="2026-08-05T00:00:00+00:00",
        )
        self.assertEqual(status["schema_version"], "governance-machine-status-v1")
        self.assertEqual(status["issue_number"], 9)
        self.assertTrue(status["read_after_write_verified"])

    def test_audit_redacts_nested_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            with mock.patch.dict(
                os.environ,
                {"GOVERNANCE_HTTP_AUDIT_FILE": str(path)},
                clear=False,
            ):
                audit_event(
                    {
                        "event": "test",
                        "token": "request-secret",
                        "nested": {
                            "Authorization": "Bearer secret",
                            "body": "response-secret",
                            "status": 503,
                        },
                    }
                )
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("request-secret", text)
            self.assertNotIn("response-secret", text)
            self.assertNotIn("Bearer secret", text)
            row = json.loads(text)
            self.assertEqual(row["token"], "[redacted]")
            self.assertEqual(row["nested"]["status"], 503)

    def test_retry_contract_remains_bounded(self) -> None:
        self.assertEqual(RETRYABLE_HTTP, {429, 502, 503, 504})
        self.assertEqual(MAX_BACKOFF_SECONDS, 120)


if __name__ == "__main__":
    unittest.main()
