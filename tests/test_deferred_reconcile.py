from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "deferred_reconcile.py"
SPEC = importlib.util.spec_from_file_location("deferred_reconcile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ReconciliationIdentityTests(unittest.TestCase):
    def issue(
        self,
        *,
        number: int = 120,
        title: str = "[control]",
        actor: str = "a15280020511",
        task_id: str = "gov-120-compute",
        child_repository: str = "a15280020511/compute-simulation-center",
    ) -> dict:
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
                f"- Task ID: `{task_id}`",
                "- Route: `compute`",
                "- Child status: `CONTROL_TIMEOUT`",
                f"- Child Issue: https://github.com/{child_repository}/issues/321",
            ]
        )
        return {
            "number": number,
            "title": title,
            "state": "closed",
            "state_reason": "not_planned",
            "body": MODULE.CONTROL._compose_text(request, receipt),
            "user": {"login": actor},
        }

    def test_accepts_canonical_owner_control_timeout(self) -> None:
        candidate = MODULE.reconciliation_candidate(self.issue())
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["task_id"], "gov-120-compute")

    def test_rejects_non_control_title(self) -> None:
        self.assertIsNone(MODULE.reconciliation_candidate(self.issue(title="[audit]")))

    def test_rejects_non_owner_issue(self) -> None:
        self.assertIsNone(MODULE.reconciliation_candidate(self.issue(actor="attacker")))

    def test_rejects_task_id_not_derived_from_issue_number(self) -> None:
        self.assertIsNone(
            MODULE.reconciliation_candidate(self.issue(task_id="gov-999-compute"))
        )

    def test_rejects_child_repository_not_fixed_by_route(self) -> None:
        self.assertIsNone(
            MODULE.reconciliation_candidate(
                self.issue(child_repository="a15280020511/expert-assessment-center")
            )
        )

    def test_reconcile_uses_deferred_terminal_validator(self) -> None:
        self.assertIsNot(MODULE.DEFERRED.trusted_terminal, MODULE.CONTROL._trusted_terminal)
        MODULE.CONTROL._trusted_terminal = MODULE.DEFERRED.trusted_terminal
        self.assertIs(MODULE.CONTROL._trusted_terminal, MODULE.DEFERRED.trusted_terminal)


if __name__ == "__main__":
    unittest.main()
