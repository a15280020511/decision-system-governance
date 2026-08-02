#!/usr/bin/env python3
"""Send one summarized governance notification through ServerChan."""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def endpoint(sendkey: str) -> str:
    match = re.match(r"^sctp(\d+)t", sendkey)
    if match:
        return f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"
    return f"https://sctapi.ftqq.com/{sendkey}.send"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    args = parser.parse_args()

    sendkey = os.getenv("SERVERCHAN_SENDKEY", "").strip()
    if not sendkey:
        print(json.dumps({"status": "SKIPPED", "reason": "SERVERCHAN_SENDKEY not configured"}))
        return 0

    title = " ".join(args.title.replace("\r", " ").replace("\n", " ").split())[:256]
    body = Path(args.body_file).read_text(encoding="utf-8")[:30000]
    payload = urllib.parse.urlencode({"title": title, "desp": body}).encode("utf-8")
    request = urllib.request.Request(
        endpoint(sendkey),
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "decision-system-governance-serverchan",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:2000]
        raise SystemExit(f"ServerChan HTTP {exc.code}: {raw}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("ServerChan returned non-JSON response") from exc
    code = result.get("code")
    if code not in (0, "0"):
        raise SystemExit(f"ServerChan rejected notification: code={code}")
    print(json.dumps({"status": "SENT"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
