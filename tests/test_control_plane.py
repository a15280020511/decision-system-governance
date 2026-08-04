from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def valid_packet(self) -> dict:
        return {
            "schema_version": "governance-control-ticket-v3",
            "route": "compute",
            "ticket": {
                "operation": "descriptive_statistics",
                "inputs": {"data": [1, 2, 3]},
            },
            "wait_seconds": 600,
        }

    def test_accepts_one_step_compute_ticket_and_generates_task_id(self) -> None:
        status, child = self.run_prepare(self.valid_packet(), issue_number=42)
        self.assertTrue(status["accepted"])
        self.assertEqual(status["task_id"], "gov-42-compute")
        self.assertEqual(
            status["target_repository"],
            "a15280020511/compute-simulation-center",
        )
        self.assertEqual(child["task_id"], "gov-42-compute")

    def test_accepts_original_request_with_governance_status_suffix(self) -> None:
        request = json.dumps(self.valid_packet())
        body = (
            request
            + "\n\n---\n\n<!-- governance-status:start -->\n"
            + "## CONTROL_RUNNING\n<!-- governance-status:end -->\n"
        )
        status, _ = self.run_prepare(body)
        self.assertTrue(status["accepted"])

    def test_rejects_non_owner_actor(self) -> None:
        status, _ = self.run_prepare(self.valid_packet(), actor="attacker")
        self.assertFalse(status["accepted"])
        self.assertIn("repository owner", status["reason"])

    def test_rejects_secret_camel_case_and_authorization(self) -> None:
        packet = self.valid_packet()
        packet["ticket"]["nested"] = {"clientSecret": "x"}
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("clientSecret", status["reason"])

        packet = self.valid_packet()
        packet["ticket"]["nested"] = {"authorization": "Bearer x"}
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("authorization", status["reason"])

    def test_rejects_executable_fields(self) -> None:
        packet = self.valid_packet()
        packet["ticket"]["pythonCode"] = "print('x')"
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("pythonCode", status["reason"])

    def test_rejects_client_supplied_task_id(self) -> None:
        packet = self.valid_packet()
        packet["ticket"]["task_id"] = "client-id"
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("must omit task_id", status["reason"])

    def test_rejects_json_depth_and_long_string(self) -> None:
        packet = self.valid_packet()
        nested: dict = {}
        cursor = nested
        for _ in range(MODULE.MAX_JSON_DEPTH + 2):
            cursor["n"] = {}
            cursor = cursor["n"]
        packet["ticket"]["nested"] = nested
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("JSON depth exceeds", status["reason"])

        packet = self.valid_packet()
        packet["ticket"]["objective"] = "x" * (MODULE.MAX_JSON_STRING_CHARS + 1)
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("JSON string exceeds", status["reason"])

    def test_rejects_boolean_wait(self) -> None:
        packet = self.valid_packet()
        packet["wait_seconds"] = True
        status, _ = self.run_prepare(packet)
        self.assertFalse(status["accepted"])
        self.assertIn("integer between 60 and 2700", status["reason"])


class DuplicateTests(unittest.TestCase):
    def packet(self) -> str:
        return json.dumps(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {
                    "inputs": {"data": [1, 2, 3]},
                    "operation": "descriptive_statistics",
                },
            }
        )

    def row(self, number: int, *, state: str, reason: str, heading: str) -> dict:
        body = self.packet()
        if heading:
            body += (
                "\n\n---\n\n"
                + MODULE.STATUS_START
                + "\n"
                + heading
                + "\n"
                + MODULE.STATUS_END
            )
        return {
            "number": number,
            "title": "[control]",
            "body": body,
            "state": state,
            "state_reason": reason,
            "user": {"login": "a15280020511"},
        }

    def test_open_and_success_block_duplicates(self) -> None:
        fingerprint = MODULE._request_fingerprint(self.packet())
        rows = [
            self.row(10, state="open", reason="", heading="## CONTROL_RUNNING"),
            self.row(20, state="closed", reason="completed", heading="## CONTROL_COMPLETED"),
        ]
        duplicate = MODULE._find_duplicate_issue(
            rows, issue_number=30, fingerprint=fingerprint
        )
        self.assertEqual(duplicate["number"], 10)

    def test_failed_history_allows_identical_resubmission(self) -> None:
        fingerprint = MODULE._request_fingerprint(self.packet())
        rows = [
            self.row(
                10,
                state="closed",
                reason="not_planned",
                heading="## CONTROL_FAILED",
            )
        ]
        duplicate = MODULE._find_duplicate_issue(
            rows, issue_number=30, fingerprint=fingerprint
        )
        self.assertIsNone(duplicate)

    def test_fingerprint_ignores_wait_seconds(self) -> None:
        first = json.loads(self.packet())
        second = json.loads(self.packet())
        first["wait_seconds"] = 60
        second["wait_seconds"] = 2700
        self.assertEqual(
            MODULE._request_fingerprint(json.dumps(first)),
            MODULE._request_fingerprint(json.dumps(second)),
        )


class PaginationTests(unittest.TestCase):
    def test_comments_read_all_pages(self) -> None:
        def fake(method: str, path: str, *, token: str, payload=None):
            self.assertEqual(method, "GET")
            if path.endswith("page=1"):
                return [{"id": index} for index in range(100)]
            if path.endswith("page=2"):
                return [{"id": 100}]
            return []

        with mock.patch.object(MODULE, "_github_request", side_effect=fake):
            rows = MODULE._list_comments("token", "owner/repo", 9)
        self.assertEqual(len(rows), 101)
        self.assertEqual(rows[-1]["id"], 100)

    def test_running_attempts_can_be_on_second_page(self) -> None:
        rows = [
            {"user": {"login": "other"}, "body": "noise"}
            for _ in range(100)
        ]
        rows.append(
            {
                "user": {"login": "github-actions[bot]"},
                "body": "## CONTROL_RUNNING",
            }
        )
        with mock.patch.object(MODULE, "_list_comments", return_value=rows):
            self.assertEqual(MODULE._count_running_attempts("t", "r", 1), 1)


class TerminalTests(unittest.TestCase):
    def bot(self, body: str) -> dict:
        return {"user": {"login": "github-actions[bot]"}, "body": body}

    def compute_success(self, task_id: str = "gov-1-compute") -> str:
        return "\n".join(
            [
                "<!-- compute-status-run:1 -->",
                "## COMPUTE_COMPLETED",
                "",
                f"- Task ID: `{task_id}`",
                "- Artifact ID: `123`",
                f"- Artifact digest: `{'a' * 64}`",
                "- Artifact: https://github.com/a15280020511/compute-simulation-center/actions/runs/1/artifacts/123",
            ]
        )

    def expert_success(self, task_id: str = "gov-2-expert") -> str:
        return "\n".join(
            [
                "## EXECUTION_COMPLETED",
                "",
                f"- Task ID：`{task_id}`",
                "- Primary Artifact ID: `101`",
                f"- Primary Artifact digest: `{'b' * 64}`",
                "- Primary Artifact: https://github.com/a15280020511/expert-assessment-center/actions/runs/1/artifacts/101",
                "- Final attestation Artifact ID: `102`",
                f"- Final attestation Artifact digest: `{'c' * 64}`",
                "- Final attestation Artifact: https://github.com/a15280020511/expert-assessment-center/actions/runs/1/artifacts/102",
            ]
        )

    def test_only_trusts_actions_bot_and_expected_task(self) -> None:
        rows = [
            {"user": {"login": "attacker"}, "body": self.compute_success()},
            self.bot(self.compute_success()),
        ]
        heading, _, success = MODULE._trusted_terminal(
            rows, route="compute", expected_task_id="gov-1-compute"
        )
        self.assertEqual(heading, "COMPUTE_COMPLETED")
        self.assertTrue(success)

    def test_task_id_mismatch_is_terminal_security_failure(self) -> None:
        heading, excerpt, success = MODULE._trusted_terminal(
            [self.bot(self.compute_success("wrong-task"))],
            route="compute",
            expected_task_id="gov-1-compute",
        )
        self.assertEqual(heading, "CONTROL_CHILD_TASK_MISMATCH")
        self.assertIn("wrong-task", excerpt)
        self.assertFalse(success)

    def test_success_without_artifact_contract_is_failure(self) -> None:
        body = "## API_COMPLETED\n\n- Task ID: `gov-3-intelligence`"
        heading, excerpt, success = MODULE._trusted_terminal(
            [self.bot(body)],
            route="intelligence",
            expected_task_id="gov-3-intelligence",
        )
        self.assertEqual(heading, "CONTROL_CHILD_EVIDENCE_INVALID")
        self.assertIn("Artifact ID", excerpt)
        self.assertFalse(success)

    def test_expert_success_requires_primary_and_attestation(self) -> None:
        heading, _, success = MODULE._trusted_terminal(
            [self.bot(self.expert_success())],
            route="expert",
            expected_task_id="gov-2-expert",
        )
        self.assertEqual(heading, "EXECUTION_COMPLETED")
        self.assertTrue(success)

    def test_failure_requires_task_id_but_not_artifact(self) -> None:
        body = "## EXECUTION_REJECTED\n\n- Task ID: `gov-4-expert`\n- Model calls: `0`"
        heading, _, success = MODULE._trusted_terminal(
            [self.bot(body)],
            route="expert",
            expected_task_id="gov-4-expert",
        )
        self.assertEqual(heading, "EXECUTION_REJECTED")
        self.assertFalse(success)


class RecoveryTests(unittest.TestCase):
    def test_recovery_is_one_time_for_compute(self) -> None:
        calls: list[tuple[str, str, object]] = []

        def fake(method: str, path: str, *, token: str, payload=None):
            calls.append((method, path, payload))
            return {}

        with mock.patch.object(MODULE, "_github_request", side_effect=fake):
            attempted = MODULE._perform_one_recovery(
                token="t",
                repo="owner/compute",
                issue_number=7,
                route="compute",
                task_id="gov-7-compute",
                comments=[],
            )
        self.assertTrue(attempted)
        self.assertEqual([call[0] for call in calls], ["POST", "PATCH", "PATCH"])

        marker = MODULE._recovery_marker("gov-7-compute")
        comments = [{"body": marker, "user": {"login": "a15280020511"}}]
        with mock.patch.object(MODULE, "_github_request") as request:
            attempted = MODULE._perform_one_recovery(
                token="t",
                repo="owner/compute",
                issue_number=7,
                route="compute",
                task_id="gov-7-compute",
                comments=comments,
            )
        self.assertFalse(attempted)
        request.assert_not_called()

    def test_expert_recovery_reposts_exact_command_once(self) -> None:
        calls = []

        def fake(method: str, path: str, *, token: str, payload=None):
            calls.append((method, path, payload))
            return {}

        with mock.patch.object(MODULE, "_github_request", side_effect=fake):
            MODULE._perform_one_recovery(
                token="t",
                repo="owner/expert",
                issue_number=8,
                route="expert",
                task_id="gov-8-expert",
                comments=[],
            )
        self.assertEqual(calls[-1][2]["body"], "/run-expert-team gov-8-expert")


class ReconciliationTests(unittest.TestCase):
    def timed_out_issue(self) -> dict:
        request = json.dumps(
            {
                "schema_version": "governance-control-ticket-v3",
                "route": "compute",
                "ticket": {"operation": "descriptive_statistics"},
            }
        )
        receipt = "\n".join(
            [
                "## CONTROL_FAILED",
                "",
                "- Task ID: `gov-12-compute`",
                "- Route: `compute`",
                "- Child status: `CONTROL_TIMEOUT`",
                "- Child Issue: https://github.com/a15280020511/compute-simulation-center/issues/99",
            ]
        )
        return {
            "number": 12,
            "state": "closed",
            "body": MODULE._compose_text(request, receipt),
        }

    def test_recognizes_timeout_candidate(self) -> None:
        candidate = MODULE._reconciliation_candidate(self.timed_out_issue())
        self.assertEqual(candidate["task_id"], "gov-12-compute")
        self.assertEqual(candidate["child_issue_number"], 99)

    def test_reconcile_writes_late_success(self) -> None:
        issue = self.timed_out_issue()
        terminal_body = "\n".join(
            [
                "## COMPUTE_COMPLETED",
                "",
                "- Task ID: `gov-12-compute`",
                "- Artifact ID: `55`",
                f"- Artifact digest: `{'d' * 64}`",
                "- Artifact: https://github.com/a15280020511/compute-simulation-center/actions/runs/1/artifacts/55",
            ]
        )
        comments = [
            {"user": {"login": "github-actions[bot]"}, "body": terminal_body}
        ]
        writes = []

        def fake_request(method: str, path: str, *, token: str, payload=None):
            writes.append((method, path, payload))
            return {}

        args = type("Args", (), {"repository": "a15280020511/decision-system-governance"})()
        with mock.patch.dict(
            os.environ,
            {"GITHUB_TOKEN": "g", "CONTROL_PLANE_TOKEN": "c"},
            clear=False,
        ), mock.patch.object(MODULE, "_list_issues", return_value=[issue]), mock.patch.object(
            MODULE, "_list_comments", return_value=comments
        ), mock.patch.object(MODULE, "_github_request", side_effect=fake_request):
            MODULE.reconcile(args)

        self.assertEqual(len(writes), 2)
        self.assertIn("CONTROL_RECONCILED_LATE_SUCCESS", writes[0][2]["body"])
        self.assertEqual(writes[1][2]["state_reason"], "completed")


class ComposeTests(unittest.TestCase):
    def test_compose_replaces_old_status_block(self) -> None:
        request = (
            '{"schema_version":"governance-control-ticket-v3"}'
            "\n\n---\n\n<!-- governance-status:start -->\n"
            "old\n<!-- governance-status:end -->\n"
        )
        body = MODULE._compose_text(request, "## CONTROL_RUNNING")
        self.assertEqual(body.count(MODULE.STATUS_START), 1)
        self.assertNotIn("\nold\n", body)
        self.assertIn("## CONTROL_RUNNING", body)


if __name__ == "__main__":
    unittest.main()
