#!/usr/bin/env python3
"""Send a metadata-only ServerChan notification without exposing SendKey."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SCT3_RE = re.compile(r"^sctp([0-9]+)t")


def endpoint(sendkey: str) -> str:
    if sendkey.startswith("SCT"):
        return f"https://sctapi.ftqq.com/{sendkey}.send"
    match = SCT3_RE.match(sendkey)
    if match:
        return f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"
    raise ValueError("unsupported ServerChan SendKey prefix")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    args = parser.parse_args()
    sendkey = os.getenv("SERVERCHAN_SENDKEY", "").strip()
    if not sendkey:
        print("::error::SERVERCHAN_SENDKEY is missing or unavailable", file=sys.stderr)
        return 2
    title = args.title.strip()[:128]
    description = args.description.strip()[:4000]
    if not title or not description:
        print("::error::notification title and description are required", file=sys.stderr)
        return 2
    data = urllib.parse.urlencode({"title": title, "desp": description}).encode("utf-8")
    request = urllib.request.Request(endpoint(sendkey), data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "governance-serverchan-notifier"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"::error::ServerChan HTTP {exc.code}", file=sys.stderr)
        return 3
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"::error::ServerChan request failed: {type(exc).__name__}", file=sys.stderr)
        return 3
    if status != 200 or payload.get("code") != 0:
        print(f"::error::ServerChan rejected notification: HTTP {status}, code={payload.get('code')}", file=sys.stderr)
        return 4
    print("ServerChan notification accepted: HTTP 200, code=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
