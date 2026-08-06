#!/usr/bin/env python3
"""Frozen execution-compatibility rules shared by governance expert selection.

Governance must apply the same task-envelope and authenticated ZDR endpoint
eligibility rules as the expert production runtime. This prevents a model from
being selected against the public endpoint inventory and then rejected when the
expert center intersects that inventory with the account's ZDR routes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "governance-expert-task-envelope-v2"
EXPERT_RUNTIME_SCHEMA_VERSION = "v5-minimal-task-envelope-1"
MINIMUM_CONTEXT_LENGTH = 16_384
FIXED_PROTOCOL_RESERVE = 8_192
ZDR_ENDPOINTS_API = "https://openrouter.ai/api/v1/endpoints/zdr"
ZDR_SELECTOR_SCHEMA_VERSION = (
    "governance-openrouter-zdr-executable-flagship-price-v3"
)


class ExpertTaskEnvelopeError(RuntimeError):
    """Raised when governance cannot reproduce expert runtime eligibility."""


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


def _zdr_endpoint_keys(selector: Any, token: str) -> frozenset[tuple[str, str]]:
    if not str(token or "").strip():
        raise ExpertTaskEnvelopeError(
            "OPENROUTER_API_KEY is required for authenticated ZDR endpoint qualification"
        )
    payload = selector._fetch_json(ZDR_ENDPOINTS_API, token)
    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise ExpertTaskEnvelopeError(
            "OpenRouter authenticated ZDR endpoint inventory is unavailable"
        )
    keys = {
        (
            str(row.get("model_id") or "").strip(),
            str(selector._provider_slug(row) or "").strip(),
        )
        for row in rows
        if isinstance(row, Mapping)
    }
    usable = frozenset(key for key in keys if all(key))
    if not usable:
        raise ExpertTaskEnvelopeError(
            "OpenRouter authenticated ZDR endpoint inventory is empty"
        )
    return usable


def patch_selector(selector: Any) -> None:
    """Bind one selector module to the frozen expert production contract."""
    selector._required_context_tokens = required_context_tokens
    selector.EXPERT_RUNTIME_MINIMUM_CONTEXT_LENGTH = MINIMUM_CONTEXT_LENGTH
    selector.EXPERT_RUNTIME_TASK_ENVELOPE_SCHEMA_VERSION = (
        EXPERT_RUNTIME_SCHEMA_VERSION
    )
    selector.EXPERT_RUNTIME_ZDR_ENDPOINTS_API = ZDR_ENDPOINTS_API

    if getattr(selector, "_expert_runtime_zdr_patch_applied", False):
        return

    original_model_record = selector._model_record
    original_build_plan = selector.build_plan
    zdr_cache: frozenset[tuple[str, str]] | None = None

    def qualify_candidate(
        candidate: Mapping[str, Any],
        token: str,
        required_context: int,
    ) -> dict[str, Any] | None:
        nonlocal zdr_cache
        if zdr_cache is None:
            zdr_cache = _zdr_endpoint_keys(selector, token)

        model_id = str(candidate.get("model_id") or "").strip()
        payload = selector._fetch_json(selector._endpoint_url(model_id), token)
        compatible = [
            row
            for row in selector._compatible_endpoint_inventory(
                candidate,
                payload,
                required_context,
            )
            if (model_id, str(row.get("provider") or "")) in zdr_cache
        ]
        if not compatible:
            return None

        qualified = dict(candidate)
        qualified.update(
            {
                "exact_endpoint_qualified": True,
                "zdr_endpoint_qualified": True,
                "qualified_provider_count": len(compatible),
                "endpoint_inventory_sha256": hashlib.sha256(
                    selector._canonical_json(compatible)
                ).hexdigest(),
                "required_context_tokens": required_context,
                "minimum_completion_tokens": selector.MINIMUM_COMPLETION_TOKENS,
            }
        )
        return qualified

    def model_record(row: Mapping[str, Any], *, slot: int) -> dict[str, Any]:
        if row.get("zdr_endpoint_qualified") is not True:
            raise ExpertTaskEnvelopeError(
                "ranked model has no authenticated ZDR endpoint qualification"
            )
        record = original_model_record(row, slot=slot)
        record["selection_evidence"] = (
            "explicit-product-tier-price-order+live-exact-endpoint-qualified+"
            "authenticated-zdr-endpoint-qualified"
        )
        return record

    def build_plan(
        ticket: Mapping[str, Any], token: str = ""
    ) -> dict[str, Any]:
        plan = original_build_plan(ticket, token)
        plan["selection_policy"] = (
            "openrouter-official-intelligence-top-150 -> paid-general-purpose-"
            "flagships -> live-exact-endpoint-qualified -> authenticated-zdr-"
            "endpoint-qualified -> combined-token-price-ascending -> "
            "distinct-model-companies"
        )
        plan["zdr_endpoint_qualification_required"] = True
        plan["zdr_endpoint_inventory_source"] = ZDR_ENDPOINTS_API
        plan["source_selector_schema_version"] = ZDR_SELECTOR_SCHEMA_VERSION
        plan["source_ranking_schema_version"] = ZDR_SELECTOR_SCHEMA_VERSION
        material = dict(plan)
        material.pop("plan_sha256", None)
        plan["plan_sha256"] = hashlib.sha256(
            selector._canonical_json(material)
        ).hexdigest()
        return plan

    selector._qualify_candidate = qualify_candidate
    selector._model_record = model_record
    selector.build_plan = build_plan
    selector.SELECTOR_SCHEMA_VERSION = ZDR_SELECTOR_SCHEMA_VERSION
    selector._expert_runtime_zdr_patch_applied = True
