#!/usr/bin/env python3
"""True asynchronous governance reconciliation for open dispatched tasks.

The dispatch worker never waits for a child terminal.  This reconciler polls
only the oldest open CONTROL_DISPATCHED Issue, preserves the single global slot,
validates trusted bot and Artifact contracts, and wakes the next FIFO task only
after the current Issue reaches a terminal state.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
POLL_INTERVAL_SECONDS = 300
RECOVERY_AFTER_SECONDS = 900
ROUTE_DEADLINES = {
    "intelligence": 7_200,
    "compute": 7_200,
    "expert": 10_800,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_async_control", ROOT / "control_plane.py")
DEFERRED = _load("governance_async_terminal", ROOT / "deferred_poll.py")
HTTP = _load("governance_async_http", ROOT / "resilient_http.py")
CONTROL._github_request = HTTP.github_request
CONTROL._trusted_terminal = DEFERRED.trusted_terminal


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("issue updated_at is missing")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def candidate(issue: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(issue.get("state") or "") != "open" or not CONTROL._is_owned_control_issue(issue):
        return None
    body = str(issue.get("body") or "")
    if CONTROL._governance_status_heading(body) != "## CONTROL_DISPATCHED":
        return None
    route_match = CONTROL.ROUTE_RE.search(body)
    task_match = CONTROL.TASK_ID_RE.search(body)
    child_match = CONTROL.CHILD_ISSUE_RE.search(body)
    if not route_match or not task_match or not child_match:
        return None
    route = route_match.group(1)
    issue_number = int(issue.get("number") or 0)
    if route not in CONTROL.ROUTES or issue_number <= 0:
        return None
    task_id = task_match.group(1)
    child_repository = child_match.group(1)
    child_issue_number = int(child_match.group(2))
    if task_id != CONTROL._generated_task_id(issue_number, route):
        return None
    if child_repository != CONTROL.ROUTES[route]["repository"]:
        return None
    return {
        "governance_issue_number": issue_number,
        "governance_body": body,
        "route": route,
        "task_id": task_id,
        "child_repository": child_repository,
        "child_issue_number": child_issue_number,
        "child_issue_url": f"https://github.com/{child_repository}/issues/{child_issue_number}",
        "updated_at": _parse_time(issue.get("updated_at")),
    }


def age_seconds(item: Mapping[str, Any], now: datetime | None = None) -> int:
    observed = now or datetime.now(timezone.utc)
    updated_at = item["updated_at"]
    if not isinstance(updated_at, datetime):
        raise TypeError("candidate updated_at must be datetime")
    return max(0, int((observed - updated_at).total_seconds()))


def render_terminal(item: Mapping[str, Any], terminal: tuple[str, str, bool]) -> str:
    heading, child_body, success = terminal
    return "\n".join([
        "## CONTROL_COMPLETED" if success else "## CONTROL_FAILED",
        "",
        f"- Task ID: `{item['task_id']}`",
        f"- Route: `{item['route']}`",
        f"- Child status: `{heading}`",
        f"- Child Issue: {item['child_issue_url']}",
        "- Reconciliation mode: `asynchronous scheduled polling`",
        f"- Poll interval target: `{POLL_INTERVAL_SECONDS} seconds`",
        "- Runner-held waiting: `false`",
        "- Authoritative result: `trusted github-actions[bot] terminal comment and validated child Artifact`",
        "",
        "<details><summary>Trusted terminal excerpt</summary>",
        "",
        child_body[:12000],
        "",
        "</details>",
    ])


def render_deadline(item: Mapping[str, Any], elapsed: int) -> str:
    return "\n".join([
        "## CONTROL_FAILED",
        "",
        f"- Task ID: `{item['task_id']}`",
        f"- Route: `{item['route']}`",
        "- Child status: `CONTROL_ASYNC_DEADLINE_EXCEEDED`",
        f"- Child Issue: {item['child_issue_url']}",
        f"- Elapsed seconds: `{elapsed}`",
        f"- Route deadline seconds: `{ROUTE_DEADLINES[item['route']]}`",
        "- Reconciliation mode: `asynchronous scheduled polling`",
        "- Runner-held waiting: `false`",
        "- Late trusted terminal reconciliation: `enabled`",
        "- Business success claimed: `false`",
    ])


def _finalize(
    *,
    governance_token: str,
    repository: str,
    item: Mapping[str, Any],
    receipt: str,
    success: bool,
) -> None:
    issue_number = int(item["governance_issue_number"])
    body = CONTROL._compose_text(str(item["governance_body"]), receipt)
    CONTROL._github_request(
        "POST",
        f"/repos/{repository}/issues/{issue_number}/comments",
        token=governance_token,
        payload={"body": receipt},
    )
    CONTROL._github_request(
        "PATCH",
        f"/repos/{repository}/issues/{issue_number}",
        token=governance_token,
        payload={
            "body": body,
            "state": "closed",
            "state_reason": "completed" if success else "not_planned",
        },
    )


def _wake_next(governance_token: str, repository: str) -> None:
    CONTROL._github_request(
        "POST",
        f"/repos/{repository}/actions/workflows/control-plane-ticket.yml/dispatches",
        token=governance_token,
        payload={"ref": "main"},
    )


def reconcile(repository: str, *, now: datetime | None = None) -> dict[str, Any]:
    governance_token = os.getenv("GITHUB_TOKEN", "")
    child_token = os.getenv("CONTROL_PLANE_TOKEN", "")
    open_issues = CONTROL._eligible_open_issues(
        CONTROL._list_issues(governance_token, repository, state="open")
    )
    candidates = [item for item in (candidate(issue) for issue in open_issues) if item]
    if not candidates:
        return {"status": "NO_ASYNC_TASK", "checked": 0, "finalized": 0, "waiting": 0}

    item = sorted(candidates, key=lambda row: int(row["governance_issue_number"]))[0]
    comments = CONTROL._list_comments(
        child_token,
        str(item["child_repository"]),
        int(item["child_issue_number"]),
    )
    terminal = DEFERRED.trusted_terminal(
        comments,
        route=str(item["route"]),
        expected_task_id=str(item["task_id"]),
    )
    elapsed = age_seconds(item, now)
    recovery_attempted = False
    if terminal:
        receipt = render_terminal(item, terminal)
        _finalize(
            governance_token=governance_token,
            repository=repository,
            item=item,
            receipt=receipt,
            success=terminal[2],
        )
        _wake_next(governance_token, repository)
        return {
            "status": "ASYNC_TERMINAL_FINALIZED",
            "checked": 1,
            "finalized": 1,
            "waiting": 0,
            "success": terminal[2],
            "child_status": terminal[0],
            "elapsed_seconds": elapsed,
            "recovery_attempted": False,
        }

    deadline = ROUTE_DEADLINES[str(item["route"])]
    if elapsed >= deadline:
        receipt = render_deadline(item, elapsed)
        _finalize(
            governance_token=governance_token,
            repository=repository,
            item=item,
            receipt=receipt,
            success=False,
        )
        _wake_next(governance_token, repository)
        return {
            "status": "ASYNC_DEADLINE_FINALIZED",
            "checked": 1,
            "finalized": 1,
            "waiting": 0,
            "success": False,
            "child_status": "CONTROL_ASYNC_DEADLINE_EXCEEDED",
            "elapsed_seconds": elapsed,
            "recovery_attempted": False,
        }

    if elapsed >= RECOVERY_AFTER_SECONDS and not CONTROL._trusted_bot_activity(comments):
        recovery_attempted = CONTROL._perform_one_recovery(
            token=child_token,
            repo=str(item["child_repository"]),
            issue_number=int(item["child_issue_number"]),
            route=str(item["route"]),
            task_id=str(item["task_id"]),
            comments=comments,
        )
    return {
        "status": "ASYNC_WAITING",
        "checked": 1,
        "finalized": 0,
        "waiting": 1,
        "success": None,
        "child_status": None,
        "elapsed_seconds": elapsed,
        "deadline_seconds": deadline,
        "recovery_attempted": recovery_attempted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    result = reconcile(args.repository)
    for key, value in result.items():
        CONTROL._write_output(key, str(value).lower() if isinstance(value, bool) else value)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
