from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "deferred_poll.py"
SPEC = importlib.util.spec_from_file_location("deferred_poll", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DeferredTerminalTests(unittest.TestCase):
    def bot(self, body: str) -> dict:
        return {"user": {"login": "github-actions[bot]"}, "body": body}

    def compute_success(self, task_id: str, *, complete: bool = True) -> str:
        lines = ["## COMPUTE_COMPLETED", "", f"- Task ID: `{task_id}`"]
        if complete:
            lines.extend(
                [
                    "- Artifact ID: `123`",
                    f"- Artifact digest: `{'a' * 64}`",
                    "- Artifact: https://github.com/a15280020511/compute-simulation-center/actions/runs/1/artifacts/123",
                ]
            )
        return "\n".join(lines)

    def api_success(self, task_id: str, *, complete: bool = True) -> str:
        lines = ["## API_COMPLETED 1/1", "", f"- Task ID: `{task_id}`"]
        if complete:
            lines.extend(
                [
                    "- Artifact ID: `456`",
                    f"- Artifact digest: `{'b' * 64}`",
                    "- Artifact: https://github.com/a15280020511/evidence-data-center/actions/runs/2/artifacts/456",
                ]
            )
        return "\n".join(lines)

    def api_failure(self, task_id: str, reason: str = "already accepted") -> str:
        return (
            "## API_REJECTED\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Reason: `{reason}`\n"
            "- Model calls: `0`"
        )

    def test_missing_task_id_is_not_terminal(self) -> None:
        body = "## EXECUTION_REJECTED\n\n模型调用：`0`"
        self.assertIsNone(
            MODULE.trusted_terminal(
                [self.bot(body)],
                route="expert",
                expected_task_id="gov-79-expert",
            )
        )

    def test_matching_later_fallback_wins(self) -> None:
        unbound = self.bot("## EXECUTION_REJECTED\n\n模型调用：`0`")
        bound = self.bot(
            "## EXECUTION_REJECTED\n\n"
            "- Task ID: `gov-79-expert`\n"
            "- Model calls: `0`"
        )
        heading, body, success = MODULE.trusted_terminal(
            [unbound, bound],
            route="expert",
            expected_task_id="gov-79-expert",
        )
        self.assertEqual(heading, "EXECUTION_REJECTED")
        self.assertIn("gov-79-expert", body)
        self.assertFalse(success)

    def test_wrong_task_is_ignored_until_matching_terminal(self) -> None:
        wrong = self.bot(self.compute_success("wrong-task"))
        self.assertIsNone(
            MODULE.trusted_terminal(
                [wrong],
                route="compute",
                expected_task_id="gov-1-compute",
            )
        )
        heading, _, success = MODULE.trusted_terminal(
            [wrong, self.bot(self.compute_success("gov-1-compute"))],
            route="compute",
            expected_task_id="gov-1-compute",
        )
        self.assertEqual(heading, "COMPUTE_COMPLETED")
        self.assertTrue(success)

    def test_incomplete_success_is_ignored_until_corrected(self) -> None:
        incomplete = self.bot(self.compute_success("gov-1-compute", complete=False))
        self.assertIsNone(
            MODULE.trusted_terminal(
                [incomplete],
                route="compute",
                expected_task_id="gov-1-compute",
            )
        )
        heading, _, success = MODULE.trusted_terminal(
            [incomplete, self.bot(self.compute_success("gov-1-compute"))],
            route="compute",
            expected_task_id="gov-1-compute",
        )
        self.assertEqual(heading, "COMPUTE_COMPLETED")
        self.assertTrue(success)

    def test_artifact_backed_success_survives_later_idempotency_rejection(self) -> None:
        task_id = "gov-90-intelligence"
        heading, body, success = MODULE.trusted_terminal(
            [
                self.bot(self.api_success(task_id)),
                self.bot(self.api_failure(task_id, "this API Issue is already accepted or running")),
            ],
            route="intelligence",
            expected_task_id=task_id,
        )
        self.assertEqual(heading, "API_COMPLETED")
        self.assertIn("Artifact ID: `456`", body)
        self.assertTrue(success)

    def test_latest_failure_is_returned_when_no_valid_success_exists(self) -> None:
        task_id = "gov-91-intelligence"
        heading, body, success = MODULE.trusted_terminal(
            [
                self.bot(self.api_failure(task_id, "first failure")),
                self.bot(self.api_failure(task_id, "latest failure")),
            ],
            route="intelligence",
            expected_task_id=task_id,
        )
        self.assertEqual(heading, "API_REJECTED")
        self.assertIn("latest failure", body)
        self.assertFalse(success)

    def test_incomplete_success_does_not_override_later_failure(self) -> None:
        task_id = "gov-92-intelligence"
        heading, body, success = MODULE.trusted_terminal(
            [
                self.bot(self.api_success(task_id, complete=False)),
                self.bot(self.api_failure(task_id, "latest failure")),
            ],
            route="intelligence",
            expected_task_id=task_id,
        )
        self.assertEqual(heading, "API_REJECTED")
        self.assertIn("latest failure", body)
        self.assertFalse(success)

    def test_non_bot_matching_terminal_is_ignored(self) -> None:
        rows = [
            {
                "user": {"login": "attacker"},
                "body": self.compute_success("gov-1-compute"),
            }
        ]
        self.assertIsNone(
            MODULE.trusted_terminal(
                rows,
                route="compute",
                expected_task_id="gov-1-compute",
            )
        )


if __name__ == "__main__":
    unittest.main()
