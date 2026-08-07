from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "tools" / "sign_expert_plan.py"
WORKFLOW = ROOT / ".github" / "workflows" / "expert-plan-preview.yml"


class ExpertPlanPreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signer = SIGNER.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.exists() else ""

    def test_signer_uses_dynamic_catalog_not_legacy_qualification_modules(self):
        self.assertIn("top50_reasoning_pool_extension.py", self.signer)
        self.assertIn("DYNAMIC_POOL.patch_selector(SELECTOR)", self.signer)
        self.assertNotIn("expert_task_envelope.py", self.signer)
        self.assertNotIn("top20_reasoning_pool.py", self.signer)

    def test_signer_does_not_preselect_or_freeze_experts(self):
        self.assertIn('"governance_selected_model_count": 0', self.signer)
        self.assertIn('"governance_recovery_model_count": 0', self.signer)
        self.assertIn('"expert_center_dynamic_composition_required": True', self.signer)
        self.assertIn('"fixed_team_size_required": False', self.signer)
        self.assertIn('"fixed_four_plus_four_required": False', self.signer)
        self.assertIn('"company_uniqueness_required": False', self.signer)

    def test_provider_routing_has_no_endpoint_or_zdr_gate(self):
        self.assertIn('"provider_routing_mode": "unrestricted-openrouter"', self.signer)
        self.assertIn('"provider_endpoint_qualification_required": False', self.signer)
        self.assertIn('"zdr_endpoint_qualification_required": False', self.signer)
        for legacy in (
            "MINIMUM_QUALIFIED_PROVIDER_COUNT",
            "authenticated-zdr-endpoint-qualified",
            "qualified ZDR provider floor",
            "provider only",
            "provider order",
        ):
            self.assertNotIn(legacy, self.signer)

    def test_free_first_price_flagship_and_rank_are_not_qualification_gates(self):
        self.assertIn('"flagship_filter_required": False', self.signer)
        self.assertIn('"price_filter_required": False', self.signer)
        self.assertIn('"intelligence_rank_required": False', self.signer)
        self.assertIn('"free_first_required": False', self.signer)
        self.assertIn('"canary_required_before_execution": False', self.signer)

    def test_signing_still_preserves_integrity(self):
        for marker in (
            "signing changed ticket content outside governance_model_plan",
            "signed ticket and plan differ",
            "plan digest mismatch",
            "plan task hash mismatch",
            "live candidate inventory is empty",
        ):
            self.assertIn(marker, self.signer)

    def test_preview_remains_owner_controlled_if_present(self):
        if not self.workflow:
            self.skipTest("preview workflow removed")
        self.assertIn("github.repository_owner", self.workflow)
        self.assertIn("OPENROUTER_API_KEY", self.workflow)
        self.assertNotIn("MINIMUM_QUALIFIED_PROVIDER_COUNT", self.workflow)
        self.assertNotIn("top20_reasoning_pool", self.workflow)


if __name__ == "__main__":
    unittest.main()
