"""Canonical request identity and idempotency primitives."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

V3 = "governance-control-ticket-v3"
V4 = "governance-control-ticket-v4"
SUPPORTED = {V3, V4}
CLIENT_REQUEST_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def packet_from_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def normalize_client_request_id(value: Any) -> str:
    return str(value).lower() if isinstance(value, str) else ""


def is_canonical_client_request_id(value: Any) -> bool:
    normalized = normalize_client_request_id(value)
    return bool(CLIENT_REQUEST_ID_RE.fullmatch(normalized))


def fingerprint_packet(packet: Mapping[str, Any]) -> str:
    material = {
        "route": packet.get("route"),
        "ticket": packet.get("ticket"),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
