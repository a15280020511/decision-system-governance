#!/usr/bin/env python3
"""Exercise governance Issue write/read without dispatching a business task."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gpts_canary_http", ROOT / "control-plane" / "resilient_http.py"
)
HTTP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HTTP)

TITLE = "[health] GPTs Ingress Canary"


def _find_issue(rows: Any) -> Mapping[str, Any] | None:
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, Mapping) and not row.get("pull_request"):
            if str(row.get("title") or "") == TITLE:
                return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", default="canary-artifacts/gpts-ingress-canary.json")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "")
    nonce = str(uuid.uuid4())
    observed_at = datetime.now(timezone.utc).isoformat()
    body = "\n".join(
        [
            "## GPTS_INGRESS_CANARY",
            "",
            f"- Nonce: `{nonce}`",
            f"- Observed at: `{observed_at}`",
            "- Business dispatch: `disabled`",
            "- Model/API/compute calls: `0`",
        ]
    )

    rows = HTTP.github_request(
        "GET",
        f"/repos/{args.repository}/issues?state=all&per_page=100",
        token=token,
    )
    issue = _find_issue(rows)
    if issue is None:
        issue = HTTP.github_request(
            "POST",
            f"/repos/{args.repository}/issues",
            token=token,
            payload={"title": TITLE, "body": body},
        )
    else:
        issue_number = int(issue.get("number") or 0)
        issue = HTTP.github_request(
            "PATCH",
            f"/repos/{args.repository}/issues/{issue_number}",
            token=token,
            payload={"body": body, "state": "open"},
        )

    issue_number = int(issue.get("number") or 0) if isinstance(issue, Mapping) else 0
    reread = HTTP.github_request(
        "GET",
        f"/repos/{args.repository}/issues/{issue_number}",
        token=token,
    )
    readback_verified = (
        isinstance(reread, Mapping)
        and int(reread.get("number") or 0) == issue_number
        and str(reread.get("title") or "") == TITLE
        and nonce in str(reread.get("body") or "")
    )

    HTTP.github_request(
        "PATCH",
        f"/repos/{args.repository}/issues/{issue_number}",
        token=token,
        payload={"state": "closed", "state_reason": "completed"},
    )

    result = {
        "schema_version": "gpts-ingress-canary-v1",
        "status": "PASS" if readback_verified else "FAIL",
        "issue_number": issue_number,
        "nonce": nonce,
        "read_after_write_verified": readback_verified,
        "observed_at": observed_at,
        "business_dispatch": False,
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
