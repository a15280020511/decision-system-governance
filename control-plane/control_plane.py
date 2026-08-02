#!/usr/bin/env python3
"""Governance control plane for one-step GPT task submission."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

API_ROOT = "https://api.github.com"
OWNER = "a15280020511"
SCHEMA_VERSION = "governance-control-ticket-v3"
ROUTES = {
    "intelligence": {
        "repository": f"{OWNER}/evidence-data-center",
        "issue_prefix": "[api]",
        "success": ("## API_COMPLETED", "## API_PARTIAL"),
        "failure": ("## API_BLOCKED", "## API_FAILED", "## API_REJECTED"),
    },
    "compute": {
        "repository": f"{OWNER}/compute-simulation-center",
        "issue_prefix": "[compute]",
        "success": ("## COMPUTE_COMPLETED",),
        "failure": ("## COMPUTE_FAILED", "## COMPUTE_REJECTED"),
    },
    "expert": {
        "repository": f"{OWNER}/expert-assessment-center",
        "issue_prefix": "[execution]",
        "success": ("## EXECUTION_COMPLETED",),
        "failure": (
            "## EXECUTION_FAILED",
            "## EXECUTION_DEGRADED",
            "## EXECUTION_REJECTED",
        ),
    },
}
SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:secret|token|password|passwd|private_key|api_key|sendkey|sckey)(?:$|_)",
    re.IGNORECASE,
)
MAX_BODY_CHARS = 100_000
TRUSTED_COMMENT_AUTHOR = "github-actions[bot]"
MAX_ISSUE_SCAN_PAGES = 5


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_json_text(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def _write_output(name: str, value: Any) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    normalized = str(value).replace("\r", " ").replace("\n", " ")
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={normalized}\n")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _forbidden_secret_path(value: Any, path: str = "ticket") -> str:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if SECRET_KEY_RE.search(key):
                return f"{path}.{key}"
            nested = _forbidden_secret_path(item, f"{path}.{key}")
            if nested:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = _forbidden_secret_path(item, f"{path}[{index}]")
            if nested:
                return nested
    return ""


def _event_data(path: str) -> tuple[str, str, str, int]:
    event = _load_json_text(Path(path).read_text(encoding="utf-8"))
    issue = event.get("issue") if isinstance(event.get("issue"), Mapping) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), Mapping) else {}
    repository = event.get("repository") if isinstance(event.get("repository"), Mapping) else {}
    owner = repository.get("owner") if isinstance(repository.get("owner"), Mapping) else {}
    actor = str(sender.get("login") or owner.get("login") or "")
    return (
        str(issue.get("title") or ""),
        str(issue.get("body") or ""),
        actor,
        int(issue.get("number") or 0),
    )


def _generated_task_id(issue_number: int, route: str) -> str:
    return f"gov-{issue_number}-{route}"


def prepare(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    packet: dict[str, Any] = {}
    issue_number = 0
    actor = ""
    issue_title = ""
    issue_body = ""

    try:
        issue_title, issue_body, actor, issue_number = _event_data(args.event_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"event parse failed: {exc}")

    if issue_title != "[control]":
        errors.append("governance issue title must be exactly [control]")
    if issue_number <= 0:
        errors.append("governance issue number is missing")
    if len(issue_body) > MAX_BODY_CHARS:
        errors.append(f"issue body exceeds {MAX_BODY_CHARS} characters")

    try:
        raw = _load_json_text(issue_body)
        if not isinstance(raw, dict):
            raise ValueError("control ticket must be a JSON object")
        packet = raw
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"control ticket JSON invalid: {exc}")

    allowed = {"schema_version", "route", "ticket", "wait_seconds"}
    unexpected = sorted(set(packet) - allowed)
    if unexpected:
        errors.append(f"unknown control ticket fields: {unexpected}")

    if packet.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    route = packet.get("route")
    if route not in ROUTES:
        errors.append(f"route must be one of {sorted(ROUTES)}")
        route = ""

    ticket = packet.get("ticket")
    if not isinstance(ticket, dict):
        errors.append("ticket must be the child-center ticket object without task_id")
        ticket = {}
    if "task_id" in ticket:
        errors.append("child ticket must omit task_id; governance generates it from the Issue number")

    forbidden_path = _forbidden_secret_path(ticket)
    if forbidden_path:
        errors.append(f"secret-bearing field is forbidden in issue content: {forbidden_path}")

    wait_seconds = packet.get("wait_seconds", 2400)
    if (
        not isinstance(wait_seconds, int)
        or isinstance(wait_seconds, bool)
        or not 60 <= wait_seconds <= 2700
    ):
        errors.append("wait_seconds must be an integer between 60 and 2700")
        wait_seconds = 2400

    task_id = _generated_task_id(issue_number, route) if issue_number > 0 and route else ""
    accepted = not errors
    route_config = ROUTES.get(route, {})
    status = {
        "accepted": accepted,
        "reason": "; ".join(errors) if errors else "control ticket accepted",
        "actor": actor,
        "governance_issue_number": issue_number,
        "task_id": task_id,
        "route": route,
        "wait_seconds": wait_seconds,
        "target_repository": route_config.get("repository", ""),
        "child_issue_title": (
            f"{route_config.get('issue_prefix', '')} {task_id} via governance"
            if accepted
            else ""
        ),
        "child_command": f"/run-expert-team {task_id}" if route == "expert" else "",
    }
    _write_json(root / "prepare-status.json", status)
    if accepted:
        child_ticket = dict(ticket)
        child_ticket["task_id"] = task_id
        _write_json(root / "child-ticket.json", child_ticket)

    for key, value in status.items():
        if key in {
            "accepted",
            "reason",
            "governance_issue_number",
            "task_id",
            "route",
            "wait_seconds",
            "target_repository",
            "child_issue_title",
            "child_command",
        }:
            _write_output(key, str(value).lower() if isinstance(value, bool) else value)
    return 0 if accepted else 2


def _github_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None = None,
) -> Any:
    if not token:
        raise RuntimeError("CONTROL_PLANE_TOKEN is not configured")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        API_ROOT + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "decision-system-governance-control-plane",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(
            f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API {method} {path} network failure: {exc}") from exc
    return json.loads(raw) if raw else None


def _find_existing_child_issue(token: str, repo: str, title: str) -> Mapping[str, Any] | None:
    for page in range(1, MAX_ISSUE_SCAN_PAGES + 1):
        rows = _github_request(
            "GET",
            f"/repos/{repo}/issues?state=all&per_page=100&page={page}",
            token=token,
        )
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, Mapping) or row.get("pull_request"):
                continue
            if str(row.get("title") or "") == title:
                return row
        if len(rows) < 100:
            return None
    return None


def _comment_exists(token: str, repo: str, issue_number: int, body: str) -> bool:
    rows = _github_request(
        "GET",
        f"/repos/{repo}/issues/{issue_number}/comments?per_page=100",
        token=token,
    )
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(row, Mapping) and str(row.get("body") or "").strip() == body
        for row in rows
    )


def dispatch(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    status = _load_json_text((root / "prepare-status.json").read_text(encoding="utf-8"))
    if status.get("accepted") is not True:
        raise SystemExit("refusing to dispatch an unaccepted control ticket")

    token = os.getenv("CONTROL_PLANE_TOKEN", "")
    repo = str(status["target_repository"])
    title = str(status["child_issue_title"])
    existing = _find_existing_child_issue(token, repo, title)
    reused = existing is not None

    if existing is None:
        ticket_text = (root / "child-ticket.json").read_text(encoding="utf-8").strip()
        issue = _github_request(
            "POST",
            f"/repos/{repo}/issues",
            token=token,
            payload={"title": title, "body": ticket_text},
        )
    else:
        issue = existing

    issue_number = int(issue["number"])
    command = str(status.get("child_command") or "")
    command_posted = False
    if command and not _comment_exists(token, repo, issue_number, command):
        _github_request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            token=token,
            payload={"body": command},
        )
        command_posted = True

    result = {
        "task_id": status["task_id"],
        "route": status["route"],
        "repository": repo,
        "issue_number": issue_number,
        "issue_url": issue["html_url"],
        "child_issue_reused": reused,
        "command_posted": command_posted,
    }
    _write_json(root / "dispatch-status.json", result)
    for key, value in result.items():
        _write_output(key, str(value).lower() if isinstance(value, bool) else value)
    return 0


def _trusted_terminal(
    rows: Any,
    *,
    route: str,
) -> tuple[str, str, bool] | None:
    config = ROUTES[route]
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != TRUSTED_COMMENT_AUTHOR:
            continue
        body = str(row.get("body") or "").strip()
        for prefix in config["success"]:
            if body.startswith(prefix):
                return prefix.removeprefix("## ").strip(), body, True
        for prefix in config["failure"]:
            if body.startswith(prefix):
                return prefix.removeprefix("## ").strip(), body, False
    return None


def poll(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    dispatch_status = _load_json_text(
        (root / "dispatch-status.json").read_text(encoding="utf-8")
    )
    token = os.getenv("CONTROL_PLANE_TOKEN", "")
    repo = str(dispatch_status["repository"])
    issue_number = int(dispatch_status["issue_number"])
    route = str(dispatch_status["route"])
    deadline = time.monotonic() + int(args.wait_seconds)
    transient_errors = 0
    terminal: tuple[str, str, bool] | None = None
    monitor_error = ""

    while time.monotonic() < deadline:
        try:
            rows = _github_request(
                "GET",
                f"/repos/{repo}/issues/{issue_number}/comments?per_page=100",
                token=token,
            )
            terminal = _trusted_terminal(rows, route=route)
            if terminal:
                break
            transient_errors = 0
        except RuntimeError as exc:
            transient_errors += 1
            monitor_error = str(exc)
            if transient_errors >= 5:
                break
        time.sleep(30)

    if terminal:
        heading, body, success = terminal
        final_status = heading
        excerpt = body[:12000]
    elif transient_errors >= 5:
        success = False
        final_status = "CONTROL_MONITOR_ERROR"
        excerpt = monitor_error[:12000]
    else:
        success = False
        final_status = "CONTROL_TIMEOUT"
        excerpt = (
            f"No trusted terminal state was observed within {args.wait_seconds} seconds. "
            "The child Issue remains the authoritative place to inspect."
        )

    result = {
        **dispatch_status,
        "success": success,
        "final_status": final_status,
        "terminal_comment_excerpt": excerpt,
    }
    _write_json(root / "final-status.json", result)
    _write_output("success", str(success).lower())
    _write_output("final_status", final_status)
    return 0 if success else 3


def render(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    if args.phase == "rejected":
        status = _load_json_text((root / "prepare-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_REJECTED",
                "",
                f"- Task ID: `{status.get('task_id') or 'not-generated'}`",
                f"- Reason: `{status.get('reason') or 'unknown'}`",
                "- Child center dispatch: `not attempted`",
                "- Model/API/compute calls caused by this ticket: `0`",
            ]
        )
    elif args.phase == "dispatched":
        status = _load_json_text((root / "dispatch-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_DISPATCHED",
                "",
                f"- Task ID: `{status['task_id']}`",
                f"- Route: `{status['route']}`",
                f"- Target repository: `{status['repository']}`",
                f"- Child Issue: {status['issue_url']}",
                f"- Idempotent child reuse: `{str(bool(status.get('child_issue_reused'))).lower()}`",
                "- Control mode: `one-step governance Issue submission`",
                "- Center-to-center communication: `none`",
            ]
        )
    elif args.phase == "final":
        status = _load_json_text((root / "final-status.json").read_text(encoding="utf-8"))
        excerpt = str(status.get("terminal_comment_excerpt") or "")
        text = "\n".join(
            [
                "## CONTROL_COMPLETED" if status.get("success") else "## CONTROL_FAILED",
                "",
                f"- Task ID: `{status['task_id']}`",
                f"- Route: `{status['route']}`",
                f"- Child status: `{status['final_status']}`",
                f"- Child Issue: {status['issue_url']}",
                "- Authoritative result: `trusted github-actions[bot] terminal comment and child Artifact`",
                "",
                "<details><summary>Trusted terminal excerpt</summary>",
                "",
                excerpt,
                "",
                "</details>",
            ]
        )
    else:
        raise ValueError(f"unsupported phase: {args.phase}")
    Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--event-path", required=True)
    prepare_parser.add_argument("--output-dir", default="control-artifacts")
    prepare_parser.set_defaults(func=prepare)

    dispatch_parser = sub.add_parser("dispatch")
    dispatch_parser.add_argument("--output-dir", default="control-artifacts")
    dispatch_parser.set_defaults(func=dispatch)

    poll_parser = sub.add_parser("poll")
    poll_parser.add_argument("--output-dir", default="control-artifacts")
    poll_parser.add_argument("--wait-seconds", required=True, type=int)
    poll_parser.set_defaults(func=poll)

    render_parser = sub.add_parser("render")
    render_parser.add_argument(
        "--phase", choices=["rejected", "dispatched", "final"], required=True
    )
    render_parser.add_argument("--output-dir", default="control-artifacts")
    render_parser.add_argument("--output", required=True)
    render_parser.set_defaults(func=render)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
