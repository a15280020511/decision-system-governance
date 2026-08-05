from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "contracts" / "gpts-web-session-protocol.json"
INSTRUCTIONS_PATH = ROOT / "gpts-knowledge" / "GPTS_CONTROL_PLANE.md"
RUNBOOK_PATH = ROOT / "CONTROL_PLANE_RUNBOOK.md"
FORMAL_SPEC_PATH = ROOT / "GPTS_WEB_SESSION_PROTOCOL.md"


class GPTWebSessionProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        cls.formal_spec = FORMAL_SPEC_PATH.read_text(encoding="utf-8")

    def test_one_non_terminal_task_per_session_and_one_global_slot(self) -> None:
        lock = self.protocol["session_task_lock"]
        self.assertEqual(lock["maximum_non_terminal_tasks_per_gpt_session"], 1)
        self.assertEqual(lock["maximum_global_execution_slots"], 1)
        self.assertEqual(
            lock["second_submission_while_current_task_non_terminal"],
            "forbidden",
        )

    def test_one_post_and_one_write_approval_per_logical_task(self) -> None:
        submission = self.protocol["submission"]
        self.assertEqual(
            submission["maximum_submitDecisionTask_calls_per_logical_task"], 1
        )
        self.assertEqual(
            submission["maximum_write_approvals_per_logical_task"], 1
        )
        self.assertFalse(submission["post_non_201_retry_allowed"])
        self.assertFalse(submission["missing_post_result_second_approval_allowed"])

    def test_async_execution_is_bounded_and_runner_free(self) -> None:
        asynchronous = self.protocol["asynchronous_execution"]
        self.assertTrue(asynchronous["submission_returns_before_business_completion"])
        self.assertTrue(asynchronous["dispatch_runner_must_not_wait_for_child_completion"])
        self.assertEqual(asynchronous["scheduled_terminal_reconciliation_minutes"], 5)
        self.assertEqual(asynchronous["scheduled_queue_recovery_minutes"], 15)

    def test_query_window_is_phase_based_not_percentage_based(self) -> None:
        query = self.protocol["query_window"]
        self.assertEqual(query["presentation"], "chat_status_card")
        self.assertEqual(query["progress_representation"], "discrete_phase_not_percentage")
        self.assertFalse(query["percentage_claim_allowed"])
        self.assertEqual(query["automatic_same_turn_query_schedule_seconds"], [0, 15, 45, 90])
        self.assertEqual(
            query["after_automatic_window"],
            "return_query_handle_and_stop_polling",
        )

    def test_runtime_remains_zero_third_party_dependency(self) -> None:
        dependency = self.protocol["runtime_dependency_policy"]
        self.assertFalse(dependency["third_party_python_packages_required"])
        self.assertIn("github-actions", dependency["allowed_runtime_primitives"])
        self.assertIn("celery", dependency["forbidden_runtime_dependencies"])
        self.assertIn("redis", dependency["forbidden_runtime_dependencies"])

    def test_gpt_instructions_enforce_session_lock_and_bounded_reads(self) -> None:
        required = (
            "one session task lock",
            "at most one non-terminal logical task",
            "exactly once for one logical task",
            "at most four bounded reads",
            "Do not claim queue position or completion percentage",
            "never create a new task",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, self.instructions)

    def test_runbook_lists_all_six_actions_and_formal_protocol(self) -> None:
        operations = (
            "checkGovernanceGatewayPublic",
            "checkGitHubAuthentication",
            "submitDecisionTask",
            "findDecisionTaskByClientRequestId",
            "getDecisionTaskStatus",
            "getDecisionTaskReceipts",
        )
        for operation in operations:
            with self.subTest(operation=operation):
                self.assertIn(operation, self.runbook)
        self.assertIn("GPTS_WEB_SESSION_PROTOCOL.md", self.runbook)
        self.assertIn("contracts/gpts-web-session-protocol.json", self.formal_spec)


if __name__ == "__main__":
    unittest.main()
