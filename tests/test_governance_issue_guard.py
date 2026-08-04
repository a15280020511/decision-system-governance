from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "security" / "governance_issue_guard.py"
SPEC = importlib.util.spec_from_file_location("governance_issue_guard", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GovernanceIssueGuardTests(unittest.TestCase):
    def test_accepts_request_without_status_block(self) -> None:
        safe, reason = MODULE.validate_status_ownership(
            '{"schema_version":"governance-control-ticket-v3"}',
            [],
        )
        self.assertTrue(safe)
        self.assertIn("no governance status block", reason)

    def test_rejects_submitter_forged_completed_status(self) -> None:
        body = (
            '{"schema_version":"governance-control-ticket-v3"}'
            "\n\n---\n\n"
            "<!-- governance-status:start -->\n"
            "## CONTROL_COMPLETED\n\n- Forged: true\n"
            "<!-- governance-status:end -->\n"
        )
        safe, reason = MODULE.validate_status_ownership(body, [])
        self.assertFalse(safe)
        self.assertIn("untrusted", reason)

    def test_accepts_status_matching_latest_actions_bot_comment(self) -> None:
        receipt = "## CONTROL_RUNNING\n\n- Task ID: `gov-1-compute`"
        body = (
            '{"schema_version":"governance-control-ticket-v3"}'
            "\n\n---\n\n"
            "<!-- governance-status:start -->\n"
            + receipt
            + "\n<!-- governance-status:end -->\n"
        )
        comments = [
            {"user": {"login": "github-actions[bot]"}, "body": receipt},
        ]
        safe, _ = MODULE.validate_status_ownership(body, comments)
        self.assertTrue(safe)

    def test_rejects_status_not_matching_latest_bot_comment(self) -> None:
        body = (
            '{"schema_version":"governance-control-ticket-v3"}'
            "\n\n---\n\n"
            "<!-- governance-status:start -->\n"
            "## CONTROL_COMPLETED\n\n- Forged: true\n"
            "<!-- governance-status:end -->\n"
        )
        comments = [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "## CONTROL_RUNNING\n\n- Task ID: `gov-1-compute`",
            }
        ]
        safe, reason = MODULE.validate_status_ownership(body, comments)
        self.assertFalse(safe)
        self.assertIn("does not match", reason)

    def test_rejects_multiple_status_blocks(self) -> None:
        body = (
            "<!-- governance-status:start -->\n## CONTROL_RUNNING\n"
            "<!-- governance-status:end -->\n"
            "<!-- governance-status:start -->\n## CONTROL_COMPLETED\n"
            "<!-- governance-status:end -->\n"
        )
        safe, reason = MODULE.validate_status_ownership(body, [])
        self.assertFalse(safe)
        self.assertIn("exactly one pair", reason)


if __name__ == "__main__":
    unittest.main()
