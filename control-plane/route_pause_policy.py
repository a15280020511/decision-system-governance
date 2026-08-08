#!/usr/bin/env python3
"""Fail-closed route seal overlay for governance-controlled child centers.

This overlay is intentionally separate from the stable route table. Sealing a
center must not delete its repository, credentials, history, or schemas; it only
prevents new governance dispatches until the operator explicitly unseals it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PAUSED_ROUTES = {
    "intelligence": {
        "state": "sealed-security-hold",
        "reason": "Evidence/intelligence center is fully sealed pending security review; no child execution is permitted.",
        "resume": "explicit-operator-approved-unseal-required",
    }
}


def patch(control: Any) -> None:
    if getattr(control, "_route_pause_policy_patched", False):
        return
    control._route_pause_policy_patched = True
    original_prepare = control.prepare

    def prepare(args: argparse.Namespace) -> int:
        original_result = int(original_prepare(args))
        root = Path(args.output_dir)
        status_path = root / "prepare-status.json"
        if not status_path.is_file():
            return original_result
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return original_result
        if not isinstance(status, dict):
            return original_result

        route = str(status.get("route") or "")
        policy = PAUSED_ROUTES.get(route)
        if policy is None or status.get("accepted") is not True:
            return original_result

        status["accepted"] = False
        status["reason"] = (
            f"CONTROL_ROUTE_PAUSED: route={route}; state={policy['state']}; "
            f"{policy['reason']} Resume requires an explicit operator-approved governance code change."
        )
        status["route_pause_state"] = policy["state"]
        status["route_pause_resume"] = policy["resume"]
        status["target_repository"] = ""
        status["child_issue_title"] = ""
        status["child_command"] = ""
        control._write_json(status_path, status)

        child_path = root / "child-ticket.json"
        if child_path.exists():
            child_path.unlink()

        control._write_json(
            root / "route-pause-receipt.json",
            {
                "schema_version": "governance-route-pause-receipt-v1",
                "status": "BLOCKED",
                "route": route,
                "pause_state": policy["state"],
                "reason": policy["reason"],
                "resume": policy["resume"],
                "child_dispatch_created": False,
            },
        )
        control._write_output("accepted", "false")
        control._write_output("reason", status["reason"])
        control._write_output("target_repository", "")
        control._write_output("child_issue_title", "")
        control._write_output("child_command", "")
        return 2

    control.prepare = prepare
