#!/usr/bin/env python3
"""Frozen task-envelope compatibility shared by governance expert selection paths."""
from __future__ import annotations

import json
from typing import Any, Mapping

SCHEMA_VERSION = "governance-expert-task-envelope-v1"
EXPERT_RUNTIME_SCHEMA_VERSION = "v5-minimal-task-envelope-1"
MINIMUM_CONTEXT_LENGTH = 16_384
FIXED_PROTOCOL_RESERVE = 8_192


class ExpertTaskEnvelopeError(RuntimeError):
    """Raised when governance cannot reproduce the expert task envelope."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def required_context_tokens(ticket: Mapping[str, Any]) -> int:
    """Mirror the expert runtime floor and conservatively bound task characters."""
    task = ticket.get("task")
    if not isinstance(task, Mapping):
        raise ExpertTaskEnvelopeError("expert ticket has no task object")
    task_characters = len(_canonical_json(task))
    return max(
        MINIMUM_CONTEXT_LENGTH,
        task_characters + FIXED_PROTOCOL_RESERVE,
    )


def patch_selector(selector: Any) -> None:
    """Bind one loaded selector module to the frozen expert runtime envelope."""
    selector._required_context_tokens = required_context_tokens
    selector.EXPERT_RUNTIME_MINIMUM_CONTEXT_LENGTH = MINIMUM_CONTEXT_LENGTH
    selector.EXPERT_RUNTIME_TASK_ENVELOPE_SCHEMA_VERSION = (
        EXPERT_RUNTIME_SCHEMA_VERSION
    )
