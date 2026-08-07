from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "control-plane" / "resilient_control.py"


class ExpertChildContractAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CONTROL.read_text(encoding="utf-8")

    def test_governance_delegates_model_assignment_to_expert_center(self):
        self.assertIn("expert-assessment-center-dynamic-ortools", self.text)
        self.assertIn("unrestricted-openrouter", self.text)

    def test_no_fixed_budget_or_team_qualification_is_injected(self):
        for legacy in (
            "budget must leave at least three initial expert calls",
            "four_primary_zero_recovery",
            "8+4",
            "eight_total",
            "distinct_expert_companies",
            "MINIMUM_QUALIFIED_PROVIDER_COUNT",
        ):
            self.assertNotIn(legacy, self.text)

    def test_private_output_is_not_an_expert_model_eligibility_gate(self):
        self.assertNotIn("private_output must be false", self.text)

    def test_provider_endpoint_and_zdr_qualification_are_disabled(self):
        self.assertIn('"provider_routing_mode": "unrestricted-openrouter"', self.text)
        self.assertIn('"provider_endpoint_qualification_required": False', self.text)
        self.assertIn('"zdr_endpoint_qualification_required": False', self.text)

    def test_governance_does_not_select_fixed_primary_or_recovery_models(self):
        self.assertIn('"selected_expert_count": 0', self.text)
        self.assertIn('"selected_recovery_count": 0', self.text)


if __name__ == "__main__":
    unittest.main()
