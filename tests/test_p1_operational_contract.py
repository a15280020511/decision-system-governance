from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_WORKFLOW = (
    ROOT / ".github" / "workflows" / "control-plane-ticket.yml"
).read_text(encoding="utf-8")
HEALTH_WORKFLOW = (
    ROOT / ".github" / "workflows" / "governance-health-check.yml"
).read_text(encoding="utf-8")
HEALTH_SCRIPT = (
    ROOT / "security" / "governance_health_check.py"
).read_text(encoding="utf-8")
STATUS_DICTIONARY = json.loads(
    (ROOT / "control-plane" / "status-dictionary.json").read_text(encoding="utf-8")
)
RETENTION_POLICY = (
    ROOT / "ISSUE_AND_ARTIFACT_RETENTION_POLICY.md"
).read_text(encoding="utf-8")


class P1OperationalContractTests(unittest.TestCase):
    def test_all_direct_control_commands_use_resilient_entrypoint(self) -> None:
        self.assertNotIn("python control-plane/control_plane.py", CONTROL_WORKFLOW)
        self.assertGreaterEqual(
            CONTROL_WORKFLOW.count("python control-plane/resilient_control.py"),
            10,
        )
        self.assertIn("python control-plane/deferred_poll.py", CONTROL_WORKFLOW)
        self.assertIn("GOVERNANCE_HTTP_AUDIT_FILE", CONTROL_WORKFLOW)

    def test_queue_wake_is_bounded_and_has_degradation_receipt(self) -> None:
        self.assertIn("Wake next FIFO worker with bounded retry", CONTROL_WORKFLOW)
        self.assertIn("delays=(0 5 15)", CONTROL_WORKFLOW)
        self.assertEqual(
            CONTROL_WORKFLOW.count(
                "gh workflow run control-plane-ticket.yml --ref main"
            ),
            1,
        )
        self.assertIn("CONTROL_QUEUE_WAKE_DEGRADED", CONTROL_WORKFLOW)
        self.assertIn("15-minute scheduled worker", CONTROL_WORKFLOW)
        self.assertIn("Model/API/compute calls caused by wake retries: `0`", CONTROL_WORKFLOW)

    def test_health_check_is_daily_zero_business_call_and_single_issue(self) -> None:
        required = (
            'cron: "23 2 * * *"',
            "CONTROL_PLANE_TOKEN:",
            "governance_health_check.py",
            "[health] Governance Control Plane",
            "Reconcile single health Issue",
            "External business data calls: `0`",
            "Secret values recorded: `false`",
        )
        missing = [item for item in required if item not in HEALTH_WORKFLOW]
        self.assertEqual(missing, [])
        self.assertEqual(HEALTH_WORKFLOW.count("CONTROL_PLANE_TOKEN:"), 1)
        self.assertNotIn("OPENROUTER_API_KEY", HEALTH_WORKFLOW)
        self.assertNotIn("ANTHROPIC_API_KEY", HEALTH_WORKFLOW)
        self.assertNotIn("OPENAI_API_KEY", HEALTH_WORKFLOW)

    def test_health_script_has_positive_and_negative_scope_checks(self) -> None:
        required = (
            "a15280020511/decision-system-governance",
            "a15280020511/evidence-data-center",
            "a15280020511/compute-simulation-center",
            "a15280020511/expert-assessment-center",
            "/contents",
            "/actions/secrets",
            '"secret_values_recorded": False',
            '"model_calls": 0',
            '"external_business_data_calls": 0',
        )
        missing = [item for item in required if item not in HEALTH_SCRIPT]
        self.assertEqual(missing, [])

    def test_status_dictionary_has_required_user_states(self) -> None:
        required = {
            "CREATED",
            "QUEUED",
            "CONTROL_RUNNING",
            "CONTROL_DISPATCHED",
            "CHILD_ACCEPTED",
            "CONTROL_COMPLETED",
            "CONTROL_FAILED",
            "CONTROL_REJECTED",
            "CONTROL_DUPLICATE",
            "CONTROL_TIMEOUT",
            "CONTROL_MONITOR_ERROR",
            "CONTROL_RECONCILED_LATE_SUCCESS",
            "CONTROL_RECONCILED_LATE_FAILURE",
            "CONTROL_QUEUE_WAKE_DEGRADED",
            "PLATFORM_UNAVAILABLE",
        }
        statuses = STATUS_DICTIONARY["statuses"]
        self.assertEqual(required - set(statuses), set())
        for name in required:
            self.assertIsInstance(statuses[name]["terminal"], bool)
            self.assertTrue(statuses[name]["meaning"])
            self.assertTrue(statuses[name]["next_action"])

    def test_retention_policy_does_not_claim_indefinite_archive(self) -> None:
        self.assertIn("No automatic durable archive is enabled", RETENTION_POLICY)
        self.assertIn("must not claim indefinite evidence retention", RETENTION_POLICY)
        self.assertIn("must not contain", RETENTION_POLICY)
        self.assertIn("Token values", RETENTION_POLICY)


if __name__ == "__main__":
    unittest.main()
