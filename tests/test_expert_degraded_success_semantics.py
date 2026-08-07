from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DEFERRED = _load("degraded_deferred_poll", "control-plane/deferred_poll.py")
ASYNC = _load("degraded_async_reconcile", "control-plane/async_reconcile.py")


def _degraded_terminal(task_id: str = "gov-42-expert") -> str:
    digest = "a" * 64
    return "\n".join(
        [
            "## EXECUTION_DEGRADED",
            "",
            f"- Task ID: `{task_id}`",
            "- Execution status: `success`",
            "- Completion mode: `degraded`",
            "- Quality status: `degraded_success`",
            "- Primary Artifact ID: `12345`",
            f"- Primary Artifact digest: `{digest}`",
            "- Primary Artifact: https://github.com/a15280020511/expert-assessment-center/actions/runs/1/artifacts/12345",
            "- Final attestation Artifact ID: `12345`",
            f"- Final attestation Artifact digest: `{digest}`",
            "- Final attestation Artifact: https://github.com/a15280020511/expert-assessment-center/actions/runs/1/artifacts/12345",
        ]
    )


class ExpertDegradedSuccessSemanticsTests(unittest.TestCase):
    def test_degraded_expert_with_valid_artifact_is_success_class(self) -> None:
        rows = [
            {
                "user": {"login": DEFERRED.CONTROL.TRUSTED_COMMENT_AUTHOR},
                "body": _degraded_terminal(),
            }
        ]
        terminal = DEFERRED.trusted_terminal(
            rows,
            route="expert",
            expected_task_id="gov-42-expert",
        )
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal[0], "EXECUTION_DEGRADED")
        self.assertTrue(terminal[2])

    def test_degraded_expert_without_artifact_is_not_trusted_success(self) -> None:
        rows = [
            {
                "user": {"login": DEFERRED.CONTROL.TRUSTED_COMMENT_AUTHOR},
                "body": "## EXECUTION_DEGRADED\n\n- Task ID: `gov-42-expert`",
            }
        ]
        self.assertIsNone(
            DEFERRED.trusted_terminal(
                rows,
                route="expert",
                expected_task_id="gov-42-expert",
            )
        )

    def test_async_renderer_distinguishes_degraded_from_full_and_failed(self) -> None:
        item = {
            "task_id": "gov-42-expert",
            "route": "expert",
            "child_issue_url": (
                "https://github.com/a15280020511/expert-assessment-center/issues/7"
            ),
        }
        degraded = ASYNC.render_terminal(
            item,
            ("EXECUTION_DEGRADED", _degraded_terminal(), True),
        )
        self.assertTrue(degraded.startswith("## CONTROL_DEGRADED"))
        self.assertIn("Governance completion class: `degraded-success`", degraded)

        full = ASYNC.render_terminal(
            item,
            ("EXECUTION_COMPLETED", "## EXECUTION_COMPLETED", True),
        )
        self.assertTrue(full.startswith("## CONTROL_COMPLETED"))

        failed = ASYNC.render_terminal(
            item,
            ("EXECUTION_FAILED", "## EXECUTION_FAILED", False),
        )
        self.assertTrue(failed.startswith("## CONTROL_FAILED"))

    def test_status_dictionary_declares_control_degraded_terminal(self) -> None:
        text = (ROOT / "control-plane" / "status-dictionary.json").read_text(
            encoding="utf-8"
        )
        self.assertIn('"CONTROL_DEGRADED"', text)
        self.assertIn("successful-but-degraded", text)


if __name__ == "__main__":
    unittest.main()
