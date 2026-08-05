#!/usr/bin/env python3
"""Acknowledge and read back a newly-created GPTs governance Issue."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ingress_http", ROOT / "resilient_http.py")
HTTP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HTTP)

OWNER = "a15280020511"
V3 = "governance-control-ticket-v3"
V4 = "governance-control-ticket-v4"
CLIENT_REQUEST_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _packet(body: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _fingerprint(packet: Mapping[str, Any]) -> str:
    material = {"route": packet.get("route"), "ticket": packet.get("ticket")}
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event(path: str) -> tuple[dict[str, Any], int, str, str]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    issue = value.get("issue") if isinstance(value.get("issue"), dict) else {}
    sender = value.get("sender") if isinstance(value.get("sender"), dict) else {}
    return (
        issue,
        int(issue.get("number") or 0),
        str(issue.get("title") or ""),
        str(sender.get("login") or ""),
    )


def _issue_readback_verified(
    reread_issue: Any,
    *,
    issue_number: int,
    expected_body: str,
    client_request_id: str,
) -> bool:
    if not isinstance(reread_issue, Mapping):
        return False
    if int(reread_issue.get("number") or 0) != issue_number:
        return False
    if str(reread_issue.get("title") or "") != "[control]":
        return False
    reread_body = str(reread_issue.get("body") or "").strip()
    if reread_body != expected_body.strip():
        return False
    return not client_request_id or client_request_id in reread_body


def _machine_status(
    *,
    client_request_id: str,
    issue_number: int,
    route: str,
    fingerprint: str,
    schema_valid: bool,
    read_after_write_verified: bool,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "governance-machine-status-v1",
        "client_request_id": client_request_id or None,
        "issue_number": issue_number,
        "task_id": None,
        "state": "RECEIVED",
        "route": route or None,
        "child_issue_number": None,
        "body_fingerprint": fingerprint or None,
        "read_after_write_verified": read_after_write_verified,
        "retryable": False,
        "error_code": None if schema_valid else "CONTROL_SCHEMA_REJECTED",
        "updated_at": observed_at,
    }


def _receipt(
    *,
    client_request_id: str,
    issue_number: int,
    schema_version: str,
    schema_valid: bool,
    fingerprint: str,
    machine: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "## CONTROL_RECEIVED",
            "",
            f"- Client request ID: `{client_request_id or 'legacy-v3-unavailable'}`",
            f"- Governance Issue: `#{issue_number}`",
            f"- Schema version: `{schema_version or 'missing'}`",
            f"- Schema precheck valid: `{str(schema_valid).lower()}`",
            f"- Request fingerprint: `{fingerprint or 'unavailable'}`",
            f"- Read-after-write verified: `{str(bool(machine.get('read_after_write_verified'))).lower()}`",
            "- Queue admission pending: `true`",
            "- Business calls caused by acknowledgement: `0`",
            "",
            "<!-- governance-machine-status:start -->",
            "```json",
            json.dumps(machine, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "<!-- governance-machine-status:end -->",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", default="ingress-artifacts/ingress-ack.json")
    args = parser.parse_args()

    issue, issue_number, title, sender = _event(args.event_path)
    if title != "[control]" or sender != OWNER:
        print(json.dumps({"handled": False, "reason": "not an owned control issue"}))
        return 0

    body = str(issue.get("body") or "").strip()
    packet = _packet(body)
    schema_version = str(packet.get("schema_version") or "")
    raw_request_id = packet.get("client_request_id")
    client_request_id = (
        str(raw_request_id).lower() if isinstance(raw_request_id, str) else ""
    )
    schema_valid = schema_version == V3 or (
        schema_version == V4
        and bool(CLIENT_REQUEST_ID_RE.fullmatch(client_request_id))
    )
    fingerprint = _fingerprint(packet) if packet else ""
    observed_at = datetime.now(timezone.utc).isoformat()
    token = os.getenv("GITHUB_TOKEN", "")

    reread_issue = HTTP.github_request(
        "GET",
        f"/repos/{args.repository}/issues/{issue_number}",
        token=token,
    )
    issue_readback_verified = _issue_readback_verified(
        reread_issue,
        issue_number=issue_number,
        expected_body=body,
        client_request_id=client_request_id,
    )
    machine = _machine_status(
        client_request_id=client_request_id,
        issue_number=issue_number,
        route=str(packet.get("route") or ""),
        fingerprint=fingerprint,
        schema_valid=schema_valid,
        read_after_write_verified=issue_readback_verified,
        observed_at=observed_at,
    )
    receipt = _receipt(
        client_request_id=client_request_id,
        issue_number=issue_number,
        schema_version=schema_version,
        schema_valid=schema_valid,
        fingerprint=fingerprint,
        machine=machine,
    )

    created = HTTP.github_request(
        "POST",
        f"/repos/{args.repository}/issues/{issue_number}/comments",
        token=token,
        payload={"body": receipt},
    )
    comments = HTTP.github_request(
        "GET",
        f"/repos/{args.repository}/issues/{issue_number}/comments?per_page=100",
        token=token,
    )
    comment_readback_verified = (
        isinstance(created, Mapping)
        and isinstance(comments, list)
        and any(
            isinstance(row, Mapping)
            and int(row.get("id") or 0) == int(created.get("id") or -1)
            and str(row.get("body") or "") == receipt
            for row in comments
        )
    )
    readback_verified = issue_readback_verified and comment_readback_verified

    result = {
        "schema_version": "governance-ingress-ack-v1",
        "handled": True,
        "issue_number": issue_number,
        "client_request_id": client_request_id,
        "request_fingerprint": fingerprint,
        "schema_valid": schema_valid,
        "issue_readback_verified": issue_readback_verified,
        "comment_readback_verified": comment_readback_verified,
        "read_after_write_verified": readback_verified,
        "comment_id": int(created.get("id") or 0) if isinstance(created, Mapping) else 0,
        "observed_at": observed_at,
        "model_calls": 0,
        "external_business_data_calls": 0,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if readback_verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
