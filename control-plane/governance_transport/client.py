"""Bounded GitHub REST client for short-lived governance workflows."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from .audit import audit_event
from .retry import (
    MAX_BACKOFF_SECONDS,
    RETRYABLE_HTTP,
    configured_max_attempts,
    header,
    is_rate_limited,
    retry_delay,
)

API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_ERROR_BODY_CHARS = 2000


class GitHubRequestError(RuntimeError):
    """Structured transport error that remains compatible with RuntimeError."""

    def __init__(
        self,
        message: str,
        *,
        method: str,
        path: str,
        status: int | None,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.path = path
        self.status = status
        self.retryable = retryable


def _request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None,
) -> urllib.request.Request:
    if not path.startswith("/"):
        raise ValueError("GitHub API path must start with /")
    data = None if payload is None else json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return urllib.request.Request(
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


def github_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Execute one GitHub request with bounded, auditable retries.

    Only transient network failures, HTTP 429, rate-limit HTTP 403, and
    HTTP 502/503/504 are retried. Authentication and validation failures stop
    immediately. Token values and response bodies are never written to audit.
    """
    if not token:
        raise RuntimeError("GitHub token is not configured")
    method = method.upper().strip()
    max_attempts = configured_max_attempts()

    for attempt in range(1, max_attempts + 1):
        request = _request(method, path, token=token, payload=payload)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                if attempt > 1:
                    audit_event(
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
            headers: Mapping[str, Any] = dict(exc.headers.items()) if exc.headers else {}
            body = exc.read().decode("utf-8", errors="replace")[:MAX_ERROR_BODY_CHARS]
            retryable = exc.code in RETRYABLE_HTTP or is_rate_limited(exc.code, headers)
            if retryable and attempt < max_attempts:
                delay, reason = retry_delay(headers, attempt)
                audit_event(
                    {
                        "event": "request-retry",
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "status": exc.code,
                        "delay_seconds": delay,
                        "reason": reason,
                        "rate_limit_remaining": header(headers, "X-RateLimit-Remaining"),
                        "rate_limit_reset": header(headers, "X-RateLimit-Reset"),
                    }
                )
                time.sleep(delay)
                continue
            audit_event(
                {
                    "event": "request-failed",
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                    "status": exc.code,
                    "retryable": retryable,
                }
            )
            raise GitHubRequestError(
                f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}",
                method=method,
                path=path,
                status=exc.code,
                retryable=retryable,
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < max_attempts:
                delay, reason = retry_delay({}, attempt)
                audit_event(
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
            audit_event(
                {
                    "event": "network-failed",
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                }
            )
            raise GitHubRequestError(
                f"GitHub API {method} {path} network failure: {exc}",
                method=method,
                path=path,
                status=None,
                retryable=True,
            ) from exc

    raise GitHubRequestError(
        f"GitHub API {method} {path} retry state exhausted",
        method=method,
        path=path,
        status=None,
        retryable=True,
    )


__all__ = [
    "API_ROOT",
    "DEFAULT_TIMEOUT_SECONDS",
    "GitHubRequestError",
    "MAX_BACKOFF_SECONDS",
    "RETRYABLE_HTTP",
    "github_request",
]
