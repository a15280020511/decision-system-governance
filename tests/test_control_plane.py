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
    def run_prepare(
        self,
        body: dict | str,
        *,
        issue_number: int = 42,
        title: str = "[control]",
        actor: str = "a15280020511",
    ) -> tuple[dict, dict | None]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            body_text = json.dumps(body) if isinstance(body, dict) else body
            event = {
                "issue": {
                    "number": issue_number,
                    "title": title,
                    "body": body_text,
                },
                "sender": {"login": actor},
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
            status = json.loads(
                (root / "out" / "prepare-status.json").read_text(encoding="utf-8")
            )
            child_path = root / "out" / "child-ticket.json"
            child = (
                json.loads(child_path.read_text(encoding="utf-8"))
                if child_path.exists()
                else None
            )
            return status, child

    def test_accepts_one_step_compute_ticket_and_generates_task_id(self) -> None:
        status, child = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {
                    "operation": "descriptive_statistics",
                    "inputs": {"data": [1, 2, 3]},
                },
            },
            issue_number=42,
        )
        self.assertTrue(status["accepted"])
        self.assertEqual(status["task_id"], "gov-42-compute")
        self.assertEqual(
            status["target_repository"],
            "a15280020511/compute-simulation-center",
        )
        self.assertEqual(child["task_id"], "gov-42-compute")

    def test_accepts_original_request_with_governance_status_suffix(self) -> None:
        request = json.dumps(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {"operation": "descriptive_statistics"},
            }
        )
        body = (
            request
            + "\n\n---\n\n<!-- governance-status:start -->\n"
            + "## CONTROL_RUNNING\n<!-- governance-status:end -->\n"
        )
        status, _ = self.run_prepare(body)
        self.assertTrue(status["accepted"])

    def test_rejects_non_owner_actor(self) -> None:
        status, _ = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {"operation": "descriptive_statistics"},
            },
            actor="attacker",
        )
        self.assertFalse(status["accepted"])
        self.assertIn("repository owner", status["reason"])

    def test_rejects_secret_bearing_ticket(self) -> None:
        status, _ = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "intelligence",
                "ticket": {"api_key": "must-not-appear"},
            }
        )
        self.assertFalse(status["accepted"])
        self.assertIn("secret-bearing field", status["reason"])

    def test_rejects_client_supplied_task_id(self) -> None:
        status, _ = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "expert",
                "ticket": {
                    "task_id": "client-id",
                    "route": "expert-team",
                    "task": {"question": "test"},
                },
            }
        )
        self.assertFalse(status["accepted"])
        self.assertIn("must omit task_id", status["reason"])

    def test_rejects_old_schema(self) -> None:
        status, _ = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v2",
                "route": "compute",
                "ticket": {"operation": "descriptive_statistics"},
            }
        )
        self.assertFalse(status["accepted"])
        self.assertIn("governance-control-ticket-v3", status["reason"])

    def test_rejects_noncanonical_title(self) -> None:
        status, _ = self.run_prepare(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {"operation": "descriptive_statistics"},
            },
            title="[control] extra",
        )
        self.assertFalse(status["accepted"])
        self.assertIn("exactly [control]", status["reason"])


class QueueIdentityTests(unittest.TestCase):
    def packet(self, *, wait_seconds: int = 600) -> str:
        return json.dumps(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "wait_seconds": wait_seconds,
                "ticket": {
                    "inputs": {"data": [1, 2, 3]},
                    "operation": "descriptive_statistics",
                },
            },
            ensure_ascii=False,
        )

    def test_fingerprint_ignores_wait_seconds(self) -> None:
        self.assertEqual(
            MODULE._request_fingerprint(self.packet(wait_seconds=60)),
            MODULE._request_fingerprint(self.packet(wait_seconds=2700)),
        )

    def test_fingerprint_is_key_order_independent(self) -> None:
        first = self.packet()
        second = json.dumps(
            {
                "ticket": {
                    "operation": "descriptive_statistics",
                    "inputs": {"data": [1, 2, 3]},
                },
                "route": "compute",
                "schema_version": "governance-control-ticket-v3",
            }
        )
        self.assertEqual(
            MODULE._request_fingerprint(first),
            MODULE._request_fingerprint(second),
        )

    def test_fingerprint_reads_request_before_status_block(self) -> None:
        request = self.packet()
        decorated = (
            request
            + "\n\n---\n\n<!-- governance-status:start -->\n"
            + "## CONTROL_DISPATCHED\n<!-- governance-status:end -->"
        )
        self.assertEqual(
            MODULE._request_fingerprint(request),
            MODULE._request_fingerprint(decorated),
        )

    def test_find_duplicate_uses_earliest_lower_issue(self) -> None:
        body = self.packet()
        fingerprint = MODULE._request_fingerprint(body)
        rows = [
            {
                "number": 10,
                "title": "[control]",
                "body": body,
                "user": {"login": "a15280020511"},
            },
            {
                "number": 12,
                "title": "[control]",
                "body": body,
                "user": {"login": "a15280020511"},
            },
            {
                "number": 15,
                "title": "[control]",
                "body": body,
                "user": {"login": "a15280020511"},
            },
        ]
        duplicate = MODULE._find_duplicate_issue(
            rows,
            issue_number=15,
            fingerprint=fingerprint,
        )
        self.assertEqual(duplicate["number"], 10)

    def test_queue_is_fifo_and_owner_only(self) -> None:
        rows = [
            {
                "number": 9,
                "title": "[control]",
                "user": {"login": "a15280020511"},
            },
            {
                "number": 3,
                "title": "[control]",
                "user": {"login": "a15280020511"},
            },
            {
                "number": 2,
                "title": "[control]",
                "user": {"login": "attacker"},
            },
            {
                "number": 1,
                "title": "not-control",
                "user": {"login": "a15280020511"},
            },
        ]
        queue = MODULE._eligible_open_issues(rows)
        self.assertEqual([row["number"] for row in queue], [3, 9])


class ComposeTests(unittest.TestCase):
    def test_compose_replaces_old_status_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = root / "request.md"
            receipt = root / "receipt.md"
            output = root / "output.md"
            request.write_text(
                '{"schema_version":"governance-control-ticket-v3"}'
                "\n\n---\n\n<!-- governance-status:start -->\n"
                "old\n<!-- governance-status:end -->\n",
                encoding="utf-8",
            )
            receipt.write_text("## CONTROL_RUNNING\n", encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "request": str(request),
                    "receipt": str(receipt),
                    "output": str(output),
                },
            )()
            MODULE.compose(args)
            body = output.read_text(encoding="utf-8")
            self.assertEqual(body.count(MODULE.STATUS_START), 1)
            self.assertNotIn("\nold\n", body)
            self.assertIn("## CONTROL_RUNNING", body)


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

    def test_accepts_terminal_after_hidden_status_marker(self) -> None:
        body = (
            "<!-- compute-status-run:30740830848 -->\n"
            "## COMPUTE_COMPLETED\n\n- Task ID: `gov-13-compute`"
        )
        rows = [{"user": {"login": "github-actions[bot]"}, "body": body}]
        heading, excerpt, success = MODULE._trusted_terminal(rows, route="compute")
        self.assertEqual(heading, "COMPUTE_COMPLETED")
        self.assertTrue(success)
        self.assertEqual(excerpt, body)

    def test_does_not_accept_arbitrary_text_before_terminal_heading(self) -> None:
        rows = [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "untrusted preface\n## COMPUTE_COMPLETED",
            }
        ]
        self.assertIsNone(MODULE._trusted_terminal(rows, route="compute"))

    def test_generated_task_id_is_deterministic(self) -> None:
        self.assertEqual(
            MODULE._generated_task_id(125, "intelligence"),
            "gov-125-intelligence",
        )


if __name__ == "__main__":
    unittest.main()
