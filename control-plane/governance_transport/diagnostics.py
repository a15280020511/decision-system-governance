"""Pure readback verification helpers for governance ingress diagnostics."""
from __future__ import annotations

from typing import Any, Mapping


def repository_metadata_verified(value: Any, expected_full_name: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        str(value.get("full_name") or "") == expected_full_name
        and value.get("archived") is not True
        and value.get("disabled") is not True
        and value.get("has_issues") is not False
    )


def issue_readback_verified(
    reread_issue: Any,
    *,
    issue_number: int,
    expected_body: str,
    client_request_id: str,
    expected_title: str = "[control]",
) -> bool:
    if not isinstance(reread_issue, Mapping):
        return False
    if int(reread_issue.get("number") or 0) != issue_number:
        return False
    if str(reread_issue.get("title") or "") != expected_title:
        return False
    reread_body = str(reread_issue.get("body") or "").strip()
    if reread_body != expected_body.strip():
        return False
    return not client_request_id or client_request_id in reread_body


def comment_readback_verified(
    created: Any,
    comments: Any,
    *,
    expected_body: str,
) -> bool:
    if not isinstance(created, Mapping) or not isinstance(comments, list):
        return False
    expected_id = int(created.get("id") or -1)
    if expected_id <= 0:
        return False
    return any(
        isinstance(row, Mapping)
        and int(row.get("id") or 0) == expected_id
        and str(row.get("body") or "") == expected_body
        for row in comments
    )
