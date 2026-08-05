"""Deterministic bounded retry and GitHub rate-limit handling."""
from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

RETRYABLE_HTTP = {429, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 4
MAX_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 120


def header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def retry_delay(headers: Mapping[str, Any], attempt: int) -> tuple[float, str]:
    retry_after = header(headers, "Retry-After").strip()
    if retry_after:
        try:
            return min(MAX_BACKOFF_SECONDS, max(1.0, float(retry_after))), "retry-after-seconds"
        except ValueError:
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    from datetime import timezone

                    when = when.replace(tzinfo=timezone.utc)
                delay = when.timestamp() - time.time()
                return min(MAX_BACKOFF_SECONDS, max(1.0, delay)), "retry-after-date"
            except (TypeError, ValueError, OverflowError):
                pass

    reset = header(headers, "X-RateLimit-Reset").strip()
    remaining = header(headers, "X-RateLimit-Remaining").strip()
    if reset and remaining == "0":
        try:
            delay = float(reset) - time.time() + 1.0
            return min(MAX_BACKOFF_SECONDS, max(1.0, delay)), "rate-limit-reset"
        except ValueError:
            pass

    exponential = min(MAX_BACKOFF_SECONDS, float(2 ** max(1, attempt)))
    return exponential, "bounded-exponential"


def is_rate_limited(code: int, headers: Mapping[str, Any]) -> bool:
    return (
        code == 429
        or header(headers, "Retry-After") != ""
        or (code == 403 and header(headers, "X-RateLimit-Remaining") == "0")
    )


def configured_max_attempts(
    *,
    env_name: str = "GOVERNANCE_HTTP_MAX_ATTEMPTS",
) -> int:
    try:
        configured = int(os.getenv(env_name, DEFAULT_MAX_ATTEMPTS))
    except ValueError:
        configured = DEFAULT_MAX_ATTEMPTS
    return min(MAX_ATTEMPTS, max(1, configured))
