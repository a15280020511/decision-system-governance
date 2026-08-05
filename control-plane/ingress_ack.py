#!/usr/bin/env python3
"""Acknowledge and read back a newly-created GPTs governance Issue."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance_transport.client import github_request
from governance_transport.diagnostics import (
    comment_readback_verified as _comment_readback_verified,
    issue_readback_verified as _verify_issue_readback,
)
from governance_transport.idempotency import (
    CLIENT_REQUEST_ID_RE,
    V3,
    V4,
    fingerprint_packet,
    is_canonical_client_request_id,
    normalize_client_request_id,
    packet_from_text,
)
from governance_transport.status import build_machine_status

OWNER = "a15280020511"


def _packet(body: str) -> dict[str, Any]:
    return packet_from_text(body)


def _fingerprint(packet: Mapping[str, Any]) -> str:
    return fingerprint_packet(packet)


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
    return _verify_issue_readback(
        reread_issue,
        issue_number=issue_number,
        expected_body=expected_body,
        client_request_id=client_request_id,
    )


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
    return build_machine_status(
        client_request_id=client_request_id,
        issue_number=issue_number,
        state="RECEIVED",
        route=route,
        body_fingerprint=fingerprint,
        read_after_write_verified=read_after_write_verified,
        read_after_write_evidence=(
            "issue-and-comment-readback" if read_after_write_verified else None
        ),
        retryable=False,
        error_code=None if schema_valid else "CONTROL_SCHEMA_REJECTED",
        updated_at=observed_at,
    )


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
    client_request_id = normalize_client_request_id(packet.get("client_request_id"))
    schema_valid = schema_version == V3 or (
        schema_version == V4
        and is_canonical_client_request_id(client_request_id)
    )
    fingerprint = _fingerprint(packet) if packet else ""
    observed_at = datetime.now(timezone.utc).isoformat()
    token = os.getenv("GITHUB_TOKEN", "")

    reread_issue = github_request(
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

    created = github_request(
        "POST",
        f"/repos/{args.repository}/issues/{issue_number}/comments",
        token=token,
        payload={"body": receipt},
    )
    comments = github_request(
        "GET",
        f"/repos/{args.repository}/issues/{issue_number}/comments?per_page=100",
        token=token,
    )
    comment_readback_verified = _comment_readback_verified(
        created,
        comments,
        expected_body=receipt,
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
