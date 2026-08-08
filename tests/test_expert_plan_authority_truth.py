from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "governance-copilot" / "select_expert_team_plan.py"


def _load():
    spec = importlib.util.spec_from_file_location("expert_plan_authority_truth", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExpertPlanAuthorityTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load()

    def test_governance_owns_pool_but_not_model_selection(self) -> None:
        plan = self.module.build_plan(
            {"task": {"question": "比较三个方案并给出建议"}}
        )
        self.assertEqual(
            "decision-system-governance",
            plan["candidate_pool_authority"],
        )
        self.assertEqual(
            "expert-assessment-center-dynamic-ortools",
            plan["selection_authority"],
        )
        self.assertEqual(
            plan["selection_authority"],
            plan["model_assignment_authority"],
        )
        self.assertFalse(plan["selection_performed_by_governance"])
        self.assertTrue(plan["candidate_pool_selection_performed_by_governance"])

    def test_company_heterogeneity_is_delegated_soft_not_governance_gate(self) -> None:
        plan = self.module.build_plan({"task": {"question": "复杂任务"}})
        self.assertEqual(
            "expert-assessment-center-current-task",
            plan["company_heterogeneity_optimization_authority"],
        )
        self.assertFalse(plan["company_heterogeneity_hard_gate_required"])
        self.assertFalse(plan["fixed_company_count_required"])
        self.assertFalse(plan["company_uniqueness_required"])


if __name__ == "__main__":
    unittest.main()
