#!/usr/bin/env python3
"""Attach a live OpenRouter top-weekly reasoning pool to expert plans.

The top-20 ranking itself is the candidate universe. Governance freezes the
server order and qualifies exact executable endpoints; it does not run the old
company-flagship or benchmark preselection over this pool. No model call is
made here.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
from typing import Any, Mapping

TOP20_POOL_SIZE = 20
MINIMUM_EXECUTABLE_CANDIDATES = 8
POOL_SCHEMA_VERSION = "governance-openrouter-top20-reasoning-pool-v1"
POOL_SOURCE = "openrouter-most-popular-last-week-token-volume"
SELECTION_EVIDENCE = (
    "openrouter-top-weekly-reasoning+live-exact-endpoint-qualified+"
    "authenticated-zdr-endpoint-qualified"
)


class Top20ReasoningPoolError(RuntimeError):
    """Raised when a complete frozen top-20 reasoning pool cannot be formed."""


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
        raise Top20ReasoningPoolError("OpenRouter top-weekly model response is invalid")

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
        expiration = row.get("expiration_date")
        pricing = _mapping(row.get("pricing"))
        prompt = _price_per_million(pricing, "prompt")
        completion = _price_per_million(pricing, "completion")
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
                "prompt_usd_per_million": prompt,
                "completion_usd_per_million": completion,
                "request_usd": _request_price(pricing),
                "expiration_date": expiration,
                "input_modalities": list(architecture.get("input_modalities") or []),
                "output_modalities": list(architecture.get("output_modalities") or []),
                "supported_parameters": [str(value) for value in parameters],
                "reasoning_supported": True,
                "pool_source": POOL_SOURCE,
            }
        )
        seen.add(model_id)
        if len(pool) == TOP20_POOL_SIZE:
            break

    if len(pool) != TOP20_POOL_SIZE:
        raise Top20ReasoningPoolError(
            f"OpenRouter returned only {len(pool)} ranked reasoning models; "
            f"need {TOP20_POOL_SIZE}"
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
        raise Top20ReasoningPoolError("OpenRouter intelligence ranking is unavailable")
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
    if (
        not model_id
        or not company
        or prompt is None
        or completion is None
        or prompt < 0
        or completion < 0
    ):
        return None
    combined = prompt + completion
    return {
        "model_id": model_id,
        "company": company,
        "official_intelligence_rank": intelligence_rank,
        "context_length": int(pool_row.get("context_length") or 0),
        "max_completion_tokens": int(
            pool_row.get("max_completion_tokens") or 0
        ),
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": float(pool_row.get("request_usd") or 0.0),
        "price_rank_usd_per_million": combined,
        "estimated_task_cost_usd": combined,
        "reasoning_parameter_required": True,
        "popularity_rank": int(pool_row["popularity_rank"]),
    }


def _candidate_record(
    qualified: Mapping[str, Any], slot: int
) -> dict[str, Any]:
    return {
        "slot": slot,
        "candidate_price_rank": slot,
        "model": str(qualified["model_id"]),
        "company": str(qualified["company"]),
        "estimated_task_cost_usd": float(
            qualified["estimated_task_cost_usd"]
        ),
        "price_rank_usd_per_million": float(
            qualified["price_rank_usd_per_million"]
        ),
        "prompt_usd_per_million": float(
            qualified["prompt_usd_per_million"]
        ),
        "completion_usd_per_million": float(
            qualified["completion_usd_per_million"]
        ),
        "request_usd": float(qualified.get("request_usd") or 0.0),
        "official_intelligence_rank": int(
            qualified.get("official_intelligence_rank") or 1_000_000
        ),
        "popularity_rank": int(qualified["popularity_rank"]),
        "qualified_provider_count": int(
            qualified["qualified_provider_count"]
        ),
        "endpoint_inventory_sha256": str(
            qualified["endpoint_inventory_sha256"]
        ),
        "required_context_tokens": int(
            qualified["required_context_tokens"]
        ),
        "minimum_completion_tokens": int(
            qualified["minimum_completion_tokens"]
        ),
        "reasoning_rank_verified": True,
        "reasoning_supported": True,
        "ranking_basis": POOL_SOURCE,
        "source_pool_schema_version": POOL_SCHEMA_VERSION,
        "source_pool": POOL_SOURCE,
        "selection_evidence": SELECTION_EVIDENCE,
        "expert_center_selectable": True,
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
    required_context = selector._required_context_tokens(ticket)
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
            exclusions.append(
                _exclusion(pool_row, "unstable-or-route-suffixed-model-id")
            )
            continue
        candidate = _direct_candidate(
            pool_row,
            int(intelligence.get(model_id, 1_000_000)),
        )
        if candidate is None:
            exclusions.append(_exclusion(pool_row, "invalid-or-missing-price-metadata"))
            continue
        row = selector._qualify_candidate(candidate, token, required_context)
        if not isinstance(row, Mapping):
            exclusions.append(
                _exclusion(pool_row, "no-compatible-authenticated-zdr-endpoint")
            )
            continue
        normalized = dict(row)
        normalized["popularity_rank"] = int(pool_row["popularity_rank"])
        qualified.append(_candidate_record(normalized, len(qualified) + 1))

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

    exclusions.sort(
        key=lambda row: (
            int(row["popularity_rank"]),
            str(row["model"]),
        )
    )
    distinct_companies = {
        str(row.get("company") or "").strip().casefold()
        for row in qualified
        if str(row.get("company") or "").strip()
    }
    if len(distinct_companies) < MINIMUM_EXECUTABLE_CANDIDATES:
        raise Top20ReasoningPoolError(
            "top-20 reasoning pool has insufficient distinct-company executable "
            f"candidates: need {MINIMUM_EXECUTABLE_CANDIDATES}, "
            f"found {len(distinct_companies)}"
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
    distinct_company_count = len(
        {
            str(row["company"]).strip().casefold()
            for row in eligible
        }
    )
    enriched = dict(plan)
    enriched.update(
        {
            "top20_reasoning_pool_schema_version": POOL_SCHEMA_VERSION,
            "top20_reasoning_pool_source": POOL_SOURCE,
            "top20_reasoning_pool_size": TOP20_POOL_SIZE,
            "top20_reasoning_models": raw_pool,
            "expert_selectable_candidates": eligible,
            "expert_selectable_candidate_count": len(eligible),
            "expert_selectable_distinct_company_count": distinct_company_count,
            "expert_ineligible_top20_models": exclusions,
            "expert_ineligible_top20_model_count": len(exclusions),
            "candidate_pool_authority": "decision-system-governance",
            "model_assignment_authority": "expert-assessment-center",
            "expert_center_pool_selection_allowed": True,
            "expert_center_pool_selection_policy": (
                "top20-reasoning-ranking-is-candidate-universe -> "
                "exact-executable-zdr-endpoint-qualified -> distinct-company -> "
                "price-ascending -> four-primary-four-recovery"
            ),
            "old_flagship_filter_applied_to_top20_pool": False,
            "route_suffixed_models_preserved_in_raw_pool_but_not_executed": True,
            "legacy_governance_selected_models_are_preview_only": True,
        }
    )
    enriched["top20_reasoning_pool_sha256"] = hashlib.sha256(
        _canonical_json(raw_pool)
    ).hexdigest()
    enriched["expert_selectable_candidates_sha256"] = hashlib.sha256(
        _canonical_json(eligible)
    ).hexdigest()
    enriched["expert_ineligible_top20_models_sha256"] = hashlib.sha256(
        _canonical_json(exclusions)
    ).hexdigest()
    material = dict(enriched)
    material.pop("plan_sha256", None)
    enriched["plan_sha256"] = hashlib.sha256(
        _canonical_json(material)
    ).hexdigest()
    return enriched


def patch_selector(selector: Any) -> None:
    """Wrap one governance selector so every expert plan carries the live pool."""
    if getattr(selector, "_top20_reasoning_pool_patched", False):
        return
    original_build_plan = selector.build_plan

    def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
        if not str(token or "").strip():
            raise Top20ReasoningPoolError("OPENROUTER_API_KEY is required")
        plan = original_build_plan(ticket, token)
        return attach_pool(selector, ticket, plan, token)

    selector.build_plan = build_plan
    selector.TOP20_REASONING_POOL_SCHEMA_VERSION = POOL_SCHEMA_VERSION
    selector.TOP20_REASONING_POOL_SIZE = TOP20_POOL_SIZE
    selector._top20_reasoning_pool_patched = True
