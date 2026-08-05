from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = json.loads(
    (ROOT / "contracts" / "gpts-control-ticket-templates.json").read_text(
        encoding="utf-8"
    )
)
MATRIX = json.loads((ROOT / "INTERFACE_VERSION_MATRIX.json").read_text(encoding="utf-8"))
OPENAPI = (ROOT / "gpts-action" / "openapi.yaml").read_text(encoding="utf-8")
INSTRUCTIONS = (ROOT / "gpts-knowledge" / "GPTS_CONTROL_PLANE.md").read_text(
    encoding="utf-8"
)


class GPTControlTicketTemplateTests(unittest.TestCase):
    def test_exact_v4_literal_and_routes_are_single_source_of_truth(self) -> None:
        self.assertEqual(
            TEMPLATES["control_schema_version"],
            "governance-control-ticket-v4",
        )
        self.assertEqual(
            TEMPLATES["allowed_routes"],
            ["intelligence", "compute", "expert"],
        )
        self.assertEqual(
            MATRIX["control_plane"]["allowed_route_literals"],
            TEMPLATES["allowed_routes"],
        )
        self.assertEqual(
            MATRIX["control_plane"]["ticket_template_contract"],
            "contracts/gpts-control-ticket-templates.json",
        )

    def test_all_templates_use_exact_schema_and_route(self) -> None:
        for route, template in TEMPLATES["templates"].items():
            with self.subTest(route=route):
                self.assertEqual(
                    template["schema_version"],
                    "governance-control-ticket-v4",
                )
                self.assertEqual(template["route"], route)
                self.assertNotIn("task_id", template["ticket"])

    def test_expert_template_matches_governance_owned_selection_boundary(self) -> None:
        ticket = TEMPLATES["templates"]["expert"]["ticket"]
        self.assertEqual(ticket["pipeline"], "expert-team")
        self.assertEqual(ticket["task"]["language"], "zh-CN")
        self.assertEqual(ticket["approved_budget"]["calls"], 8)
        self.assertEqual(ticket["approved_budget"]["maximum_recovery_calls"], 1)
        self.assertIs(ticket["private_output"], False)
        self.assertNotIn("governance_model_plan", ticket)
        for forbidden in TEMPLATES["expert_forbidden_top_level_ticket_fields"]:
            self.assertNotIn(forbidden, ticket)

    def test_openapi_and_instructions_forbid_issue_153_aliases(self) -> None:
        for source in (OPENAPI, INSTRUCTIONS):
            self.assertIn("governance-control-ticket-v4", source)
            self.assertIn("research", source)
            self.assertIn("route", source)
            self.assertIn("expert", source)
        self.assertIn("never 4 or v4", OPENAPI)
        self.assertIn("Never shorten it to `4`, `v4`", INSTRUCTIONS)
        self.assertIn("Never send `research`", INSTRUCTIONS)

    def test_openapi_version_and_examples_are_current(self) -> None:
        self.assertIn("version: 4.1.0", OPENAPI)
        self.assertEqual(
            MATRIX["control_plane"]["gpt_action_interface_version"],
            "4.1.0",
        )
        for route in ("intelligence", "compute", "expert"):
            self.assertIn(f'"route":"{route}"', OPENAPI)
        for field in (
            "objective",
            "pipeline",
            "task",
            "execution_acceptance",
            "approved_budget",
            "private_output",
        ):
            self.assertIn(field, OPENAPI)


if __name__ == "__main__":
    unittest.main()
