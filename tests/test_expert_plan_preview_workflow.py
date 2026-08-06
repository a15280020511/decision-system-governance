from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "expert-plan-preview.yml"


class ExpertPlanPreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_owner_only_issue_entrypoint(self) -> None:
        text = self.text
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("startsWith(github.event.issue.title, '[expert-plan]')", text)
        self.assertIn("issues:\n    types: [opened]", text)

    def test_preview_uses_governance_selector_and_no_model_runtime(self) -> None:
        text = self.text
        self.assertIn("governance-copilot/select_expert_team_plan.py", text)
        self.assertIn("--output-ticket", text)
        self.assertIn("--output-plan", text)
        self.assertIn('plan.get("model_calls") != 0', text)
        self.assertIn("Model calls: `0`", text)
        self.assertNotIn("chat/completions", text)
        self.assertNotIn("responses.create", text)
        self.assertNotIn("anthropic.com", text)

    def test_preview_cannot_dispatch_or_execute_children(self) -> None:
        text = self.text
        forbidden = (
            "CONTROL_PLANE_TOKEN",
            "/run-expert-team",
            "/retry-expert-team",
            "expert-assessment-center/issues",
            "evidence-data-center/issues",
            "compute-simulation-center/issues",
            "v5_price_ranked_production_ticket.py",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, text)
        self.assertIn("Child dispatch: `false`", text)
        self.assertIn("No expert execution was attempted", text)

    def test_signed_ticket_is_written_back_to_same_issue(self) -> None:
        text = self.text
        self.assertIn("issue_number: context.issue.number", text)
        self.assertIn("body: signed", text)
        self.assertIn("state_reason: 'completed'", text)
        self.assertIn("EXPERT_PLAN_COMPLETED", text)
        self.assertIn("governance-expert-plan-preview-${{ github.run_id }}", text)

    def test_fail_closed_validation_boundaries(self) -> None:
        text = self.text
        required = (
            "unsigned ticket must not contain governance_model_plan",
            "route must be expert-team",
            "private_output must be false",
            "budget must leave at least three initial expert calls",
            "selection authority is not governance",
            "expert companies are not globally distinct",
            "governance companies cannot be expert companies",
            "every model must have at least two qualified providers",
            "EXPERT_PLAN_FAILED",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_permissions_remain_read_only_for_contents(self) -> None:
        permissions = self.text.split("concurrency:", 1)[0]
        self.assertIn("contents: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertIn("issues: write", permissions)


if __name__ == "__main__":
    unittest.main()
