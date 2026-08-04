#!/usr/bin/env python3
"""Identity-hardened late terminal reconciliation entrypoint."""
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


CONTROL = _load("governance_control_plane_reconcile", ROOT / "control_plane.py")
DEFERRED = _load("governance_deferred_terminal_reconcile", ROOT / "deferred_poll.py")
BASE_CANDIDATE = CONTROL._reconciliation_candidate


def reconciliation_candidate(issue: Mapping[str, Any]) -> dict[str, Any] | None:
    """Accept only owner-authored canonical governance timeout records."""
    if not CONTROL._is_owned_control_issue(issue):
        return None
    candidate = BASE_CANDIDATE(issue)
    if not candidate:
        return None

    route = str(candidate["route"])
    issue_number = int(candidate["governance_issue_number"])
    expected_task_id = CONTROL._generated_task_id(issue_number, route)
    if str(candidate["task_id"]) != expected_task_id:
        return None
    expected_repository = str(CONTROL.ROUTES[route]["repository"])
    if str(candidate["child_repository"]) != expected_repository:
        return None
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()

    CONTROL._reconciliation_candidate = reconciliation_candidate
    CONTROL._trusted_terminal = DEFERRED.trusted_terminal
    return CONTROL.reconcile(args)


if __name__ == "__main__":
    raise SystemExit(main())
