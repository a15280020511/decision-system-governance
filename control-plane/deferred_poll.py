#!/usr/bin/env python3
"""Fail-closed child terminal polling with deferred provisional evidence."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_control_plane_runtime", ROOT / "control_plane.py")
HTTP = _load("governance_deferred_poll_http", ROOT / "resilient_http.py")
CONTROL._github_request = HTTP.github_request


def trusted_terminal(
    rows: Any,
    *,
    route: str,
    expected_task_id: str = "",
) -> tuple[str, str, bool] | None:
    """Return a task-bound terminal without allowing success revocation.

    A bot terminal with a missing/mismatched Task ID or an incomplete success
    Artifact is provisional and is never accepted. A valid completed success is
    absorbing for its Task ID: later duplicate-admission, already-running or
    replay rejection comments cannot revoke an Artifact-backed completion. When
    no valid success exists, the latest trusted task-bound failure is returned.

    Expert ``EXECUTION_DEGRADED`` is a successful-but-degraded delivery class,
    not a business failure. It still must pass the exact same Artifact identity
    contract as ``EXECUTION_COMPLETED`` before governance accepts it.
    """
    config = CONTROL.ROUTES[route]
    if not isinstance(rows, list):
        return None

    latest_failure: tuple[str, str, bool] | None = None
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != CONTROL.TRUSTED_COMMENT_AUTHOR:
            continue

        raw_body = str(row.get("body") or "").strip()
        match_body = CONTROL._normalized_terminal_body(raw_body)
        matched_status = ""
        success = False

        # Degraded expert delivery is terminal and usable. Keep it distinct from
        # full success, but classify it as successful for queue/finalization
        # semantics after the normal success Artifact contract is verified.
        if route == "expert" and match_body.startswith("## EXECUTION_DEGRADED"):
            matched_status = "EXECUTION_DEGRADED"
            success = True
        else:
            for prefix in config["success"]:
                if match_body.startswith(prefix):
                    matched_status = prefix.removeprefix("## ").strip()
                    success = True
                    break
            if not matched_status:
                for prefix in config["failure"]:
                    if match_body.startswith(prefix):
                        matched_status = prefix.removeprefix("## ").strip()
                        break
        if not matched_status:
            continue

        actual_task_id = CONTROL._extract_task_id(raw_body)
        if expected_task_id and actual_task_id != expected_task_id:
            continue
        if success:
            if CONTROL._artifact_contract_error(route, raw_body):
                continue
            return matched_status, raw_body, True
        if latest_failure is None:
            latest_failure = (matched_status, raw_body, False)

    return latest_failure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="control-artifacts")
    parser.add_argument("--wait-seconds", required=True, type=int)
    args = parser.parse_args()
    CONTROL._trusted_terminal = trusted_terminal
    return CONTROL.poll(args)


if __name__ == "__main__":
    raise SystemExit(main())
