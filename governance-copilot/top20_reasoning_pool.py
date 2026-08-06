#!/usr/bin/env python3
"""Attach a live OpenRouter top-weekly reasoning pool to expert plans.

Governance remains responsible for fetching, filtering and freezing the candidate
pool. The expert center may assign primary and recovery models only from the
frozen pool. No model call is made here.
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


def _company(model_id: str) -> str:
    return model_id.split("/", 1)[0].strip().casefold() if "/" in model_id else ""


def _raw_pool_rows(selector: Any, token: str) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
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
            f"OpenRouter returned only {len(pool)} ranked reasoning models; need {TOP20_POOL_SIZE}"
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


def _eligible_records(
    selector: Any,
    ticket: Mapping[str, Any],
    token: str,
    raw_pool: list[dict[str, Any]],
    raw_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    benchmark_query = urllib.parse.urlencode({"source": "artificial-analysis"})
    benchmark_payload = selector._fetch_json(
        f"{selector.BENCHMARKS_API}?{benchmark_query}", token
    )
    try:
        candidates = selector._catalog_candidates(raw_payload, benchmark_payload)
    except Exception as exc:  # noqa: BLE001 - preserve the selector's fail-closed semantics
        raise Top20ReasoningPoolError(
            f"top-20 reasoning flagship qualification failed: {exc}"
        ) from exc

    popularity = {str(row["model"]): int(row["popularity_rank"]) for row in raw_pool}
    intelligence = _intelligence_rank_map(selector, token)
    required_context = selector._required_context_tokens(ticket)
    qualified: list[dict[str, Any]] = []
    companies: set[str] = set()
    models: set[str] = set()
    for candidate in candidates:
        model_id = str(candidate.get("model_id") or "").strip()
        company = str(candidate.get("company") or "").strip().casefold()
        if model_id not in popularity or not company or model_id in models or company in companies:
            continue
        row = selector._qualify_candidate(candidate, token, required_context)
        if not isinstance(row, Mapping):
            continue
        normalized = dict(row)
        normalized["official_intelligence_rank"] = int(
            intelligence.get(model_id, 1_000_000)
        )
        record = selector._model_record(normalized, slot=len(qualified) + 1)
        record.update(
            {
                "popularity_rank": popularity[model_id],
                "source_pool_schema_version": POOL_SCHEMA_VERSION,
                "source_pool": POOL_SOURCE,
                "expert_center_selectable": True,
            }
        )
        qualified.append(record)
        companies.add(company)
        models.add(model_id)

    qualified.sort(
        key=lambda row: (
            float(row.get("price_rank_usd_per_million") or 0.0),
            int(row.get("popularity_rank") or 1_000_000),
            int(row.get("official_intelligence_rank") or 1_000_000),
            str(row.get("model") or ""),
        )
    )
    for slot, row in enumerate(qualified, 1):
        row["slot"] = slot
        row["candidate_price_rank"] = slot

    if len(qualified) < MINIMUM_EXECUTABLE_CANDIDATES:
        raise Top20ReasoningPoolError(
            "top-20 reasoning pool has insufficient distinct-company executable "
            f"candidates: need {MINIMUM_EXECUTABLE_CANDIDATES}, found {len(qualified)}"
        )
    return qualified


def attach_pool(selector: Any, ticket: Mapping[str, Any], plan: Mapping[str, Any], token: str) -> dict[str, Any]:
    raw_pool, raw_payload = _raw_pool_rows(selector, token)
    eligible = _eligible_records(selector, ticket, token, raw_pool, raw_payload)
    enriched = dict(plan)
    enriched.update(
        {
            "top20_reasoning_pool_schema_version": POOL_SCHEMA_VERSION,
            "top20_reasoning_pool_source": POOL_SOURCE,
            "top20_reasoning_pool_size": TOP20_POOL_SIZE,
            "top20_reasoning_models": raw_pool,
            "expert_selectable_candidates": eligible,
            "expert_selectable_candidate_count": len(eligible),
            "candidate_pool_authority": "decision-system-governance",
            "model_assignment_authority": "expert-assessment-center",
            "expert_center_pool_selection_allowed": True,
            "expert_center_pool_selection_policy": (
                "top20-reasoning-only -> executable-and-zdr-qualified -> "
                "different-company -> price-ascending -> four-primary-four-recovery"
            ),
            "legacy_governance_selected_models_are_preview_only": True,
        }
    )
    enriched["top20_reasoning_pool_sha256"] = hashlib.sha256(
        _canonical_json(raw_pool)
    ).hexdigest()
    enriched["expert_selectable_candidates_sha256"] = hashlib.sha256(
        _canonical_json(eligible)
    ).hexdigest()
    material = dict(enriched)
    material.pop("plan_sha256", None)
    enriched["plan_sha256"] = hashlib.sha256(_canonical_json(material)).hexdigest()
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
