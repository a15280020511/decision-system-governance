#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "route_pause_policy_test_runtime",
    ROOT / "control-plane" / "route_pause_policy.py",
)
assert SPEC is not None and SPEC.loader is not None
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class DummyControl:
    def __init__(self, route: str) -> None:
        self.route = route
        self.outputs: dict[str, str] = {}

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_output(self, name: str, value: object) -> None:
        self.outputs[name] = str(value)

    def prepare(self, args: argparse.Namespace) -> int:
        root = Path(args.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        status = {
            "accepted": True,
            "reason": "control ticket accepted",
            "route": self.route,
            "target_repository": "a15280020511/evidence-data-center" if self.route == "intelligence" else "a15280020511/compute-simulation-center",
            "child_issue_title": "[child] example",
            "child_command": "",
        }
        self._write_json(root / "prepare-status.json", status)
        self._write_json(root / "child-ticket.json", {"task_id": "example"})
        return 0


class RoutePausePolicyTests(unittest.TestCase):
    def test_intelligence_route_is_blocked_and_child_ticket_removed(self) -> None:
        control = DummyControl("intelligence")
        POLICY.patch(control)
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(output_dir=directory)
            result = control.prepare(args)
            status = json.loads(Path(directory, "prepare-status.json").read_text(encoding="utf-8"))
            receipt = json.loads(Path(directory, "route-pause-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertFalse(status["accepted"])
            self.assertEqual(status["route_pause_state"], "paused-risk-review")
            self.assertEqual(status["target_repository"], "")
            self.assertEqual(status["child_issue_title"], "")
            self.assertFalse(Path(directory, "child-ticket.json").exists())
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertFalse(receipt["child_dispatch_created"])
            self.assertEqual(control.outputs["accepted"], "false")

    def test_compute_route_is_unchanged(self) -> None:
        control = DummyControl("compute")
        POLICY.patch(control)
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(output_dir=directory)
            result = control.prepare(args)
            status = json.loads(Path(directory, "prepare-status.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertTrue(status["accepted"])
            self.assertTrue(Path(directory, "child-ticket.json").exists())
            self.assertFalse(Path(directory, "route-pause-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
