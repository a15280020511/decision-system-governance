from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "async_reconcile.py"
SPEC = importlib.util.spec_from_file_location("async_reconcile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AsyncReconcileTests(unittest.TestCase):
    def issue(self, *, number: int = 42, route: str = "compute", state: str = "open") -> dict:
        repo = MODULE.CONTROL.ROUTES[route]["repository"]
        task_id = f"gov-{number}-{route}"
        body = "\n".join([
            '{"schema_version":"governance-control-ticket-v3"}',
            "",
            "---",
            "",
            MODULE.CONTROL.STATUS_START,
            "## CONTROL_DISPATCHED",
            "",
            f"- Task ID: `{task_id}`",
            f"- Route: `{route}`",
            f"- Child Issue: https://github.com/{repo}/issues/7",
            MODULE.CONTROL.STATUS_END,
        ])
        return {
            "number": number,
            "title": "[control]",
            "state": state,
            "body": body,
            "updated_at": "2099-01-01T00:00:00Z",
            "user": {"login": MODULE.CONTROL.OWNER},
        }

    def test_candidate_is_owner_task_and_route_bound(self):
        item = MODULE.candidate(self.issue())
        self.assertIsNotNone(item)
        self.assertEqual(item["task_id"], "gov-42-compute")
        self.assertEqual(item["child_repository"], "a15280020511/compute-simulation-center")
        self.assertNotIn("updated_at", item)

    def test_closed_or_wrong_task_is_rejected(self):
        self.assertIsNone(MODULE.candidate(self.issue(state="closed")))
        wrong = self.issue()
        wrong["body"] = wrong["body"].replace("gov-42-compute", "wrong")
        self.assertIsNone(MODULE.candidate(wrong))

    def test_deadline_uses_child_dispatch_time_not_governance_updates(self):
        item = MODULE.candidate(self.issue(route="expert"))
        item["dispatched_at"] = MODULE._parse_time("2026-08-05T00:00:00Z", "child Issue created_at")
        now = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(MODULE.age_seconds(item, now), 14400)
        receipt = MODULE.render_deadline(item, 14400)
        self.assertIn("CONTROL_ASYNC_DEADLINE_EXCEEDED", receipt)
        self.assertIn("Runner-held waiting: `false`", receipt)
        self.assertIn("child Issue created_at", receipt)

    def test_terminal_receipt_declares_scheduled_polling(self):
        item = MODULE.candidate(self.issue())
        receipt = MODULE.render_terminal(
            item,
            ("COMPUTE_COMPLETED", "## COMPUTE_COMPLETED\n\n- Task ID: `gov-42-compute`", True),
        )
        self.assertTrue(receipt.startswith("## CONTROL_COMPLETED"))
        self.assertIn("asynchronous scheduled polling", receipt)
        self.assertIn("Runner-held waiting: `false`", receipt)
        self.assertIn("child Issue created_at", receipt)

    def test_workflow_owns_two_separate_child_token_assignments(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "control-plane-reconcile.yml").read_text(encoding="utf-8")
        line = "CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}"
        self.assertEqual(workflow.count(line), 2)
        self.assertNotIn("deferred_poll.py", workflow)

    def test_workflow_has_bounded_event_monitor_and_schedule_fallback(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "control-plane-reconcile.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn("Governance Control Plane", workflow)
        self.assertIn('cron: "*/5 * * * *"', workflow)
        self.assertIn("attempts=20", workflow)
        self.assertIn("interval=30", workflow)
        self.assertIn('EVENT_NAME: ${{ github.event_name }}', workflow)
        self.assertNotIn("while true", workflow)


if __name__ == "__main__":
    unittest.main()
