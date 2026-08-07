from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPAIR_PATH = ROOT / "tools" / "repair_expert_child_plan.py"


def _load():
    spec = importlib.util.spec_from_file_location("dynamic_expert_child_repair_test", REPAIR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExpertChildPlanRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repair = _load()
        cls.source = REPAIR_PATH.read_text(encoding="utf-8")

    def test_repair_uses_dynamic_pool_not_legacy_envelope_or_top20(self):
        self.assertIn("top50_reasoning_pool_extension.py", self.source)
        self.assertNotIn("expert_task_envelope.py", self.source)
        self.assertNotIn("top20_reasoning_pool.py", self.source)

    def test_prepare_base_ticket_only_removes_old_plan_and_normalizes_route(self):
        ticket = {
            "task_id": "gov-42-expert",
            "task": {"question": "x"},
            "private_output": True,
            "approved_budget": {"total_calls": 1},
            "governance_model_plan": {"old": True},
        }
        base = self.repair.prepare_base_ticket(ticket, "gov-42-expert")
        self.assertEqual(base["route"], "expert-team")
        self.assertTrue(base["private_output"])
        self.assertEqual(base["approved_budget"], {"total_calls": 1})
        self.assertNotIn("governance_model_plan", base)

    def test_task_identity_remains_integrity_bound(self):
        with self.assertRaisesRegex(self.repair.ExpertChildRepairError, "task_id mismatch"):
            self.repair.prepare_base_ticket({"task_id": "other"}, "gov-42-expert")

    def test_no_company_flagship_budget_or_zdr_qualification_code_remains(self):
        for legacy in (
            "MINIMUM_QUALIFIED_PROVIDER_COUNT",
            "verified-company-flagship-reasoning",
            "fewer than eight executable companies",
            "qualified ZDR provider floor",
            "expert context floor was not enforced",
        ):
            self.assertNotIn(legacy, self.source)

    def test_repair_requires_unrestricted_provider_and_gate_flags_false(self):
        self.assertIn('"unrestricted-openrouter"', self.source)
        for gate in (
            "fixed_team_size_required",
            "fixed_four_plus_four_required",
            "company_uniqueness_required",
            "flagship_filter_required",
            "price_filter_required",
            "intelligence_rank_required",
            "provider_endpoint_qualification_required",
            "zdr_endpoint_qualification_required",
            "free_first_required",
            "canary_required_before_execution",
        ):
            self.assertIn(gate, self.source)


if __name__ == "__main__":
    unittest.main()
