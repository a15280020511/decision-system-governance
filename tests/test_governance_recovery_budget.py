from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "governance-copilot" / "expert_task_envelope.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "governance_recovery_budget_test",
        POLICY,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


policy = _load()


def ticket(calls: int, recovery: int) -> dict:
    return {
        "task_id": "recovery-policy-001",
        "route": "expert-team",
        "task": {"question": "Analyze one decision"},
        "approved_budget": {
            "calls": calls,
            "maximum_recovery_calls": recovery,
            "cost_policy": "prompt_led_soft_governance",
        },
        "private_output": False,
    }


class GovernanceRecoveryBudgetTests(unittest.TestCase):
    def test_zero_recovery_is_upgraded_without_reducing_initial_capacity(self) -> None:
        source = ticket(4, 0)
        normalized = policy.normalize_recovery_budget(source)
        self.assertEqual(source["approved_budget"]["calls"], 4)
        self.assertEqual(source["approved_budget"]["maximum_recovery_calls"], 0)
        self.assertEqual(normalized["approved_budget"]["calls"], 5)
        self.assertEqual(normalized["approved_budget"]["maximum_recovery_calls"], 1)
        self.assertEqual(
            normalized["approved_budget"]["calls"]
            - normalized["approved_budget"]["maximum_recovery_calls"],
            4,
        )

    def test_existing_larger_recovery_reserve_is_preserved(self) -> None:
        source = ticket(6, 2)
        normalized = policy.normalize_recovery_budget(source)
        self.assertEqual(normalized["approved_budget"], source["approved_budget"])

    def test_maximum_total_budget_still_gets_one_recovery_slot(self) -> None:
        normalized = policy.normalize_recovery_budget(ticket(16, 0))
        self.assertEqual(normalized["approved_budget"]["calls"], 16)
        self.assertEqual(normalized["approved_budget"]["maximum_recovery_calls"], 1)
        self.assertGreaterEqual(
            normalized["approved_budget"]["calls"]
            - normalized["approved_budget"]["maximum_recovery_calls"],
            3,
        )

    def test_recovery_policy_covers_transport_and_empty_output_failures(self) -> None:
        self.assertEqual(policy.MINIMUM_GOVERNANCE_RECOVERY_MODELS, 1)
        self.assertEqual(
            policy.RECOVERY_POOL_POLICY,
            "shared-governance-approved-candidates",
        )
        self.assertIn("PROVIDER_TIMEOUT", policy.RECOVERY_TRIGGER_CATEGORIES)
        self.assertIn("PROVIDER_EMPTY_RESPONSE", policy.RECOVERY_TRIGGER_CATEGORIES)
        self.assertIn("PROVIDER_RATE_LIMITED", policy.RECOVERY_TRIGGER_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
