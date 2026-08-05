from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = (ROOT / "gpts-action" / "openapi.yaml").read_text(encoding="utf-8")


def _operation_descriptions(source: str) -> dict[str, str]:
    lines = source.splitlines()
    descriptions: dict[str, str] = {}
    operation_id: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("operationId: "):
            operation_id = stripped.split(":", 1)[1].strip()
            continue
        if operation_id is None or stripped != "description: >":
            continue
        base_indent = len(line) - len(line.lstrip())
        parts: list[str] = []
        for next_line in lines[index + 1 :]:
            if not next_line.strip():
                break
            next_indent = len(next_line) - len(next_line.lstrip())
            if next_indent <= base_indent:
                break
            parts.append(next_line.strip())
        descriptions[operation_id] = " ".join(parts)
        operation_id = None
    return descriptions


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

    def test_operation_descriptions_fit_gpt_builder_limit(self) -> None:
        descriptions = _operation_descriptions(OPENAPI)
        self.assertEqual(len(descriptions), 4)
        for operation_id, description in descriptions.items():
            with self.subTest(operation_id=operation_id):
                self.assertLessEqual(len(description), 300)


if __name__ == "__main__":
    unittest.main()
