from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

STATUS_START = "<!-- governance-status:start -->"
STATUS_END = "<!-- governance-status:end -->"
TRUSTED_AUTHOR = "github-actions[bot]"
TRUSTED_HEADINGS = (
    "## CONTROL_RUNNING",
    "## CONTROL_DISPATCHED",
    "## CONTROL_COMPLETED",
    "## CONTROL_FAILED",
    "## CONTROL_REJECTED",
    "## CONTROL_DUPLICATE",
)


def _write_output(name: str, value: str) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    normalized = value.replace("\r", " ").replace("\n", " ")
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={normalized}\n")


def _extract_status_receipt(body: str) -> tuple[str | None, str | None]:
    starts = body.count(STATUS_START)
    ends = body.count(STATUS_END)
    if starts == 0 and ends == 0:
        return None, None
    if starts != 1 or ends != 1:
        return None, "governance status markers must be absent or form exactly one pair"
    start = body.find(STATUS_START)
    end = body.find(STATUS_END)
    if start < 0 or end < start:
        return None, "governance status markers are malformed"
    trailing = body[end + len(STATUS_END) :].strip()
    if trailing:
        return None, "content after the governance status block is forbidden"
    receipt = body[start + len(STATUS_START) : end].strip()
    if not receipt.startswith(TRUSTED_HEADINGS):
        return None, "governance status block has an unsupported heading"
    return receipt, None


def _latest_trusted_receipt(rows: Any) -> str | None:
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        if str(user.get("login") or "") != TRUSTED_AUTHOR:
            continue
        body = str(row.get("body") or "").strip()
        if body.startswith(TRUSTED_HEADINGS):
            return body
    return None


def validate_status_ownership(body: str, comments: Any) -> tuple[bool, str]:
    receipt, marker_error = _extract_status_receipt(body)
    if marker_error:
        return False, marker_error
    if receipt is None:
        return True, "no governance status block supplied by the submitter"
    trusted = _latest_trusted_receipt(comments)
    if trusted is None:
        return False, "untrusted governance status block is forbidden"
    if receipt != trusted:
        return False, "governance status block does not match the latest trusted bot receipt"
    return True, "governance status block matches the latest trusted bot receipt"


def _mark_rejected(path: Path, reason: str) -> None:
    status = json.loads(path.read_text(encoding="utf-8"))
    existing = str(status.get("reason") or "")
    status["accepted"] = False
    status["reason"] = f"{existing}; {reason}" if existing else reason
    status["target_repository"] = ""
    status["child_issue_title"] = ""
    status["child_command"] = ""
    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-body", required=True)
    parser.add_argument("--comments-json", required=True)
    parser.add_argument("--prepare-status", required=True)
    args = parser.parse_args()

    status_path = Path(args.prepare_status)
    try:
        body = Path(args.raw_body).read_text(encoding="utf-8")
        comments = json.loads(Path(args.comments_json).read_text(encoding="utf-8"))
        safe, reason = validate_status_ownership(body, comments)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        safe = False
        reason = f"governance status ownership check failed: {exc}"

    if not safe:
        _mark_rejected(status_path, reason)

    _write_output("safe", str(safe).lower())
    _write_output("reason", reason)
    print(json.dumps({"safe": safe, "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
