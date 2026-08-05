"""Machine-readable governance status construction and embedding."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MACHINE_START = "<!-- governance-machine-status:start -->"
MACHINE_END = "<!-- governance-machine-status:end -->"


def build_machine_status(
    *,
    client_request_id: str,
    issue_number: int,
    state: str,
    route: str = "",
    task_id: str = "",
    child_issue_number: int | None = None,
    body_fingerprint: str = "",
    read_after_write_verified: bool | None = None,
    read_after_write_evidence: str | None = None,
    retryable: bool = False,
    error_code: str | None = None,
    canonical_issue_number: int | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "governance-machine-status-v1",
        "client_request_id": client_request_id or None,
        "issue_number": int(issue_number),
        "task_id": task_id or None,
        "state": state,
        "route": route or None,
        "child_issue_number": child_issue_number,
        "body_fingerprint": body_fingerprint or None,
        "read_after_write_verified": read_after_write_verified,
        "read_after_write_evidence": read_after_write_evidence,
        "retryable": bool(retryable),
        "error_code": error_code,
        "canonical_issue_number": canonical_issue_number,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }


def append_machine_status(path: Path, payload: Mapping[str, Any]) -> None:
    existing = path.read_text(encoding="utf-8").rstrip()
    block = "\n".join(
        [
            "",
            MACHINE_START,
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            MACHINE_END,
            "",
        ]
    )
    path.write_text(existing + block, encoding="utf-8")
