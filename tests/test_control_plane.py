from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "control_plane.py"
SPEC = importlib.util.spec_from_file_location("governance_control_plane", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareTests(unittest.TestCase):
    def run_prepare(self, body: dict, command: str) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            event = {
                "issue": {"title": "[control] test", "body": json.dumps(body)},
                "comment": {"body": command, "user": {"login": "a15280020511"}},
                "repository": {"owner": {"login": "a15280020511"}},
            }
            event_path = root / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            args = type(
                "Args",
                (),
                {"event_path": str(event_path), "output_dir": str(root / "out")},
            )()
            old_output = os.environ.pop("GITHUB_OUTPUT", None)
            try:
                MODULE.prepare(args)
            finally:
                if old_output is not None:
                    os.environ["GITHUB_OUTPUT"] = old_output
            return json.loads(
                (root / "out" / "prepare-status.json").read_text(encoding="utf-8")
            )

    def test_accepts_exact_compute_wrapper(self) -> None:
        task_id = "compute-20260802-001"
        status = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v2",
                "task_id": task_id,
                "route": "compute",
                "ticket": {
                    "task_id": task_id,
                    "operation": "descriptive_statistics",
                    "inputs": {"values": [1, 2, 3]},
                },
            },
            f"/dispatch-control {task_id}",
        )
        self.assertTrue(status["accepted"])
        self.assertEqual(
            status["target_repository"],
            "a15280020511/compute-simulation-center",
        )

    def test_rejects_secret_bearing_ticket(self) -> None:
        task_id = "api-20260802-001"
        status = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v2",
                "task_id": task_id,
                "route": "intelligence",
                "ticket": {
                    "task_id": task_id,
                    "api_key": "must-not-appear",
                },
            },
            f"/dispatch-control {task_id}",
        )
        self.assertFalse(status["accepted"])
        self.assertIn("secret-bearing field", status["reason"])

    def test_rejects_command_ticket_mismatch(self) -> None:
        status = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v2",
                "task_id": "expert-20260802-001",
                "route": "expert",
                "ticket": {
                    "task_id": "expert-20260802-001",
                    "route": "expert-team",
                    "task": {"question": "test"},
                    "approved_budget": {
                        "calls": 4,
                        "maximum_recovery_calls": 1,
                        "cost_policy": "unbounded_with_anomaly_guard",
                    },
                },
            },
            "/dispatch-control expert-20260802-999",
        )
        self.assertFalse(status["accepted"])
        self.assertIn("exactly match", status["reason"])

    def test_rejects_removed_notify_field(self) -> None:
        task_id = "compute-20260802-002"
        status = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v2",
                "task_id": task_id,
                "route": "compute",
                "notify": True,
                "ticket": {
                    "task_id": task_id,
                    "operation": "descriptive_statistics",
                    "inputs": {"values": [1, 2, 3]},
                },
            },
            f"/dispatch-control {task_id}",
        )
        self.assertFalse(status["accepted"])
        self.assertIn("unknown control ticket fields", status["reason"])


class TerminalTests(unittest.TestCase):
    def test_only_trusts_actions_bot(self) -> None:
        rows = [
            {
                "user": {"login": "attacker"},
                "body": "## EXECUTION_COMPLETED\nfake",
            },
            {
                "user": {"login": "github-actions[bot]"},
                "body": "## EXECUTION_FAILED\nreal",
            },
        ]
        heading, _, success = MODULE._trusted_terminal(rows, route="expert")
        self.assertEqual(heading, "EXECUTION_FAILED")
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
