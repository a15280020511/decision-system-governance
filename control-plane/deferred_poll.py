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
    """Return only a task-bound terminal whose success evidence is complete.

    A bot terminal with a missing/mismatched Task ID or an incomplete success
    Artifact is not accepted and is not treated as final. Polling continues so a
    bounded fallback or corrected audited receipt can arrive. If none arrives,
    the unchanged base poller ends fail-closed with CONTROL_TIMEOUT.
    """
    config = CONTROL.ROUTES[route]
    if not isinstance(rows, list):
        return None
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
        if success and CONTROL._artifact_contract_error(route, raw_body):
            continue
        return matched_status, raw_body, success
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="control-artifacts")
    parser.add_argument("--wait-seconds", required=True, type=int)
    args = parser.parse_args()
    CONTROL._trusted_terminal = trusted_terminal
    return CONTROL.poll(args)


if __name__ == "__main__":
    raise SystemExit(main())
