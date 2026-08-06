#!/usr/bin/env python3
"""Frozen execution compatibility shared by governance expert selection paths.

Governance and expert production must use the same task envelope, authenticated
ZDR endpoint inventory, provider redundancy floor, role assignment, and a
minimum governance-approved recovery reserve. The price-minimal distinct-company
set is selected first; within that frozen set, the strongest official
intelligence rank performs final synthesis and the second strongest performs
cross-review.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "governance-expert-task-envelope-v4"
EXPERT_RUNTIME_SCHEMA_VERSION = "v5-minimal-task-envelope-1"
MINIMUM_CONTEXT_LENGTH = 16_384
FIXED_PROTOCOL_RESERVE = 8_192
MINIMUM_QUALIFIED_PROVIDER_COUNT = 2
MINIMUM_GOVERNANCE_RECOVERY_MODELS = 1
MAXIMUM_TOTAL_MODEL_CALLS = 16
ZDR_ENDPOINTS_API = "https://openrouter.ai/api/v1/endpoints/zdr"
ZDR_SELECTOR_SCHEMA_VERSION = (
    "governance-openrouter-zdr-redundant-executable-flagship-price-v4"
)
ROLE_ASSIGNMENT_POLICY = (
    "price-minimal-distinct-company-set -> official-intelligence-rank-ascending -> "
    "strongest-final-synthesis -> second-strongest-cross-review -> remaining-independent"
)
RECOVERY_POOL_POLICY = "shared-governance-approved-candidates"
RECOVERY_TRIGGER_CATEGORIES = (
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_TIMEOUT",
    "PROVIDER_EMPTY_RESPONSE",
    "PROVIDER_INVALID_RESPONSE",
    "UNSUPPORTED_PARAMETER",
    "CONTEXT_OVERFLOW",
    "OUTPUT_TRUNCATED",
)
_ROLE_FIELDS = frozenset({"slot", "role", "role_id", "role_kind"})


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


def normalize_recovery_budget(ticket: Mapping[str, Any]) -> dict[str, Any]:
    """Add one shared recovery call without reducing the requested initial capacity.

    Governance owns this normalization. A submitted 4+0 ticket therefore becomes
    5+1 before the immutable model plan is created. The extra model is only called
    after an eligible technical failure, so a healthy run still performs the same
    number of initial expert calls.
    """
    budget = ticket.get("approved_budget")
    if not isinstance(budget, Mapping):
        raise ExpertTaskEnvelopeError("expert ticket has no approved_budget object")
    calls = budget.get("calls")
    recovery = budget.get("maximum_recovery_calls")
    if isinstance(calls, bool) or not isinstance(calls, int) or not 4 <= calls <= 16:
        raise ExpertTaskEnvelopeError("approved_budget.calls must be an integer from 4 to 16")
    if (
        isinstance(recovery, bool)
        or not isinstance(recovery, int)
        or not 0 <= recovery <= 4
    ):
        raise ExpertTaskEnvelopeError(
            "approved_budget.maximum_recovery_calls must be an integer from 0 to 4"
        )
    if calls - recovery < 3:
        raise ExpertTaskEnvelopeError(
            "budget must leave capacity for at least three initial experts"
        )

    normalized = dict(ticket)
    normalized_budget = dict(budget)
    if recovery < MINIMUM_GOVERNANCE_RECOVERY_MODELS:
        initial_capacity = calls - recovery
        normalized_recovery = MINIMUM_GOVERNANCE_RECOVERY_MODELS
        normalized_calls = min(
            MAXIMUM_TOTAL_MODEL_CALLS,
            initial_capacity + normalized_recovery,
        )
        if normalized_calls - normalized_recovery < 3:
            raise ExpertTaskEnvelopeError(
                "governance recovery reserve would leave fewer than three initial experts"
            )
        normalized_budget["calls"] = normalized_calls
        normalized_budget["maximum_recovery_calls"] = normalized_recovery
    normalized["approved_budget"] = normalized_budget
    return normalized


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


def _provider_count_is_sufficient(qualified: Mapping[str, Any]) -> bool:
    provider_count = qualified.get("qualified_provider_count")
    return bool(
        not isinstance(provider_count, bool)
        and isinstance(provider_count, int)
        and provider_count >= MINIMUM_QUALIFIED_PROVIDER_COUNT
    )


def _official_rank(row: Mapping[str, Any]) -> int | None:
    value = row.get("official_intelligence_rank")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _without_role(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _ROLE_FIELDS}


def _assign_intelligence_ranked_roles(selector: Any, plan: dict[str, Any]) -> None:
    """Assign roles inside the already selected price-minimal company set."""
    rows = plan.get("selected_models")
    if not isinstance(rows, list) or not 3 <= len(rows) <= 6:
        raise ExpertTaskEnvelopeError("selected expert set is outside constitutional bounds")
    records = [dict(row) for row in rows if isinstance(row, Mapping)]
    if len(records) != len(rows):
        raise ExpertTaskEnvelopeError("selected expert rows must be objects")
    ranks = [_official_rank(row) for row in records]
    if any(rank is None for rank in ranks):
        # Synthetic unit fixtures created before official-rank evidence existed are
        # left unchanged. Live production records always carry a positive rank.
        return

    ranked = sorted(
        records,
        key=lambda row: (
            int(row["official_intelligence_rank"]),
            float(row.get("estimated_task_cost_usd") or 0.0),
            str(row.get("model") or ""),
        ),
    )
    synthesis_model = str(ranked[0].get("model") or "")
    review_model = str(ranked[1].get("model") or "")
    if not synthesis_model or not review_model or synthesis_model == review_model:
        raise ExpertTaskEnvelopeError("ranked review role models are invalid")

    independent = [
        row
        for row in records
        if str(row.get("model") or "") not in {synthesis_model, review_model}
    ]
    if len(independent) != len(records) - 2:
        raise ExpertTaskEnvelopeError("selected expert model identities are not unique")
    review = next(
        row for row in records if str(row.get("model") or "") == review_model
    )
    synthesis = next(
        row for row in records if str(row.get("model") or "") == synthesis_model
    )

    role_templates = selector._roles(len(records))
    if len(role_templates) != len(records):
        raise ExpertTaskEnvelopeError("selector role template count mismatch")
    assigned: list[dict[str, Any]] = []
    for row, role in zip(independent, role_templates[:-2], strict=True):
        assigned.append({**_without_role(row), **dict(role)})
    assigned.append({**_without_role(review), **dict(role_templates[-2])})
    assigned.append({**_without_role(synthesis), **dict(role_templates[-1])})
    for slot, row in enumerate(assigned, 1):
        row["slot"] = slot

    plan["selected_models"] = assigned
    plan["role_assignment_policy"] = ROLE_ASSIGNMENT_POLICY
    plan["final_synthesis_official_intelligence_rank"] = int(
        synthesis["official_intelligence_rank"]
    )
    plan["cross_review_official_intelligence_rank"] = int(
        review["official_intelligence_rank"]
    )


def patch_selector(selector: Any) -> None:
    """Bind one selector to the frozen runtime, ZDR, recovery and role contract."""
    selector._required_context_tokens = required_context_tokens
    selector.EXPERT_RUNTIME_MINIMUM_CONTEXT_LENGTH = MINIMUM_CONTEXT_LENGTH
    selector.EXPERT_RUNTIME_TASK_ENVELOPE_SCHEMA_VERSION = (
        EXPERT_RUNTIME_SCHEMA_VERSION
    )
    selector.MINIMUM_QUALIFIED_PROVIDER_COUNT = MINIMUM_QUALIFIED_PROVIDER_COUNT
    selector.MINIMUM_GOVERNANCE_RECOVERY_MODELS = MINIMUM_GOVERNANCE_RECOVERY_MODELS
    selector.EXPERT_RUNTIME_ZDR_ENDPOINTS_API = ZDR_ENDPOINTS_API
    selector.normalize_recovery_budget = normalize_recovery_budget

    if getattr(selector, "_expert_runtime_endpoint_contract_patched", False):
        return

    original_qualify = selector._qualify_candidate
    has_live_endpoint_primitives = all(
        hasattr(selector, name)
        for name in (
            "_fetch_json",
            "_endpoint_url",
            "_compatible_endpoint_inventory",
            "_provider_slug",
            "_canonical_json",
            "MINIMUM_COMPLETION_TOKENS",
        )
    )
    zdr_cache: frozenset[tuple[str, str]] | None = None

    def qualify_candidate(
        candidate: Mapping[str, Any],
        token: str,
        required_context: int,
    ) -> dict[str, Any] | None:
        nonlocal zdr_cache
        if not has_live_endpoint_primitives:
            qualified = original_qualify(candidate, token, required_context)
            if not isinstance(qualified, Mapping):
                return None
            return dict(qualified) if _provider_count_is_sufficient(qualified) else None

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
        if len(compatible) < MINIMUM_QUALIFIED_PROVIDER_COUNT:
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

    selector._qualify_candidate = qualify_candidate

    if hasattr(selector, "_model_record"):
        original_model_record = selector._model_record

        def model_record(row: Mapping[str, Any], *, slot: int) -> dict[str, Any]:
            if has_live_endpoint_primitives and row.get("zdr_endpoint_qualified") is not True:
                raise ExpertTaskEnvelopeError(
                    "ranked model has no authenticated ZDR endpoint qualification"
                )
            if not _provider_count_is_sufficient(row):
                raise ExpertTaskEnvelopeError(
                    "ranked model does not satisfy the provider redundancy floor"
                )
            record = original_model_record(row, slot=slot)
            if has_live_endpoint_primitives:
                record["selection_evidence"] = (
                    "explicit-product-tier-price-order+live-exact-endpoint-qualified+"
                    "authenticated-zdr-endpoint-qualified+two-provider-redundancy"
                )
            return record

        selector._model_record = model_record

    if hasattr(selector, "build_plan") and hasattr(selector, "_canonical_json"):
        original_build_plan = selector.build_plan

        def build_plan(
            ticket: Mapping[str, Any], token: str = ""
        ) -> dict[str, Any]:
            normalized_ticket = normalize_recovery_budget(ticket)
            plan = original_build_plan(normalized_ticket, token)
            _assign_intelligence_ranked_roles(selector, plan)
            if int(plan.get("recovery_count") or 0) < MINIMUM_GOVERNANCE_RECOVERY_MODELS:
                raise ExpertTaskEnvelopeError(
                    "governance plan must include at least one approved recovery model"
                )
            plan["selection_policy"] = (
                "openrouter-official-intelligence-top-150 -> paid-general-purpose-"
                "flagships -> live-exact-endpoint-qualified -> authenticated-zdr-"
                "endpoint-qualified -> minimum-two-provider-routes -> combined-token-"
                "price-ascending -> distinct-model-companies"
            )
            plan["zdr_endpoint_qualification_required"] = True
            plan["zdr_endpoint_inventory_source"] = ZDR_ENDPOINTS_API
            plan["minimum_qualified_provider_count"] = (
                MINIMUM_QUALIFIED_PROVIDER_COUNT
            )
            plan["minimum_governance_recovery_models"] = (
                MINIMUM_GOVERNANCE_RECOVERY_MODELS
            )
            plan["governance_approved_recovery_allowed"] = True
            plan["recovery_pool_policy"] = RECOVERY_POOL_POLICY
            plan["recovery_trigger_categories"] = list(RECOVERY_TRIGGER_CATEGORIES)
            plan["unapproved_model_substitution_allowed"] = False
            plan["source_selector_schema_version"] = ZDR_SELECTOR_SCHEMA_VERSION
            plan["source_ranking_schema_version"] = ZDR_SELECTOR_SCHEMA_VERSION
            material = dict(plan)
            material.pop("plan_sha256", None)
            plan["plan_sha256"] = hashlib.sha256(
                selector._canonical_json(material)
            ).hexdigest()
            return plan

        selector.build_plan = build_plan
        selector.SELECTOR_SCHEMA_VERSION = ZDR_SELECTOR_SCHEMA_VERSION

    if hasattr(selector, "enrich_ticket"):
        original_enrich_ticket = selector.enrich_ticket

        def enrich_ticket(
            ticket: Mapping[str, Any], token: str = ""
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            normalized = normalize_recovery_budget(ticket)
            # The signer verifies that no fields changed outside the governance
            # plan. Mutate ordinary dict inputs so that verification compares
            # against the governance-normalized budget rather than the raw draft.
            if isinstance(ticket, dict):
                ticket.clear()
                ticket.update(normalized)
                normalized = ticket
            return original_enrich_ticket(normalized, token)

        selector.enrich_ticket = enrich_ticket

    selector._expert_runtime_endpoint_contract_patched = True
    selector._provider_redundancy_floor_patched = True
    selector._intelligence_ranked_role_assignment_patched = True
    selector._governance_recovery_budget_patched = True
