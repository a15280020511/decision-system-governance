from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = (ROOT / "gpts-action" / "openapi.yaml").read_text(encoding="utf-8")


class GPTActionSchemaCompatibilityTests(unittest.TestCase):
    def test_components_schemas_is_explicit_object(self) -> None:
        self.assertIn(
            "components:\n  schemas: {}\n  securitySchemes:\n",
            OPENAPI,
        )

    def test_schema_avoids_refs_rejected_by_importer(self) -> None:
        self.assertNotIn("$ref:", OPENAPI)

    def test_exposes_exactly_four_operations(self) -> None:
        self.assertEqual(OPENAPI.count("operationId:"), 4)
        self.assertIn("operationId: findDecisionTaskByClientRequestId", OPENAPI)

    def test_submission_documents_uuid_and_readback(self) -> None:
        self.assertIn("governance-control-ticket-v4", OPENAPI)
        self.assertIn("client_request_id", OPENAPI)
        self.assertIn("read-after-write", OPENAPI)


if __name__ == "__main__":
    unittest.main()
