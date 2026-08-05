#!/usr/bin/env python3
"""Compatibility facade for the internal governance transport package.

Existing workflows and tests import this file by path. The implementation now
lives in ``governance_transport`` so every governance entrypoint shares one
retry, rate-limit, timeout and audit policy without adding a third-party
runtime dependency.

Compatibility contract: Retry-After, X-RateLimit-Reset,
X-RateLimit-Remaining, request-retry, network-retry, Authorization and token
handling remain enforced by the internal client.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance_transport import audit as _audit_module
from governance_transport import client as _client
from governance_transport import retry as _retry

API_ROOT = _client.API_ROOT
DEFAULT_MAX_ATTEMPTS = _retry.DEFAULT_MAX_ATTEMPTS
MAX_BACKOFF_SECONDS = 120
RETRYABLE_HTTP = {429, 502, 503, 504}
GitHubRequestError = _client.GitHubRequestError

if MAX_BACKOFF_SECONDS != _retry.MAX_BACKOFF_SECONDS:
    raise RuntimeError("governance transport backoff compatibility mismatch")
if RETRYABLE_HTTP != _retry.RETRYABLE_HTTP:
    raise RuntimeError("governance transport retryable HTTP compatibility mismatch")

# Compatibility aliases keep existing deterministic tests and callers stable.
urllib = _client.urllib
time = _client.time
_audit = _audit_module.audit_event
_header = _retry.header
_retry_delay = _retry.retry_delay
_is_rate_limited = _retry.is_rate_limited


def github_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: Any | None = None,
) -> Any:
    return _client.github_request(
        method,
        path,
        token=token,
        payload=payload,
    )


__all__ = [
    "API_ROOT",
    "DEFAULT_MAX_ATTEMPTS",
    "GitHubRequestError",
    "MAX_BACKOFF_SECONDS",
    "RETRYABLE_HTTP",
    "github_request",
]
