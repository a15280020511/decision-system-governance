"""Redacted JSONL audit support for governance transport events."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "body",
    "credential",
    "key",
    "payload",
    "secret",
    "token",
)
MAX_TEXT_LENGTH = 1000


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if _is_sensitive_key(key) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return value[:MAX_TEXT_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_TEXT_LENGTH]


def audit_event(
    event: Mapping[str, Any],
    *,
    env_name: str = "GOVERNANCE_HTTP_AUDIT_FILE",
) -> None:
    """Append one redacted event when the configured audit file is present."""
    path_text = os.getenv(env_name, "").strip()
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        **_sanitize(event),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
