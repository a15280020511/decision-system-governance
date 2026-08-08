#!/usr/bin/env python3
"""Attach the live OpenRouter reasoning-popularity catalog as expert candidates.

Governance defines the candidate *source* as models that OpenRouter reports as
reasoning-capable and orders that source by current ``most-popular`` usage. It
never truncates the source to a fixed Top-N and never applies price, flagship,
company, Provider, ZDR, endpoint, context, free-first, Canary, or optimizer
qualification gates. Those fields remain advisory metadata for the Expert
Center's current-task optimizer.

In addition to the unrestricted public catalog, governance best-effort fetches
OpenRouter's authenticated ``/api/v1/models/user`` view. OpenRouter documents that
view as filtered by the current user's provider preferences, privacy settings and
guardrails. Membership is attached only as transport-compatibility telemetry; it
never removes a model from the normal candidate pool and never changes Provider
routing. The Expert Center may use the signal after a real transport failure (for
example an account-credit 402 followed by zero-cost recovery) to avoid obviously
incompatible endpoints without weakening the account's privacy policy.

The only hard model-execution boundary declared by governance is no-tools: every
candidate is marked as forbidden from tools/functions/search/browser/MCP and the
Expert Center must enforce that boundary on both request and response.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
from typing import Any, Mapping

TOP50_POOL_SIZE = 50  # compatibility constant only; never an execution limit
MINIMUM_EXECUTABLE_COMPANIES = 0
POOL_SCHEMA_VERSION = "governance-openrouter-reasoning-popularity-pool-v4-user-policy-telemetry"
POOL_SOURCE = "openrouter-live-reasoning-most-popular-catalog"
POPULARITY_PERIOD = "openrouter-most-popular-live"
USER_POLICY_SOURCE = "openrouter-authenticated-models-user"
SELECTION_PRINCIPLES = [
    "concrete-problem-concrete-analysis",
    "dynamic-adaptation",
    "small-effort-large-return",
]
SELECTION_EVIDENCE = (
    "live-reasoning-popularity-identity+unrestricted-openrouter-provider-routing"
)


class Top50ReasoningPoolError(RuntimeError):
    """Compatibility error type for malformed upstream catalog responses."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price_per_million(pricing: Mapping[str, Any], key: str) -> float | None:
    value = _number(pricing.get(key))
    if value is None or value < 0:
        return None
    return value * 1_000_000 if value < 0.1 else value


def _company(model_id: str) -> str:
    return (
        model_id.split("/", 1)[0].strip().casefold()
        if "/" in model_id
        else "unknown"
    )


def _fetch_rows(selector: Any, token: str) -> list[Mapping[str, Any]]:
    """Fetch the full live reasoning-capable popularity sequence.

    ``supported_parameters=reasoning`` and text output define the requested
    reasoning leaderboard source. They are not post-fetch business gates.
    No fixed Top-N is requested or applied.
    """
    query = urllib.parse.urlencode(
        {
            "sort": "most-popular",
            "supported_parameters": "reasoning",
            "output_modalities": "text",
        }
    )
    payload = selector._fetch_json(f"{selector.MODELS_API}?{query}", token)
    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise Top50ReasoningPoolError("OpenRouter model response is invalid")
    return [row for row in rows if isinstance(row, Mapping)]


def _user_models_url(selector: Any) -> str:
    base = str(selector.MODELS_API).rstrip("/")
    return f"{base}/user"


def _user_policy_model_ids(
    selector: Any,
    token: str,
) -> tuple[set[str] | None, dict[str, Any]]:
    """Fetch account-policy compatibility as non-gating advisory telemetry.

    ``None`` means the authenticated view could not be obtained, so absence must
    never be interpreted as incompatibility. An actual set (including an empty
    set) means the upstream request succeeded and membership is authoritative for
    the current account/key view at this instant.
    """
    try:
        payload = selector._fetch_json(_user_models_url(selector), token)
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise Top50ReasoningPoolError("OpenRouter /models/user response is invalid")
        model_ids = {
            str(row.get("id") or "").strip()
            for row in rows
            if isinstance(row, Mapping) and str(row.get("id") or "").strip()
        }
        return model_ids, {
            "available": True,
            "source": USER_POLICY_SOURCE,
            "model_count": len(model_ids),
            "used_as_normal_candidate_gate": False,
            "used_to_change_provider_routing": False,
            "cross_task_history_used": False,
        }
    except Exception as exc:  # noqa: BLE001 - telemetry must never gate the pool
        return None, {
            "available": False,
            "source": USER_POLICY_SOURCE,
            "model_count": None,
            "error_type": type(exc).__name__,
            "used_as_normal_candidate_gate": False,
            "used_to_change_provider_routing": False,
            "cross_task_history_used": False,
        }


def _intelligence_rank_map(selector: Any, token: str) -> dict[str, int]:
    """Best-effort advisory intelligence ranking; never candidate eligibility."""
    try:
        query = urllib.parse.urlencode(
            {
                "sort": "intelligence-high-to-low",
                "output_modalities": "text",
                "supported_parameters": "reasoning",
            }
        )
        payload = selector._fetch_json(f"{selector.MODELS_API}?{query}", token)
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            return {}
        result: dict[str, int] = {}
        for rank, row in enumerate(rows, 1):
            if isinstance(row, Mapping):
                model_id = str(row.get("id") or "").strip()
                if model_id and model_id not in result:
                    result[model_id] = rank
        return result
    except Exception:  # noqa: BLE001 - advisory metadata must never gate execution
        return {}


def _candidate_record(
    row: Mapping[str, Any],
    source_rank: int,
    intelligence_rank: int | None,
    user_policy_model_ids: set[str] | None,
) -> dict[str, Any] | None:
    model_id = str(row.get("id") or "").strip()
    if not model_id:
        return None
    pricing = _mapping(row.get("pricing"))
    architecture = _mapping(row.get("architecture"))
    top_provider = _mapping(row.get("top_provider"))
    prompt = _price_per_million(pricing, "prompt")
    completion = _price_per_million(pricing, "completion")
    parameters = row.get("supported_parameters")
    parameter_list = (
        [str(value) for value in parameters]
        if isinstance(parameters, list)
        else []
    )
    reasoning_supported = "reasoning" in {
        value.casefold() for value in parameter_list
    }
    combined = (prompt or 0.0) + (completion or 0.0)
    if user_policy_model_ids is None:
        user_policy_compatible: bool | None = None
    else:
        user_policy_compatible = model_id in user_policy_model_ids
    return {
        "slot": source_rank,
        "candidate_price_rank": source_rank,
        "model": model_id,
        "company": _company(model_id),
        "name": str(row.get("name") or model_id),
        "canonical_slug": str(row.get("canonical_slug") or model_id),
        "source_rank": source_rank,
        "popularity_rank": source_rank,
        "popularity_source": POPULARITY_PERIOD,
        "official_intelligence_rank": intelligence_rank or source_rank,
        "intelligence_rank_verified": intelligence_rank is not None,
        "context_length": int(row.get("context_length") or 0),
        "max_completion_tokens": int(
            top_provider.get("max_completion_tokens") or 0
        ),
        "prompt_usd_per_million": float(prompt or 0.0),
        "completion_usd_per_million": float(completion or 0.0),
        "price_rank_usd_per_million": float(combined),
        "request_usd": float(_number(pricing.get("request")) or 0.0),
        "input_modalities": list(architecture.get("input_modalities") or []),
        "output_modalities": list(architecture.get("output_modalities") or []),
        "supported_parameters": parameter_list,
        "reasoning_supported": reasoning_supported,
        "reasoning_rank_verified": intelligence_rank is not None,
        "selection_evidence": SELECTION_EVIDENCE,
        "candidate_source": "reasoning-popularity-board",
        "expert_center_selectable": True,
        "provider_routing_mode": "unrestricted-openrouter",
        "provider_restrictions_applied": False,
        "qualification_gates_applied": False,
        "user_policy_compatibility_source": USER_POLICY_SOURCE,
        "user_policy_compatible": user_policy_compatible,
        "user_policy_compatibility_is_normal_gate": False,
        "tool_use_forbidden": True,
        "tools_allowed": False,
        "external_tool_capability_exposed": False,
    }


def _candidate_inventory(
    selector: Any,
    token: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _fetch_rows(selector, token)
    intelligence = _intelligence_rank_map(selector, token)
    user_policy_model_ids, user_policy_audit = _user_policy_model_ids(selector, token)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_rank, row in enumerate(rows, 1):
        candidate = _candidate_record(
            row,
            source_rank,
            intelligence.get(str(row.get("id") or "").strip()),
            user_policy_model_ids,
        )
        if candidate is None:
            continue
        model_id = str(candidate["model"])
        if model_id in seen:
            continue
        result.append(candidate)
        seen.add(model_id)
    if not result:
        raise Top50ReasoningPoolError(
            "OpenRouter returned no reasoning-popularity model identities"
        )
    user_policy_audit = dict(user_policy_audit)
    if user_policy_model_ids is not None:
        user_policy_audit["candidate_pool_compatible_count"] = sum(
            1 for row in result if row.get("user_policy_compatible") is True
        )
        user_policy_audit["candidate_pool_incompatible_count"] = sum(
            1 for row in result if row.get("user_policy_compatible") is False
        )
    else:
        user_policy_audit["candidate_pool_compatible_count"] = None
        user_policy_audit["candidate_pool_incompatible_count"] = None
    return result, user_policy_audit


def attach_pool(
    selector: Any,
    ticket: Mapping[str, Any],
    plan: Mapping[str, Any],
    token: str,
) -> dict[str, Any]:
    del ticket
    candidates, user_policy_audit = _candidate_inventory(selector, token)
    distinct_company_count = len({str(row["company"]) for row in candidates})
    enriched = dict(plan)
    enriched.update(
        {
            "expert_candidate_pool_schema_version": POOL_SCHEMA_VERSION,
            "expert_candidate_pool_source": POOL_SOURCE,
            "expert_candidate_pool": candidates,
            "expert_candidate_pool_size": len(candidates),
            "expert_candidate_pool_distinct_company_count": distinct_company_count,
            "expert_candidate_pool_fixed_size": False,
            "expert_candidate_pool_top50_only": False,
            # Compatibility booleans remain false because reasoning/text are
            # source-definition fields, not post-discovery admission gates.
            "expert_candidate_pool_reasoning_only_required": False,
            "expert_candidate_pool_text_only_required": False,
            "expert_candidate_pool_reasoning_popularity_source": True,
            "expert_candidate_pool_intelligence_rank_required": False,
            "expert_candidate_pool_price_required": False,
            "expert_candidate_pool_context_gate_required": False,
            "expert_candidate_pool_company_diversity_required": False,
            "candidate_pool_authority": "decision-system-governance",
            "model_assignment_authority": (
                "expert-assessment-center-dynamic-ortools"
            ),
            "expert_center_pool_selection_allowed": True,
            "task_adaptive_assignment_required": True,
            "model_assignment_principles": list(SELECTION_PRINCIPLES),
            "assignment_recomputed_from_current_task": True,
            "cross_task_history_allowed": False,
            "provider_routing_mode": "unrestricted-openrouter",
            "provider_restrictions_applied": False,
            "provider_endpoint_qualification_required": False,
            "zdr_provider_qualification_required": False,
            "user_policy_compatibility_telemetry": user_policy_audit,
            "user_policy_compatibility_normal_candidate_gate_required": False,
            "fixed_team_size_required": False,
            "fixed_four_plus_four_required": False,
            "company_uniqueness_required": False,
            "optimizer_optimality_required": False,
            "free_first_required": False,
            "canary_required_before_execution": False,
            "price_filter_required": False,
            "flagship_filter_required": False,
            "intelligence_rank_required": False,
            "tool_use_forbidden": True,
            "tools_allowed": False,
            "only_hard_model_boundary": "no-tools",
            "model_calls": 0,
            # Historical Top50 names are aliases only; contents are the entire
            # live reasoning-popularity sequence and are never size-limited.
            "top50_reasoning_pool_schema_version": POOL_SCHEMA_VERSION,
            "top50_reasoning_pool_source": POOL_SOURCE,
            "top50_reasoning_pool_period": POPULARITY_PERIOD,
            "top50_reasoning_pool_size": len(candidates),
            "top50_reasoning_models": candidates,
            "top50_expert_selectable_candidates": candidates,
            "top50_expert_selectable_candidate_count": len(candidates),
            "top50_expert_selectable_distinct_company_count": distinct_company_count,
            "top50_candidate_pool_authority": "decision-system-governance",
            "top50_model_assignment_authority": (
                "expert-assessment-center-dynamic-ortools"
            ),
            "expert_center_top50_pool_selection_allowed": True,
            "top50_provider_routing_mode": "unrestricted-openrouter",
            "top50_provider_restrictions_applied": False,
            "top50_provider_endpoint_qualification_required": False,
            "top50_zdr_provider_qualification_required": False,
            "top50_old_flagship_filter_applied": False,
            "top50_model_calls": 0,
        }
    )
    pool_hash = hashlib.sha256(_canonical_json(candidates)).hexdigest()
    enriched["expert_candidate_pool_sha256"] = pool_hash
    enriched["top50_reasoning_pool_sha256"] = pool_hash
    enriched["top50_expert_selectable_candidates_sha256"] = pool_hash
    material = dict(enriched)
    material.pop("plan_sha256", None)
    enriched["plan_sha256"] = hashlib.sha256(_canonical_json(material)).hexdigest()
    return enriched


def patch_selector(selector: Any) -> None:
    if getattr(selector, "_dynamic_reasoning_pool_patched", False):
        return
    original_build_plan = selector.build_plan

    def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
        if not str(token or "").strip():
            raise Top50ReasoningPoolError("OPENROUTER_API_KEY is required")
        plan = original_build_plan(ticket, token)
        return attach_pool(selector, ticket, plan, token)

    selector.build_plan = build_plan
    selector.TOP50_REASONING_POOL_SCHEMA_VERSION = POOL_SCHEMA_VERSION
    selector.TOP50_REASONING_POOL_SIZE = TOP50_POOL_SIZE
    selector.TOP50_MODEL_ASSIGNMENT_PRINCIPLES = list(SELECTION_PRINCIPLES)
    selector._dynamic_reasoning_pool_patched = True
    selector._top50_reasoning_pool_patched = True


__all__ = [
    "POOL_SCHEMA_VERSION",
    "POOL_SOURCE",
    "POPULARITY_PERIOD",
    "SELECTION_PRINCIPLES",
    "Top50ReasoningPoolError",
    "attach_pool",
    "patch_selector",
]
