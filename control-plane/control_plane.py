#!/usr/bin/env python3
"""Governance control plane for dispatching formal tickets to isolated centers."""
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
COMMAND_RE = re.compile(
    r"^/dispatch-control\s+([A-Za-z0-9][A-Za-z0-9._:-]{7,127})$"
)
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:secret|token|password|passwd|private_key|api_key|sendkey|sckey)(?:$|_)",
    re.IGNORECASE,
)
MAX_BODY_CHARS = 100_000
TRUSTED_COMMENT_AUTHOR = "github-actions[bot]"


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


def _event_data(path: str) -> tuple[str, str, str, str]:
    event = _load_json_text(Path(path).read_text(encoding="utf-8"))
    issue = event.get("issue") if isinstance(event.get("issue"), Mapping) else {}
    comment = event.get("comment") if isinstance(event.get("comment"), Mapping) else {}
    sender = comment.get("user") if isinstance(comment.get("user"), Mapping) else {}
    repository = event.get("repository") if isinstance(event.get("repository"), Mapping) else {}
    owner = repository.get("owner") if isinstance(repository.get("owner"), Mapping) else {}
    return (
        str(issue.get("title") or ""),
        str(issue.get("body") or ""),
        str(comment.get("body") or "").strip(),
        str(sender.get("login") or owner.get("login") or ""),
    )


def prepare(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    packet: dict[str, Any] = {}

    try:
        issue_title, issue_body, comment_body, actor = _event_data(args.event_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        issue_title = issue_body = comment_body = actor = ""
        errors.append(f"event parse failed: {exc}")

    command_id = ""
    match = COMMAND_RE.fullmatch(comment_body)
    if match:
        command_id = match.group(1)
    else:
        errors.append("command must be: /dispatch-control <task_id>")

    if not issue_title.startswith("[control]"):
        errors.append("governance issue title must start with [control]")
    if len(issue_body) > MAX_BODY_CHARS:
        errors.append(f"issue body exceeds {MAX_BODY_CHARS} characters")

    try:
        raw = _load_json_text(issue_body)
        if not isinstance(raw, dict):
            raise ValueError("control ticket must be a JSON object")
        packet = raw
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"control ticket JSON invalid: {exc}")

    allowed = {
        "schema_version",
        "task_id",
        "route",
        "ticket",
        "wait_seconds",
    }
    unexpected = sorted(set(packet) - allowed)
    if unexpected:
        errors.append(f"unknown control ticket fields: {unexpected}")

    if packet.get("schema_version") != "governance-control-ticket-v2":
        errors.append("schema_version must be governance-control-ticket-v2")

    task_id = packet.get("task_id")
    if not isinstance(task_id, str) or TASK_ID_RE.fullmatch(task_id) is None:
        errors.append("task_id must be 8-128 safe characters")
        task_id = ""
    if command_id and task_id and command_id != task_id:
        errors.append("command task_id must exactly match ticket task_id")

    route = packet.get("route")
    if route not in ROUTES:
        errors.append(f"route must be one of {sorted(ROUTES)}")
        route = ""

    ticket = packet.get("ticket")
    if not isinstance(ticket, dict):
        errors.append("ticket must be the exact child-center ticket object")
        ticket = {}
    child_task_id = ticket.get("task_id") if isinstance(ticket, dict) else None
    if task_id and child_task_id != task_id:
        errors.append("child ticket task_id must exactly match control task_id")

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

    accepted = not errors
    route_config = ROUTES.get(route, {})
    status = {
        "accepted": accepted,
        "reason": "; ".join(errors) if errors else "control ticket accepted",
        "actor": actor,
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
        _write_json(root / "child-ticket.json", ticket)

    for key, value in status.items():
        if key in {
            "accepted",
            "reason",
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
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        raise RuntimeError(f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}") from exc
    return json.loads(raw) if raw else None


def dispatch(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    status = _load_json_text((root / "prepare-status.json").read_text(encoding="utf-8"))
    if status.get("accepted") is not True:
        raise SystemExit("refusing to dispatch an unaccepted control ticket")
    token = os.getenv("CONTROL_PLANE_TOKEN", "")
    repo = str(status["target_repository"])
    ticket_text = (root / "child-ticket.json").read_text(encoding="utf-8").strip()
    issue = _github_request(
        "POST",
        f"/repos/{repo}/issues",
        token=token,
        payload={
            "title": status["child_issue_title"],
            "body": ticket_text,
        },
    )
    issue_number = int(issue["number"])
    if status.get("child_command"):
        _github_request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            token=token,
            payload={"body": status["child_command"]},
        )
    result = {
        "task_id": status["task_id"],
        "route": status["route"],
        "repository": repo,
        "issue_number": issue_number,
        "issue_url": issue["html_url"],
        "command_posted": bool(status.get("child_command")),
    }
    _write_json(root / "dispatch-status.json", result)
    for key, value in result.items():
        _write_output(key, value)
    return 0


def _trusted_terminal(
    rows: Any,
    *,
    route: str,
) -> tuple[str, str, bool] | None:
    config = ROUTES[route]
    success_prefixes = config["success"]
    failure_prefixes = config["failure"]
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != TRUSTED_COMMENT_AUTHOR:
            continue
        body = str(row.get("body") or "").strip()
        for prefix in success_prefixes:
            if body.startswith(prefix):
                return prefix.removeprefix("## ").strip(), body, True
        for prefix in failure_prefixes:
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
        except RuntimeError:
            transient_errors += 1
            if transient_errors >= 5:
                raise
        time.sleep(30)

    if terminal:
        heading, body, success = terminal
        final_status = heading
        excerpt = body[:12000]
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
    phase = args.phase
    if phase == "rejected":
        status = _load_json_text((root / "prepare-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_REJECTED",
                "",
                f"- Task ID: `{status.get('task_id') or 'unknown'}`",
                f"- Reason: `{status.get('reason') or 'unknown'}`",
                "- Child center dispatch: `not attempted`",
                "- Model/API/compute calls caused by this ticket: `0`",
            ]
        )
    elif phase == "dispatched":
        status = _load_json_text((root / "dispatch-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_DISPATCHED",
                "",
                f"- Task ID: `{status['task_id']}`",
                f"- Route: `{status['route']}`",
                f"- Target repository: `{status['repository']}`",
                f"- Child Issue: {status['issue_url']}",
                "- Control mode: `governance issue gateway; child repository retains execution authority`",
                "- Center-to-center communication: `none`",
            ]
        )
    elif phase == "final":
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
                "- Authoritative result: `the trusted github-actions[bot] terminal comment and child Artifact`",
                "",
                "<details><summary>Trusted terminal excerpt</summary>",
                "",
                excerpt,
                "",
                "</details>",
            ]
        )
    else:
        raise ValueError(f"unsupported phase: {phase}")
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
    render_parser.add_argument("--phase", choices=["rejected", "dispatched", "final"], required=True)
    render_parser.add_argument("--output-dir", default="control-artifacts")
    render_parser.add_argument("--output", required=True)
    render_parser.set_defaults(func=render)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
