#!/usr/bin/env python3
"""Bounded GitHub API retry, rate-limit backoff and audit support."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping

API_ROOT = "https://api.github.com"
RETRYABLE_HTTP = {429, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 120


def _audit(event: Mapping[str, Any]) -> None:
    path_text = os.getenv("GOVERNANCE_HTTP_AUDIT_FILE", "").strip()
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _retry_delay(headers: Mapping[str, Any], attempt: int) -> tuple[float, str]:
    retry_after = _header(headers, "Retry-After").strip()
    if retry_after:
        try:
            return min(MAX_BACKOFF_SECONDS, max(1.0, float(retry_after))), "retry-after-seconds"
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                delay = when.timestamp() - time.time()
                return min(MAX_BACKOFF_SECONDS, max(1.0, delay)), "retry-after-date"
            except (TypeError, ValueError, OverflowError):
                pass

    reset = _header(headers, "X-RateLimit-Reset").strip()
    remaining = _header(headers, "X-RateLimit-Remaining").strip()
    if reset and remaining == "0":
        try:
            delay = float(reset) - time.time() + 1.0
            return min(MAX_BACKOFF_SECONDS, max(1.0, delay)), "rate-limit-reset"
        except ValueError:
            pass

    exponential = min(MAX_BACKOFF_SECONDS, float(2 ** max(1, attempt)))
    return exponential, "bounded-exponential"


def _is_rate_limited(code: int, headers: Mapping[str, Any]) -> bool:
    return (
        code == 429
        or _header(headers, "Retry-After") != ""
        or (code == 403 and _header(headers, "X-RateLimit-Remaining") == "0")
    )


def github_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None = None,
) -> Any:
    """Execute one GitHub REST request with bounded, auditable retries.

    Retries are limited to transient network errors, 429, rate-limit 403, and
    502/503/504. Authorization failures, validation errors and other 4xx
    responses fail immediately. Tokens and response bodies are never audited.
    """
    if not token:
        raise RuntimeError("GitHub token is not configured")

    try:
        max_attempts = int(os.getenv("GOVERNANCE_HTTP_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))
    except ValueError:
        max_attempts = DEFAULT_MAX_ATTEMPTS
    max_attempts = min(6, max(1, max_attempts))
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            API_ROOT + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "decision-system-governance-resilient-client",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                if attempt > 1:
                    _audit(
                        {
                            "event": "request-recovered",
                            "method": method,
                            "path": path,
                            "attempt": attempt,
                            "status": int(getattr(response, "status", 200)),
                        }
                    )
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            body = exc.read().decode("utf-8", errors="replace")[:2000]
            retryable = exc.code in RETRYABLE_HTTP or _is_rate_limited(exc.code, headers)
            if retryable and attempt < max_attempts:
                delay, reason = _retry_delay(headers, attempt)
                _audit(
                    {
                        "event": "request-retry",
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "status": exc.code,
                        "delay_seconds": delay,
                        "reason": reason,
                        "rate_limit_remaining": _header(headers, "X-RateLimit-Remaining"),
                        "rate_limit_reset": _header(headers, "X-RateLimit-Reset"),
                    }
                )
                time.sleep(delay)
                continue
            _audit(
                {
                    "event": "request-failed",
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                    "status": exc.code,
                    "retryable": retryable,
                }
            )
            raise RuntimeError(
                f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < max_attempts:
                delay, reason = _retry_delay({}, attempt)
                _audit(
                    {
                        "event": "network-retry",
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "reason": reason,
                    }
                )
                time.sleep(delay)
                continue
            _audit(
                {
                    "event": "network-failed",
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                }
            )
            raise RuntimeError(f"GitHub API {method} {path} network failure: {exc}") from exc

    raise RuntimeError(f"GitHub API {method} {path} retry state exhausted")
