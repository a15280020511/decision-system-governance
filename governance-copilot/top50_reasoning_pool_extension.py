#!/usr/bin/env python3
"""Attach a live OpenRouter Top-50 weekly reasoning pool to expert plans.

Governance freezes model identities and model-level metadata only. Expert-center
assignment must implement the signed task-adaptive value principles. Provider
selection remains unrestricted and is delegated entirely to OpenRouter. No
model is called here.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
from typing import Any, Mapping

TOP50_POOL_SIZE = 50
MINIMUM_EXECUTABLE_COMPANIES = 8
POOL_SCHEMA_VERSION = "governance-openrouter-top50-reasoning-pool-v2-open-provider"
POOL_SOURCE = "openrouter-most-popular-last-week-token-volume"
POPULARITY_PERIOD = "week"
SELECTION_PRINCIPLES = [
    "concrete-problem-concrete-analysis",
    "dynamic-adaptation",
    "small-effort-large-return",
]
SELECTION_EVIDENCE = (
    "openrouter-top-weekly-reasoning+model-metadata-qualified+"
    "unrestricted-openrouter-provider-routing"
)


class Top50ReasoningPoolError(RuntimeError):
    """Raised when a complete model-level Top-50 pool cannot be formed."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
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


def _request_price(pricing: Mapping[str, Any]) -> float:
    value = _number(pricing.get("request"))
    return value if value is not None and value >= 0 else 0.0


def _company(model_id: str) -> str:
    return model_id.split("/", 1)[0].strip().casefold() if "/" in model_id else ""


def _raw_pool_rows(
    selector: Any, token: str
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "sort": "most-popular",
            "output_modalities": "text",
            "supported_parameters": "reasoning",
        }
    )
    payload = selector._fetch_json(f"{selector.MODELS_API}?{query}", token)
    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise Top50ReasoningPoolError("OpenRouter weekly model response is invalid")

    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_rank, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id in seen or "/" not in model_id:
            continue
        parameters = row.get("supported_parameters")
        supports_reasoning = isinstance(parameters, list) and "reasoning" in {
            str(value or "").strip().casefold() for value in parameters
        }
        if not supports_reasoning:
            continue
        pricing = _mapping(row.get("pricing"))
        architecture = _mapping(row.get("architecture"))
        top_provider = _mapping(row.get("top_provider"))
        pool.append(
            {
                "popularity_rank": len(pool) + 1,
                "source_rank": source_rank,
                "model": model_id,
                "company": _company(model_id),
                "name": str(row.get("name") or model_id),
                "canonical_slug": str(row.get("canonical_slug") or model_id),
                "context_length": int(row.get("context_length") or 0),
                "max_completion_tokens": int(
                    top_provider.get("max_completion_tokens") or 0
                ),
                "prompt_usd_per_million": _price_per_million(pricing, "prompt"),
                "completion_usd_per_million": _price_per_million(pricing, "completion"),
                "request_usd": _request_price(pricing),
                "expiration_date": row.get("expiration_date"),
                "input_modalities": list(architecture.get("input_modalities") or []),
                "output_modalities": list(architecture.get("output_modalities") or []),
                "supported_parameters": [str(value) for value in parameters],
                "reasoning_supported": True,
                "pool_source": POOL_SOURCE,
                "popularity_period": POPULARITY_PERIOD,
                "provider_routing_mode": "unrestricted-openrouter",
            }
        )
        seen.add(model_id)
        if len(pool) == TOP50_POOL_SIZE:
            break

    if len(pool) != TOP50_POOL_SIZE:
        raise Top50ReasoningPoolError(
            f"OpenRouter returned only {len(pool)} ranked reasoning models; need {TOP50_POOL_SIZE}"
        )
    return pool, payload


def _intelligence_rank_map(selector: Any, token: str) -> dict[str, int]:
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
        raise Top50ReasoningPoolError("OpenRouter intelligence ranking is unavailable")
    result: dict[str, int] = {}
    for rank, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            model_id = str(row.get("id") or "").strip()
            if model_id and model_id not in result:
                result[model_id] = rank
    return result


def _direct_candidate(
    pool_row: Mapping[str, Any], intelligence_rank: int
) -> dict[str, Any] | None:
    model_id = str(pool_row.get("model") or "").strip()
    company = str(pool_row.get("company") or "").strip().casefold()
    prompt = _number(pool_row.get("prompt_usd_per_million"))
    completion = _number(pool_row.get("completion_usd_per_million"))
    if not model_id or not company or prompt is None or completion is None or prompt < 0 or completion < 0:
        return None
    combined = prompt + completion
    return {
        "model_id": model_id,
        "company": company,
        "official_intelligence_rank": intelligence_rank,
        "context_length": int(pool_row.get("context_length") or 0),
        "max_completion_tokens": int(pool_row.get("max_completion_tokens") or 0),
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": float(pool_row.get("request_usd") or 0.0),
        "price_rank_usd_per_million": combined,
        "estimated_task_cost_usd": combined,
        "reasoning_parameter_required": True,
        "popularity_rank": int(pool_row["popularity_rank"]),
    }


def _candidate_record(candidate: Mapping[str, Any], slot: int, required_context: int) -> dict[str, Any]:
    return {
        "slot": slot,
        "candidate_price_rank": slot,
        "model": str(candidate["model_id"]),
        "company": str(candidate["company"]),
        "estimated_task_cost_usd": float(candidate["estimated_task_cost_usd"]),
        "price_rank_usd_per_million": float(candidate["price_rank_usd_per_million"]),
        "prompt_usd_per_million": float(candidate["prompt_usd_per_million"]),
        "completion_usd_per_million": float(candidate["completion_usd_per_million"]),
        "request_usd": float(candidate.get("request_usd") or 0.0),
        "official_intelligence_rank": int(candidate.get("official_intelligence_rank") or 1_000_000),
        "popularity_rank": int(candidate["popularity_rank"]),
        "context_length": int(candidate.get("context_length") or 0),
        "max_completion_tokens": int(candidate.get("max_completion_tokens") or 0),
        "required_context_tokens": int(required_context),
        "reasoning_rank_verified": True,
        "reasoning_supported": True,
        "ranking_basis": POOL_SOURCE,
        "popularity_period": POPULARITY_PERIOD,
        "source_pool_schema_version": POOL_SCHEMA_VERSION,
        "source_pool": POOL_SOURCE,
        "selection_evidence": SELECTION_EVIDENCE,
        "expert_center_selectable": True,
        "provider_routing_mode": "unrestricted-openrouter",
        "provider_restrictions_applied": False,
    }


def _exclusion(pool_row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "model": str(pool_row.get("model") or ""),
        "company": str(pool_row.get("company") or "").strip().casefold(),
        "popularity_rank": int(pool_row.get("popularity_rank") or 0),
        "reason": reason,
        "expert_center_selectable": False,
    }


def _eligible_records(
    selector: Any,
    ticket: Mapping[str, Any],
    token: str,
    raw_pool: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    intelligence = _intelligence_rank_map(selector, token)
    required_context = int(selector._required_context_tokens(ticket))
    qualified: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    stable_model_id = getattr(selector, "_stable_model_id", None)
    for pool_row in raw_pool:
        model_id = str(pool_row.get("model") or "").strip()
        if not model_id or model_id in seen_models:
            continue
        seen_models.add(model_id)
        if callable(stable_model_id) and not stable_model_id(model_id):
            exclusions.append(_exclusion(pool_row, "unstable-or-route-suffixed-model-id"))
            continue
        candidate = _direct_candidate(pool_row, int(intelligence.get(model_id, 1_000_000)))
        if candidate is None:
            exclusions.append(_exclusion(pool_row, "invalid-or-missing-price-metadata"))
            continue
        if int(candidate.get("context_length") or 0) < required_context:
            exclusions.append(_exclusion(pool_row, "model-context-below-task-requirement"))
            continue
        qualified.append(_candidate_record(candidate, len(qualified) + 1, required_context))

    qualified.sort(
        key=lambda row: (
            float(row["price_rank_usd_per_million"]),
            int(row["popularity_rank"]),
            int(row["official_intelligence_rank"]),
            str(row["model"]),
        )
    )
    for slot, row in enumerate(qualified, 1):
        row["slot"] = slot
        row["candidate_price_rank"] = slot

    exclusions.sort(key=lambda row: (int(row["popularity_rank"]), str(row["model"])))
    distinct_companies = {
        str(row.get("company") or "").strip().casefold()
        for row in qualified
        if str(row.get("company") or "").strip()
    }
    if len(distinct_companies) < MINIMUM_EXECUTABLE_COMPANIES:
        raise Top50ReasoningPoolError(
            "top-50 reasoning pool has insufficient distinct-company executable candidates: "
            f"need {MINIMUM_EXECUTABLE_COMPANIES}, found {len(distinct_companies)}"
        )
    return qualified, exclusions


def attach_pool(
    selector: Any,
    ticket: Mapping[str, Any],
    plan: Mapping[str, Any],
    token: str,
) -> dict[str, Any]:
    raw_pool, _ = _raw_pool_rows(selector, token)
    eligible, exclusions = _eligible_records(selector, ticket, token, raw_pool)
    distinct_company_count = len({str(row["company"]).strip().casefold() for row in eligible})
    enriched = dict(plan)
    enriched.update(
        {
            "top50_reasoning_pool_schema_version": POOL_SCHEMA_VERSION,
            "top50_reasoning_pool_source": POOL_SOURCE,
            "top50_reasoning_pool_period": POPULARITY_PERIOD,
            "top50_reasoning_pool_size": TOP50_POOL_SIZE,
            "top50_reasoning_models": raw_pool,
            "top50_expert_selectable_candidates": eligible,
            "top50_expert_selectable_candidate_count": len(eligible),
            "top50_expert_selectable_distinct_company_count": distinct_company_count,
            "top50_expert_ineligible_models": exclusions,
            "top50_expert_ineligible_model_count": len(exclusions),
            "top50_candidate_pool_authority": "decision-system-governance",
            "top50_model_assignment_authority": "expert-assessment-center-ortools",
            "expert_center_top50_pool_selection_allowed": True,
            "top50_task_adaptive_assignment_required": True,
            "top50_model_assignment_principles": list(SELECTION_PRINCIPLES),
            "top50_assignment_recomputed_from_current_task": True,
            "top50_cross_task_history_allowed": False,
            "top50_semantic_keyword_routing_allowed": False,
            "top50_domain_hardcoding_allowed": False,
            "top50_provider_metric_allowed_in_assignment": False,
            "expert_center_top50_pool_selection_policy": (
                "weekly-top50-reasoning-model-metadata-qualified -> current-task-"
                "structural-demand-profile -> dynamic-cost-quality-capacity-marginal-return-"
                "ortools-cp-sat-four-primary-four-warm-recovery -> openrouter-unrestricted-"
                "provider-routing"
            ),
            "top50_provider_routing_mode": "unrestricted-openrouter",
            "top50_provider_restrictions_applied": False,
            "top50_provider_endpoint_qualification_required": False,
            "top50_zdr_provider_qualification_required": False,
            "top50_old_flagship_filter_applied": False,
            "top50_route_suffixed_models_preserved_but_not_executed": True,
            "top50_model_calls": 0,
        }
    )
    enriched["top50_reasoning_pool_sha256"] = hashlib.sha256(_canonical_json(raw_pool)).hexdigest()
    enriched["top50_expert_selectable_candidates_sha256"] = hashlib.sha256(_canonical_json(eligible)).hexdigest()
    enriched["top50_expert_ineligible_models_sha256"] = hashlib.sha256(_canonical_json(exclusions)).hexdigest()
    material = dict(enriched)
    material.pop("plan_sha256", None)
    enriched["plan_sha256"] = hashlib.sha256(_canonical_json(material)).hexdigest()
    return enriched


def patch_selector(selector: Any) -> None:
    """Wrap a selector after the legacy Top-20 wrapper and attach Top-50 fields."""
    if getattr(selector, "_top50_reasoning_pool_patched", False):
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
    selector.TOP50_MODEL_ASSIGNMENT_PRINCIPLES = tuple(SELECTION_PRINCIPLES)
    selector._top50_reasoning_pool_patched = True
