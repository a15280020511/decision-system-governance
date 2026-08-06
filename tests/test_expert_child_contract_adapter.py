from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "control-plane" / "resilient_control.py"
    spec = importlib.util.spec_from_file_location("expert_child_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNTIME = _load()


class ExpertChildContractAdapterTests(unittest.TestCase):
    def test_governance_ticket_matches_expert_execution_contract(self) -> None:
        adapted = RUNTIME._adapt_expert_execution_contract(
            {
                "task_id": "gov-172-expert",
                "objective": "Assess strategy",
                "pipeline": "expert-team",
                "task": {
                    "question": "Analyze the task",
                    "requirements": ["Separate facts and inference"],
                    "language": "zh-CN",
                },
                "approved_budget": {
                    "calls": 8,
                    "maximum_recovery_calls": 1,
                },
                "evidence": [],
                "execution_acceptance": ["Publish final synthesis"],
                "private_output": False,
            }
        )
        self.assertEqual(adapted["route"], "expert-team")
        self.assertEqual(
            adapted["approved_budget"]["cost_policy"],
            "prompt_led_soft_governance",
        )
        self.assertEqual(adapted["pipeline"]["pipeline_id"], "gov-172-expert")
        self.assertEqual(adapted["pipeline"]["stage_id"], "expert")
        self.assertFalse(adapted["private_output"])

    def test_existing_budget_policy_is_preserved(self) -> None:
        adapted = RUNTIME._adapt_expert_execution_contract(
            {
                "task_id": "gov-999-expert",
                "pipeline": {
                    "pipeline_id": "gov-999-expert",
                    "stage_id": "expert",
                },
                "task": {"question": "Q"},
                "approved_budget": {
                    "calls": 8,
                    "maximum_recovery_calls": 1,
                    "cost_policy": "unbounded_with_anomaly_guard",
                },
            }
        )
        self.assertEqual(
            adapted["approved_budget"]["cost_policy"],
            "unbounded_with_anomaly_guard",
        )

    def test_invalid_private_output_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "private_output"):
            RUNTIME._adapt_expert_execution_contract(
                {
                    "task_id": "gov-172-expert",
                    "task": {"question": "Q"},
                    "approved_budget": {
                        "calls": 8,
                        "maximum_recovery_calls": 1,
                    },
                    "private_output": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
