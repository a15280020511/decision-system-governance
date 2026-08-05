#!/usr/bin/env python3
"""Governance control plane with a global FIFO single-execution queue."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

API_ROOT = "https://api.github.com"
OWNER = "a15280020511"
SCHEMA_VERSION = "governance-control-ticket-v3"
STATUS_START = "<!-- governance-status:start -->"
STATUS_END = "<!-- governance-status:end -->"
MAX_BODY_CHARS = 100_000
MAX_ISSUE_SCAN_PAGES = 10
MAX_COMMENT_SCAN_PAGES = 10
MAX_EXECUTION_ATTEMPTS = 3
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 5_000
MAX_JSON_STRING_CHARS = 40_000
MAX_JSON_KEY_CHARS = 256
MAX_RECONCILE_PER_RUN = 20
TRUSTED_COMMENT_AUTHOR = "github-actions[bot]"
RECOVERY_MARKER_TEMPLATE = "<!-- governance-recovery:{task_id}:1 -->"
LEADING_HTML_COMMENT_RE = re.compile(r"\A(?:\s*<!--[\s\S]*?-->\s*)+")
TASK_ID_RE = re.compile(r"(?mi)^\s*-\s*Task ID\s*[:：]\s*`([^`]+)`\s*$")
CHILD_ISSUE_RE = re.compile(
    r"(?mi)^\s*-\s*Child Issue:\s+https://github\.com/([^/\s]+/[^/\s]+)/issues/(\d+)\s*$"
)
ROUTE_RE = re.compile(r"(?mi)^\s*-\s*Route:\s*`([^`]+)`\s*$")
CHILD_STATUS_RE = re.compile(r"(?mi)^\s*-\s*Child status:\s*`([^`]+)`\s*$")

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

SECRET_SUFFIXES = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "bearertoken",
    "clientsecret",
    "privatekey",
    "sendkey",
    "sckey",
    "password",
    "passwd",
    "secret",
    "token",
)
SECRET_EXACT = {
    "authorization",
    "credentials",
    "credential",
    "auth",
}
DANGEROUS_EXECUTION_KEYS = {
    "shell",
    "shellcommand",
    "command",
    "script",
    "pythoncode",
    "javascriptcode",
    "powershell",
    "bash",
    "executable",
    "subprocess",
    "eval",
    "exec",
    "systemcommand",
}


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


def _original_request_body(body: str) -> str:
    index = body.find(STATUS_START)
    if index < 0:
        return body.strip()
    prefix = body[:index].rstrip()
    if prefix.endswith("---"):
        prefix = prefix[:-3].rstrip()
    return prefix


def _governance_status_heading(body: str) -> str:
    start = body.find(STATUS_START)
    end = body.find(STATUS_END)
    if start < 0 or end <= start:
        return ""
    receipt = body[start + len(STATUS_START):end].strip()
    return receipt.splitlines()[0].strip() if receipt else ""


def _request_fingerprint(body: str) -> str:
    try:
        packet = _load_json_text(_original_request_body(body))
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(packet, dict):
        return ""
    material = {
        "schema_version": packet.get("schema_version"),
        "route": packet.get("route"),
        "ticket": packet.get("ticket"),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _forbidden_field_path(value: Any, path: str = "ticket") -> str:
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        current, current_path = stack.pop()
        if isinstance(current, Mapping):
            for raw_key, item in current.items():
                key = str(raw_key)
                compact = _compact_key(key)
                child_path = f"{current_path}.{key}"
                if compact in SECRET_EXACT or compact.endswith(SECRET_SUFFIXES):
                    return child_path
                if compact in DANGEROUS_EXECUTION_KEYS:
                    return child_path
                stack.append((item, child_path))
        elif isinstance(current, list):
            for index, item in enumerate(current):
                stack.append((item, f"{current_path}[{index}]"))
    return ""


def _json_complexity_errors(value: Any) -> list[str]:
    errors: list[str] = []
    stack: list[tuple[Any, str, int]] = [(value, "packet", 0)]
    nodes = 0
    while stack:
        current, path, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            errors.append(f"JSON node count exceeds {MAX_JSON_NODES}")
            break
        if depth > MAX_JSON_DEPTH:
            errors.append(f"JSON depth exceeds {MAX_JSON_DEPTH} at {path}")
            break
        if isinstance(current, Mapping):
            for raw_key, item in current.items():
                key = str(raw_key)
                if len(key) > MAX_JSON_KEY_CHARS:
                    errors.append(
                        f"JSON key exceeds {MAX_JSON_KEY_CHARS} characters at {path}"
                    )
                    return errors
                stack.append((item, f"{path}.{key}", depth + 1))
        elif isinstance(current, list):
            for index, item in enumerate(current):
                stack.append((item, f"{path}[{index}]", depth + 1))
        elif isinstance(current, str) and len(current) > MAX_JSON_STRING_CHARS:
            errors.append(
                f"JSON string exceeds {MAX_JSON_STRING_CHARS} characters at {path}"
            )
            break
    return errors


def _event_data(path: str) -> tuple[str, str, str, int]:
    event = _load_json_text(Path(path).read_text(encoding="utf-8"))
    issue = event.get("issue") if isinstance(event.get("issue"), Mapping) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), Mapping) else {}
    repository = event.get("repository") if isinstance(event.get("repository"), Mapping) else {}
    owner = repository.get("owner") if isinstance(repository.get("owner"), Mapping) else {}
    actor = str(sender.get("login") or owner.get("login") or "")
    return (
        str(issue.get("title") or ""),
        _original_request_body(str(issue.get("body") or "")),
        actor,
        int(issue.get("number") or 0),
    )


def _generated_task_id(issue_number: int, route: str) -> str:
    return f"gov-{issue_number}-{route}"


def _github_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None = None,
) -> Any:
    if not token:
        raise RuntimeError("GitHub token is not configured")
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


def _paged_path(path: str, page: int) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}per_page=100&page={page}"


def _list_paginated(
    token: str,
    path: str,
    *,
    max_pages: int,
) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    for page in range(1, max_pages + 1):
        rows = _github_request("GET", _paged_path(path, page), token=token)
        if not isinstance(rows, list):
            break
        page_rows = [row for row in rows if isinstance(row, Mapping)]
        output.extend(page_rows)
        if len(rows) < 100:
            break
    return output


def _list_issues(token: str, repository: str, *, state: str) -> list[Mapping[str, Any]]:
    query = urllib.parse.urlencode(
        {"state": state, "sort": "created", "direction": "asc"}
    )
    return _list_paginated(
        token,
        f"/repos/{repository}/issues?{query}",
        max_pages=MAX_ISSUE_SCAN_PAGES,
    )


def _list_comments(token: str, repository: str, issue_number: int) -> list[Mapping[str, Any]]:
    return _list_paginated(
        token,
        f"/repos/{repository}/issues/{issue_number}/comments",
        max_pages=MAX_COMMENT_SCAN_PAGES,
    )


def _issue_login(issue: Mapping[str, Any]) -> str:
    user = issue.get("user") if isinstance(issue.get("user"), Mapping) else {}
    return str(user.get("login") or "")


def _is_owned_control_issue(issue: Mapping[str, Any]) -> bool:
    return (
        not issue.get("pull_request")
        and str(issue.get("title") or "") == "[control]"
        and _issue_login(issue) == OWNER
    )


def _eligible_open_issues(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    eligible = [row for row in rows if _is_owned_control_issue(row)]
    return sorted(eligible, key=lambda row: int(row.get("number") or 0))


def _duplicate_blocks(row: Mapping[str, Any]) -> bool:
    state = str(row.get("state") or "")
    reason = str(row.get("state_reason") or "")
    heading = _governance_status_heading(str(row.get("body") or ""))
    if state == "open":
        return True
    if heading in {"## CONTROL_COMPLETED", "## CONTROL_DUPLICATE"}:
        return True
    if heading in {
        "## CONTROL_FAILED",
        "## CONTROL_REJECTED",
        "## CONTROL_RECONCILED_LATE_FAILURE",
    }:
        return False
    return reason in {"completed", "duplicate"}


def _find_duplicate_issue(
    rows: list[Mapping[str, Any]],
    *,
    issue_number: int,
    fingerprint: str,
) -> Mapping[str, Any] | None:
    if not fingerprint:
        return None
    candidates = sorted(
        (
            row
            for row in rows
            if _is_owned_control_issue(row)
            and int(row.get("number") or 0) < issue_number
            and _request_fingerprint(str(row.get("body") or "")) == fingerprint
            and _duplicate_blocks(row)
        ),
        key=lambda row: int(row.get("number") or 0),
    )
    return candidates[0] if candidates else None


def _count_running_attempts(token: str, repository: str, issue_number: int) -> int:
    attempts = 0
    for row in _list_comments(token, repository, issue_number):
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != TRUSTED_COMMENT_AUTHOR:
            continue
        if str(row.get("body") or "").lstrip().startswith("## CONTROL_RUNNING"):
            attempts += 1
    return attempts


def select(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    token = os.getenv("GITHUB_TOKEN", "")
    open_rows = _list_issues(token, args.repository, state="open")
    queue = _eligible_open_issues(open_rows)

    if not queue:
        status = {"has_task": False, "pending_count": 0}
        _write_json(root / "selection-status.json", status)
        _write_output("has_task", "false")
        _write_output("pending_count", 0)
        return 0

    issue = queue[0]
    issue_number = int(issue["number"])
    request_body = _original_request_body(str(issue.get("body") or ""))
    current_heading = _governance_status_heading(str(issue.get("body") or ""))
    if current_heading == "## CONTROL_DISPATCHED":
        status = {
            "has_task": False,
            "in_flight": True,
            "pending_count": len(queue),
            "issue_number": issue_number,
            "issue_url": str(issue.get("html_url") or ""),
            "reason": "oldest governance task is asynchronously waiting for a child terminal",
        }
        _write_json(root / "selection-status.json", status)
        for key, value in status.items():
            _write_output(key, str(value).lower() if isinstance(value, bool) else value)
        return 0
    fingerprint = _request_fingerprint(request_body)
    all_rows = _list_issues(token, args.repository, state="all")
    duplicate = _find_duplicate_issue(
        all_rows,
        issue_number=issue_number,
        fingerprint=fingerprint,
    )
    previous_attempts = _count_running_attempts(token, args.repository, issue_number)
    retry_exhausted = previous_attempts >= MAX_EXECUTION_ATTEMPTS

    status = {
        "has_task": True,
        "pending_count": len(queue),
        "issue_number": issue_number,
        "issue_url": str(issue.get("html_url") or ""),
        "request_fingerprint": fingerprint,
        "duplicate": duplicate is not None,
        "duplicate_of_issue_number": int(duplicate.get("number") or 0) if duplicate else 0,
        "duplicate_of_issue_url": str(duplicate.get("html_url") or "") if duplicate else "",
        "previous_attempts": previous_attempts,
        "attempt": previous_attempts + 1,
        "retry_exhausted": retry_exhausted,
    }
    _write_json(root / "selection-status.json", status)
    (root / "selected-request.md").write_text(request_body + "\n", encoding="utf-8")
    event = {
        "issue": {
            "number": issue_number,
            "title": "[control]",
            "body": request_body,
        },
        "sender": {"login": OWNER},
        "repository": {
            "full_name": args.repository,
            "owner": {"login": OWNER},
        },
    }
    _write_json(root / "selected-event.json", event)

    for key, value in status.items():
        _write_output(key, str(value).lower() if isinstance(value, bool) else value)
    return 0


def pending(args: argparse.Namespace) -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    queue = _eligible_open_issues(_list_issues(token, args.repository, state="open"))
    _write_output("has_more", str(bool(queue)).lower())
    _write_output("pending_count", len(queue))
    return 0


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

    if actor != OWNER:
        errors.append("governance issue actor must be the repository owner")
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
        errors.extend(_json_complexity_errors(packet))
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

    forbidden_path = _forbidden_field_path(ticket)
    if forbidden_path:
        errors.append(f"secret-bearing or executable field is forbidden: {forbidden_path}")

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


def _find_existing_child_issue(token: str, repo: str, title: str) -> Mapping[str, Any] | None:
    for row in _list_issues(token, repo, state="all"):
        if row.get("pull_request"):
            continue
        if str(row.get("title") or "") == title:
            return row
    return None


def _comment_exists(token: str, repo: str, issue_number: int, body: str) -> bool:
    return any(
        str(row.get("body") or "").strip() == body
        for row in _list_comments(token, repo, issue_number)
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


def _normalized_terminal_body(body: str) -> str:
    return LEADING_HTML_COMMENT_RE.sub("", body).lstrip()


def _extract_task_id(body: str) -> str:
    match = TASK_ID_RE.search(body)
    return match.group(1).strip() if match else ""


def _artifact_value(body: str, label: str) -> str:
    match = re.search(
        rf"(?mi)^\s*-\s*{re.escape(label)}:\s*`([^`]+)`\s*$",
        body,
    )
    return match.group(1).strip() if match else ""


def _artifact_url(body: str, label: str) -> str:
    match = re.search(
        rf"(?mi)^\s*-\s*{re.escape(label)}:\s*(https://github\.com/\S+/artifacts/\d+)\s*$",
        body,
    )
    return match.group(1).strip() if match else ""


def _valid_digest(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _artifact_contract_error(route: str, body: str) -> str:
    if route in {"compute", "intelligence"}:
        artifact_id = _artifact_value(body, "Artifact ID")
        digest = _artifact_value(body, "Artifact digest")
        url = _artifact_url(body, "Artifact")
        if not artifact_id.isdigit():
            return "success terminal is missing a numeric Artifact ID"
        if not _valid_digest(digest):
            return "success terminal is missing a 64-hex Artifact digest"
        if not url.endswith(f"/artifacts/{artifact_id}"):
            return "success terminal Artifact URL does not match Artifact ID"
        return ""

    primary_id = _artifact_value(body, "Primary Artifact ID")
    primary_digest = _artifact_value(body, "Primary Artifact digest")
    primary_url = _artifact_url(body, "Primary Artifact")
    final_id = _artifact_value(body, "Final attestation Artifact ID")
    final_digest = _artifact_value(body, "Final attestation Artifact digest")
    final_url = _artifact_url(body, "Final attestation Artifact")
    if not primary_id.isdigit() or not _valid_digest(primary_digest):
        return "expert success is missing the primary Artifact identity"
    if not primary_url.endswith(f"/artifacts/{primary_id}"):
        return "expert primary Artifact URL does not match its ID"
    if not final_id.isdigit() or not _valid_digest(final_digest):
        return "expert success is missing the final attestation Artifact identity"
    if not final_url.endswith(f"/artifacts/{final_id}"):
        return "expert final attestation Artifact URL does not match its ID"
    return ""


def _trusted_terminal(
    rows: Any,
    *,
    route: str,
    expected_task_id: str = "",
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
        raw_body = str(row.get("body") or "").strip()
        match_body = _normalized_terminal_body(raw_body)
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

        actual_task_id = _extract_task_id(raw_body)
        if expected_task_id and actual_task_id != expected_task_id:
            detail = (
                f"Expected Task ID `{expected_task_id}` but terminal contained "
                f"`{actual_task_id or 'missing'}`.\n\n{raw_body}"
            )
            return "CONTROL_CHILD_TASK_MISMATCH", detail, False
        if success:
            contract_error = _artifact_contract_error(route, raw_body)
            if contract_error:
                return (
                    "CONTROL_CHILD_EVIDENCE_INVALID",
                    f"{contract_error}.\n\n{raw_body}",
                    False,
                )
        return matched_status, raw_body, success
    return None


def _trusted_bot_activity(rows: list[Mapping[str, Any]]) -> bool:
    for row in rows:
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != TRUSTED_COMMENT_AUTHOR:
            continue
        body = _normalized_terminal_body(str(row.get("body") or "").strip())
        if body.startswith("## "):
            return True
    return False


def _recovery_marker(task_id: str) -> str:
    return RECOVERY_MARKER_TEMPLATE.format(task_id=task_id)


def _perform_one_recovery(
    *,
    token: str,
    repo: str,
    issue_number: int,
    route: str,
    task_id: str,
    comments: list[Mapping[str, Any]],
) -> bool:
    marker = _recovery_marker(task_id)
    if any(marker in str(row.get("body") or "") for row in comments):
        return False

    _github_request(
        "POST",
        f"/repos/{repo}/issues/{issue_number}/comments",
        token=token,
        payload={
            "body": "\n".join(
                [
                    marker,
                    "## GOVERNANCE_RECOVERY_REQUESTED",
                    "",
                    f"- Task ID: `{task_id}`",
                    "- Recovery attempt: `1/1`",
                    "- Reason: `no trusted child workflow activity observed`",
                ]
            )
        },
    )
    if route == "expert":
        _github_request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            token=token,
            payload={"body": f"/run-expert-team {task_id}"},
        )
    else:
        _github_request(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            token=token,
            payload={"state": "closed", "state_reason": "not_planned"},
        )
        _github_request(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            token=token,
            payload={"state": "open"},
        )
    return True


def poll(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    dispatch_status = _load_json_text(
        (root / "dispatch-status.json").read_text(encoding="utf-8")
    )
    token = os.getenv("CONTROL_PLANE_TOKEN", "")
    repo = str(dispatch_status["repository"])
    issue_number = int(dispatch_status["issue_number"])
    route = str(dispatch_status["route"])
    task_id = str(dispatch_status["task_id"])
    wait_seconds = int(args.wait_seconds)
    started = time.monotonic()
    deadline = started + wait_seconds
    recovery_after = started + min(max(30, wait_seconds // 3), 180)
    transient_errors = 0
    terminal: tuple[str, str, bool] | None = None
    monitor_error = ""
    recovery_attempted = False

    while time.monotonic() < deadline:
        try:
            rows = _list_comments(token, repo, issue_number)
            terminal = _trusted_terminal(
                rows,
                route=route,
                expected_task_id=task_id,
            )
            if terminal:
                break
            if (
                not recovery_attempted
                and time.monotonic() >= recovery_after
                and not _trusted_bot_activity(rows)
            ):
                recovery_attempted = _perform_one_recovery(
                    token=token,
                    repo=repo,
                    issue_number=issue_number,
                    route=route,
                    task_id=task_id,
                    comments=rows,
                )
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
            f"No trusted terminal state was observed within {wait_seconds} seconds. "
            "The child Issue remains authoritative and late reconciliation is enabled."
        )

    result = {
        **dispatch_status,
        "success": success,
        "final_status": final_status,
        "terminal_comment_excerpt": excerpt,
        "recovery_attempted": recovery_attempted,
    }
    _write_json(root / "final-status.json", result)
    _write_output("success", str(success).lower())
    _write_output("final_status", final_status)
    _write_output("recovery_attempted", str(recovery_attempted).lower())
    return 0 if success else 3


def _compose_text(request: str, receipt: str) -> str:
    return (
        _original_request_body(request).rstrip()
        + "\n\n---\n\n"
        + STATUS_START
        + "\n"
        + receipt.strip()
        + "\n"
        + STATUS_END
        + "\n"
    )


def _reconciliation_candidate(issue: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(issue.get("state") or "") != "closed":
        return None
    body = str(issue.get("body") or "")
    heading = _governance_status_heading(body)
    if heading != "## CONTROL_FAILED":
        return None
    status_match = CHILD_STATUS_RE.search(body)
    route_match = ROUTE_RE.search(body)
    task_match = TASK_ID_RE.search(body)
    child_match = CHILD_ISSUE_RE.search(body)
    if not status_match or status_match.group(1) not in {
        "CONTROL_TIMEOUT",
        "CONTROL_MONITOR_ERROR",
        "CONTROL_ASYNC_DEADLINE_EXCEEDED",
    }:
        return None
    if not route_match or route_match.group(1) not in ROUTES:
        return None
    if not task_match or not child_match:
        return None
    return {
        "governance_issue_number": int(issue.get("number") or 0),
        "governance_body": body,
        "task_id": task_match.group(1),
        "route": route_match.group(1),
        "child_repository": child_match.group(1),
        "child_issue_number": int(child_match.group(2)),
        "original_monitor_status": status_match.group(1),
    }


def _render_reconciled(candidate: Mapping[str, Any], terminal: tuple[str, str, bool]) -> str:
    heading, body, success = terminal
    reconciled = (
        "CONTROL_RECONCILED_LATE_SUCCESS"
        if success
        else "CONTROL_RECONCILED_LATE_FAILURE"
    )
    return "\n".join(
        [
            f"## {reconciled}",
            "",
            f"- Task ID: `{candidate['task_id']}`",
            f"- Route: `{candidate['route']}`",
            f"- Original monitor status: `{candidate['original_monitor_status']}`",
            f"- Child status: `{heading}`",
            (
                "- Child Issue: "
                f"https://github.com/{candidate['child_repository']}/issues/"
                f"{candidate['child_issue_number']}"
            ),
            "- Authoritative result: `late trusted github-actions[bot] terminal comment`",
            "",
            "<details><summary>Trusted terminal excerpt</summary>",
            "",
            body[:12000],
            "",
            "</details>",
        ]
    )


def reconcile(args: argparse.Namespace) -> int:
    governance_token = os.getenv("GITHUB_TOKEN", "")
    child_token = os.getenv("CONTROL_PLANE_TOKEN", "")
    reconciled_count = 0
    for issue in reversed(_list_issues(governance_token, args.repository, state="closed")):
        if reconciled_count >= MAX_RECONCILE_PER_RUN:
            break
        candidate = _reconciliation_candidate(issue)
        if not candidate:
            continue
        rows = _list_comments(
            child_token,
            str(candidate["child_repository"]),
            int(candidate["child_issue_number"]),
        )
        terminal = _trusted_terminal(
            rows,
            route=str(candidate["route"]),
            expected_task_id=str(candidate["task_id"]),
        )
        if not terminal:
            continue
        receipt = _render_reconciled(candidate, terminal)
        body = _compose_text(str(candidate["governance_body"]), receipt)
        issue_number = int(candidate["governance_issue_number"])
        _github_request(
            "POST",
            f"/repos/{args.repository}/issues/{issue_number}/comments",
            token=governance_token,
            payload={"body": receipt},
        )
        _github_request(
            "PATCH",
            f"/repos/{args.repository}/issues/{issue_number}",
            token=governance_token,
            payload={
                "body": body,
                "state": "closed",
                "state_reason": "completed" if terminal[2] else "not_planned",
            },
        )
        reconciled_count += 1

    _write_output("reconciled_count", reconciled_count)
    print(json.dumps({"reconciled_count": reconciled_count}))
    return 0


def render(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    if args.phase == "duplicate":
        status = _load_json_text((root / "selection-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_DUPLICATE",
                "",
                f"- Request fingerprint: `{status.get('request_fingerprint') or 'unavailable'}`",
                f"- Original Issue: {status.get('duplicate_of_issue_url') or 'unknown'}",
                "- Queue admission: `rejected as duplicate`",
                "- Child center dispatch: `not attempted`",
                "- Model/API/compute calls caused by this ticket: `0`",
            ]
        )
    elif args.phase == "exhausted":
        status = _load_json_text((root / "selection-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_FAILED",
                "",
                "- Failure class: `CONTROL_RETRY_EXHAUSTED`",
                f"- Maximum attempts: `{MAX_EXECUTION_ATTEMPTS}`",
                f"- Recorded attempts: `{status.get('previous_attempts', 0)}`",
                "- Child center dispatch: `not attempted in this recovery run`",
                "- Action: inspect prior governance receipts; no automatic retry remains.",
            ]
        )
    elif args.phase == "running":
        prepared = _load_json_text((root / "prepare-status.json").read_text(encoding="utf-8"))
        selected = _load_json_text((root / "selection-status.json").read_text(encoding="utf-8"))
        text = "\n".join(
            [
                "## CONTROL_RUNNING",
                "",
                f"- Task ID: `{prepared['task_id']}`",
                f"- Route: `{prepared['route']}`",
                f"- Request fingerprint: `{selected.get('request_fingerprint') or 'unavailable'}`",
                f"- Execution attempt: `{selected.get('attempt', 1)}/{MAX_EXECUTION_ATTEMPTS}`",
                "- Global execution slots: `1`",
                "- Queue discipline: `FIFO`",
                "- Submission mode: `asynchronous`",
            ]
        )
    elif args.phase == "rejected":
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
                "- Global execution slots: `1`",
                "- Queue discipline: `FIFO`",
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
                f"- Controlled recovery attempted: `{str(bool(status.get('recovery_attempted'))).lower()}`",
                "- Authoritative result: `trusted github-actions[bot] terminal comment and validated child Artifact`",
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


def compose(args: argparse.Namespace) -> int:
    request = Path(args.request).read_text(encoding="utf-8")
    receipt = Path(args.receipt).read_text(encoding="utf-8")
    Path(args.output).write_text(_compose_text(request, receipt), encoding="utf-8")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    select_parser = sub.add_parser("select")
    select_parser.add_argument("--repository", required=True)
    select_parser.add_argument("--output-dir", default="control-artifacts")
    select_parser.set_defaults(func=select)

    pending_parser = sub.add_parser("pending")
    pending_parser.add_argument("--repository", required=True)
    pending_parser.set_defaults(func=pending)

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

    reconcile_parser = sub.add_parser("reconcile")
    reconcile_parser.add_argument("--repository", required=True)
    reconcile_parser.set_defaults(func=reconcile)

    render_parser = sub.add_parser("render")
    render_parser.add_argument(
        "--phase",
        choices=["duplicate", "exhausted", "running", "rejected", "dispatched", "final"],
        required=True,
    )
    render_parser.add_argument("--output-dir", default="control-artifacts")
    render_parser.add_argument("--output", required=True)
    render_parser.set_defaults(func=render)

    compose_parser = sub.add_parser("compose")
    compose_parser.add_argument("--request", required=True)
    compose_parser.add_argument("--receipt", required=True)
    compose_parser.add_argument("--output", required=True)
    compose_parser.set_defaults(func=compose)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
