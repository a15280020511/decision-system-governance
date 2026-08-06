#!/usr/bin/env python3
"""Frozen execution compatibility shared by governance expert selection paths."""
from __future__ import annotations

import json
from typing import Any, Mapping

SCHEMA_VERSION = "governance-expert-task-envelope-v2"
EXPERT_RUNTIME_SCHEMA_VERSION = "v5-minimal-task-envelope-1"
MINIMUM_CONTEXT_LENGTH = 16_384
FIXED_PROTOCOL_RESERVE = 8_192
MINIMUM_QUALIFIED_PROVIDER_COUNT = 2


class ExpertTaskEnvelopeError(RuntimeError):
    """Raised when governance cannot reproduce the expert execution envelope."""


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
    """Bind one loaded selector to the frozen runtime and provider redundancy floor."""
    selector._required_context_tokens = required_context_tokens
    selector.EXPERT_RUNTIME_MINIMUM_CONTEXT_LENGTH = MINIMUM_CONTEXT_LENGTH
    selector.EXPERT_RUNTIME_TASK_ENVELOPE_SCHEMA_VERSION = (
        EXPERT_RUNTIME_SCHEMA_VERSION
    )
    selector.MINIMUM_QUALIFIED_PROVIDER_COUNT = MINIMUM_QUALIFIED_PROVIDER_COUNT

    if getattr(selector, "_provider_redundancy_floor_patched", False):
        return
    original_qualify = selector._qualify_candidate

    def qualify_with_redundancy(
        candidate: Mapping[str, Any],
        token: str,
        required_context_tokens: int,
    ) -> dict[str, Any] | None:
        qualified = original_qualify(
            candidate,
            token,
            required_context_tokens,
        )
        if not isinstance(qualified, Mapping):
            return None
        provider_count = qualified.get("qualified_provider_count")
        if (
            isinstance(provider_count, bool)
            or not isinstance(provider_count, int)
            or provider_count < MINIMUM_QUALIFIED_PROVIDER_COUNT
        ):
            return None
        return dict(qualified)

    selector._qualify_candidate = qualify_with_redundancy
    selector._provider_redundancy_floor_patched = True
