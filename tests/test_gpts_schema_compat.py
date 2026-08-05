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

    def test_exposes_exactly_six_operations(self) -> None:
        required = {
            "operationId: checkGovernanceGatewayPublic",
            "operationId: checkGitHubAuthentication",
            "operationId: submitDecisionTask",
            "operationId: findDecisionTaskByClientRequestId",
            "operationId: getDecisionTaskStatus",
            "operationId: getDecisionTaskReceipts",
        }
        self.assertEqual(OPENAPI.count("operationId:"), 6)
        for operation in required:
            self.assertIn(operation, OPENAPI)

    def test_submission_documents_uuid_and_readback(self) -> None:
        self.assertIn("governance-control-ticket-v4", OPENAPI)
        self.assertIn("client_request_id", OPENAPI)
        self.assertIn("read-after-write", OPENAPI)

    def test_operation_descriptions_fit_gpt_builder_limit(self) -> None:
        descriptions = _operation_descriptions(OPENAPI)
        self.assertEqual(len(descriptions), 6)
        for operation_id, description in descriptions.items():
            with self.subTest(operation_id=operation_id):
                self.assertLessEqual(len(description), 300)

    def test_consequential_flags_are_explicit(self) -> None:
        self.assertEqual(OPENAPI.count("x-openai-isConsequential: true"), 1)
        self.assertEqual(OPENAPI.count("x-openai-isConsequential: false"), 5)

    def test_public_probe_overrides_bearer_auth(self) -> None:
        public_section = OPENAPI.split(
            "/repos/a15280020511/decision-system-governance:", 1
        )[1].split("\n  /user:", 1)[0]
        self.assertIn("operationId: checkGovernanceGatewayPublic", public_section)
        self.assertIn("security: []", public_section)

    def test_authenticated_probe_is_read_only(self) -> None:
        auth_section = OPENAPI.split("\n  /user:", 1)[1].split(
            "\n  /repos/a15280020511/decision-system-governance/issues:", 1
        )[0]
        self.assertIn("operationId: checkGitHubAuthentication", auth_section)
        self.assertIn("x-openai-isConsequential: false", auth_section)
        self.assertIn("githubBearer", auth_section)

    def test_post_errors_forbid_automatic_retry(self) -> None:
        self.assertIn('"401":\n          description: Bearer token missing', OPENAPI)
        self.assertIn('"403":\n          description: Token lacks Issues write access', OPENAPI)
        self.assertIn('"422":\n          description: Request validation failed', OPENAPI)
        self.assertIn("without retrying the POST", OPENAPI)


if __name__ == "__main__":
    unittest.main()
