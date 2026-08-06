from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "expert-plan-preview.yml"
SIGNER = ROOT / "tools" / "sign_expert_plan.py"


class ExpertPlanPreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.signer = SIGNER.read_text(encoding="utf-8")

    def test_owner_only_issue_entrypoint(self) -> None:
        text = self.workflow
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("startsWith(github.event.issue.title, '[expert-plan]')", text)
        self.assertIn("issues:\n    types: [opened]", text)

    def test_workflow_uses_dedicated_zero_call_signer(self) -> None:
        text = self.workflow
        self.assertIn("python tools/sign_expert_plan.py", text)
        self.assertIn("Model calls: `0`", text)
        self.assertIn("Child dispatch: `false`", text)
        self.assertIn("No expert execution was attempted", text)
        self.assertIn("Verify authoritative zero-call signing outcome", text)
        self.assertNotIn("chat/completions", text)
        self.assertNotIn("v5_price_ranked_production_ticket.py", text)

    def test_signer_applies_same_frozen_contract_as_production(self) -> None:
        text = self.signer
        required = (
            "expert_task_envelope.py",
            "TASK_ENVELOPE.patch_selector(SELECTOR)",
            "zdr_endpoint_qualification_required",
            "MINIMUM_QUALIFIED_PROVIDER_COUNT",
            "authenticated-zdr-endpoint-qualified",
            "selection authority is not governance",
            "expert center reranking must be disabled",
            "model substitution must be disabled",
            "model does not satisfy the qualified ZDR provider floor",
            "model lacks verified company reasoning flagship evidence",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_signer_preserves_ticket_and_plan_digests(self) -> None:
        text = self.signer
        required = (
            "signing changed ticket fields outside the plan",
            "signed ticket and plan file differ",
            "plan digest mismatch",
            "plan task hash mismatch",
            "plan does not match the frozen expert task envelope",
            "endpoint inventory hash is invalid",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_preview_cannot_dispatch_or_execute_children(self) -> None:
        combined = self.workflow + "\n" + self.signer
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
                self.assertNotIn(value, combined)

    def test_signed_ticket_is_written_back_to_same_issue(self) -> None:
        text = self.workflow
        self.assertIn("issue_number: context.issue.number", text)
        self.assertIn("body: signed", text)
        self.assertIn("state_reason: 'completed'", text)
        self.assertIn("EXPERT_PLAN_COMPLETED", text)
        self.assertIn("governance-expert-plan-preview-${{ github.run_id }}", text)

    def test_fail_closed_validation_boundaries(self) -> None:
        text = self.signer
        required = (
            "unsigned ticket must not contain governance_model_plan",
            "route must be expert-team",
            "private_output must be false",
            "budget must leave at least three initial expert calls",
            "expert model companies are not globally distinct",
            "OPENROUTER_API_KEY is required",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_permissions_remain_read_only_for_contents(self) -> None:
        permissions = self.workflow.split("concurrency:", 1)[0]
        self.assertIn("contents: read", permissions)
        self.assertNotIn("contents: write", permissions)
        self.assertIn("issues: write", permissions)

    def test_explicit_always_guards_prevent_status_skip(self) -> None:
        text = self.workflow
        self.assertIn(
            "if: ${{ always() && steps.sign.outcome == 'success' }}",
            text,
        )
        self.assertIn(
            "steps.artifact.outcome == 'success'",
            text,
        )
        self.assertIn(
            "steps.publish.outcome != 'success'",
            text,
        )
        self.assertIn(
            'test "${{ steps.publish.outcome }}" = "success"',
            text,
        )


if __name__ == "__main__":
    unittest.main()
