#!/usr/bin/env python3
"""Create the governance-owned expert model plan.

Selection is intentionally simple:
1. Read the OpenRouter model catalog.
2. Keep paid, stable, general-purpose text models with an explicit flagship tier.
3. Sort by combined prompt and completion token price, low to high.
4. Take the first models from different companies.

The expert center only validates and executes the immutable result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

MODELS_API = "https://openrouter.ai/api/v1/models"
SCHEMA_VERSION = "governance-expert-model-plan-v1"
SELECTOR_SCHEMA_VERSION = "governance-openrouter-simple-flagship-price-v1"
SELECTION_AUTHORITY = "decision-system-governance"
DEFAULT_EXPERT_COUNT = 4
MIN_EXPERT_COUNT = 3
MAX_EXPERT_COUNT = 6

FLAGSHIP_TIER = re.compile(
    r"(?:^|[-_ /])(pro|max|opus|ultra|premier)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
EXCLUDED_TIER = re.compile(
    r"(?:^|[-_ /])"
    r"(flash|mini|nano|micro|small|lite|fast|instant|turbo|haiku|spark|"
    r"preview|experimental|beta)"
    r"(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
SPECIALIZED_MARKERS = (
    "coder",
    "code-",
    "-code",
    "content-safety",
    "safety",
    "guard",
    "embedding",
    "embed",
    "rerank",
    "moderation",
)


class ExpertPlanError(RuntimeError):
    """Raised when governance cannot form a complete fail-closed model plan."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def task_sha256(ticket: Mapping[str, Any]) -> str:
    task = ticket.get("task")
    if not isinstance(task, Mapping):
        raise ExpertPlanError("expert ticket has no task object")
    return hashlib.sha256(_canonical_json(task)).hexdigest()


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "decision-system-governance-expert-selector/2.0",
        "X-Title": "Decision System Governance Expert Selector",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ExpertPlanError(f"invalid JSON object from {url}")
            return payload
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise ExpertPlanError(f"OpenRouter catalog request failed: {last_error}")


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
    return value * 1_000_000


def _request_price(pricing: Mapping[str, Any]) -> float:
    value = _number(pricing.get("request"))
    return value if value is not None and value >= 0 else 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_general_text(row: Mapping[str, Any]) -> bool:
    architecture = _mapping(row.get("architecture"))
    inputs = architecture.get("input_modalities")
    outputs = architecture.get("output_modalities")
    return (
        isinstance(inputs, list)
        and "text" in inputs
        and isinstance(outputs, list)
        and outputs == ["text"]
    )


def _not_expired(row: Mapping[str, Any]) -> bool:
    raw = row.get("expiration_date")
    if raw in {None, ""}:
        return True
    try:
        return date.fromisoformat(str(raw)[:10]) >= date.today()
    except ValueError:
        return False


def _identity(row: Mapping[str, Any], model_id: str) -> str:
    model_name = model_id.split("/", 1)[-1]
    canonical = str(row.get("canonical_slug") or model_id).split("/", 1)[-1]
    name = str(row.get("name") or model_name)
    return " ".join((model_name, canonical, name))


def _is_general_flagship(identity: str) -> bool:
    lowered = identity.lower()
    return (
        bool(FLAGSHIP_TIER.search(identity))
        and not EXCLUDED_TIER.search(identity)
        and not any(marker in lowered for marker in SPECIALIZED_MARKERS)
    )


def _catalog_candidates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ExpertPlanError("OpenRouter model catalog is empty")

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id in seen or "/" not in model_id:
            continue
        seen.add(model_id)
        if not _is_general_text(row) or not _not_expired(row):
            continue
        if not _is_general_flagship(_identity(row, model_id)):
            continue

        pricing = _mapping(row.get("pricing"))
        prompt = _price_per_million(pricing, "prompt")
        completion = _price_per_million(pricing, "completion")
        if prompt is None or completion is None or prompt + completion <= 0:
            continue

        company = model_id.split("/", 1)[0]
        combined = prompt + completion
        candidates.append(
            {
                "model_id": model_id,
                "company": company,
                "prompt_usd_per_million": prompt,
                "completion_usd_per_million": completion,
                "request_usd": _request_price(pricing),
                "price_rank_usd_per_million": combined,
                "estimated_task_cost_usd": combined,
                "flagship_basis": "explicit-product-tier",
            }
        )

    candidates.sort(
        key=lambda row: (
            float(row["price_rank_usd_per_million"]),
            float(row["request_usd"]),
            float(row["prompt_usd_per_million"]),
            float(row["completion_usd_per_million"]),
            str(row["model_id"]),
        )
    )
    if not candidates:
        raise ExpertPlanError("no paid general-purpose flagship model is available")
    return candidates


def _live_flagship_rows(token: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"sort": "pricing-low-to-high", "output_modalities": "text"}
    )
    payload = _fetch_json(f"{MODELS_API}?{query}", token)
    return _catalog_candidates(payload)


def _budget(ticket: Mapping[str, Any]) -> tuple[int, int, int]:
    budget = ticket.get("approved_budget")
    if not isinstance(budget, Mapping):
        raise ExpertPlanError("expert ticket has no approved_budget object")
    calls = budget.get("calls")
    recovery = budget.get("maximum_recovery_calls")
    if isinstance(calls, bool) or not isinstance(calls, int) or not 4 <= calls <= 16:
        raise ExpertPlanError("approved_budget.calls must be an integer from 4 to 16")
    if (
        isinstance(recovery, bool)
        or not isinstance(recovery, int)
        or not 0 <= recovery <= 4
    ):
        raise ExpertPlanError(
            "approved_budget.maximum_recovery_calls must be an integer from 0 to 4"
        )
    initial_capacity = calls - recovery
    if initial_capacity < MIN_EXPERT_COUNT:
        raise ExpertPlanError("budget must leave capacity for at least three experts")
    expert_count = min(DEFAULT_EXPERT_COUNT, initial_capacity, MAX_EXPERT_COUNT)
    return calls, recovery, expert_count


def _roles(expert_count: int) -> list[dict[str, str]]:
    lenses = (
        ("evidence", "独立分析专家：重点检查证据、事实、数据质量、关键假设与不确定性"),
        ("options", "独立分析专家：重点检查备选方案、机制、因果链与反事实"),
        ("risk", "独立分析专家：重点检查风险、失败模式、约束、边界与实施条件"),
        ("stakeholders", "独立分析专家：重点检查利益相关方、激励、二阶效应与现实扰动"),
    )
    independent_count = expert_count - 2
    roles = [
        {"role_id": lens_id, "role_kind": "independent", "role": label}
        for lens_id, label in lenses[:independent_count]
    ]
    roles.extend(
        [
            {
                "role_id": "review",
                "role_kind": "review",
                "role": "交叉审查专家：比较前序分析，找出冲突、遗漏、薄弱证据和失败模式",
            },
            {
                "role_id": "synthesis",
                "role_kind": "synthesis",
                "role": "最终综合专家：依据原始任务和全部前序结果形成唯一完整交付",
            },
        ]
    )
    return roles


def _finite_cost(row: Mapping[str, Any]) -> float:
    try:
        value = float(row.get("estimated_task_cost_usd"))
    except (TypeError, ValueError) as exc:
        raise ExpertPlanError("ranked model has no valid price") from exc
    if not math.isfinite(value) or value < 0:
        raise ExpertPlanError("ranked model has invalid price")
    return value


def _distinct_company_rows(
    rows: Sequence[Mapping[str, Any]], count: int, excluded: set[str] | None = None
) -> list[Mapping[str, Any]]:
    excluded = set(excluded or ())
    chosen: list[Mapping[str, Any]] = []
    companies = set(excluded)
    models: set[str] = set()
    for row in rows:
        model = str(row.get("model_id") or "").strip()
        company = str(row.get("company") or "").strip()
        if not model or not company or model in models or company in companies:
            continue
        _finite_cost(row)
        chosen.append(row)
        models.add(model)
        companies.add(company)
        if len(chosen) == count:
            return chosen
    raise ExpertPlanError(
        f"not enough distinct-company flagship models: need {count}, found {len(chosen)}"
    )


def _model_record(row: Mapping[str, Any], *, slot: int) -> dict[str, Any]:
    return {
        "slot": slot,
        "model": str(row["model_id"]),
        "company": str(row["company"]),
        "estimated_task_cost_usd": _finite_cost(row),
        "price_rank_usd_per_million": float(row["price_rank_usd_per_million"]),
        "prompt_usd_per_million": float(row["prompt_usd_per_million"]),
        "completion_usd_per_million": float(row["completion_usd_per_million"]),
        "selection_evidence": "explicit-product-tier-price-order",
    }


def _catalog_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    source = [
        {
            "model_id": row["model_id"],
            "company": row["company"],
            "prompt_usd_per_million": row["prompt_usd_per_million"],
            "completion_usd_per_million": row["completion_usd_per_million"],
            "request_usd": row["request_usd"],
            "price_rank_usd_per_million": row["price_rank_usd_per_million"],
        }
        for row in rows
    ]
    return hashlib.sha256(_canonical_json(source)).hexdigest()


def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
    _, recovery_count, expert_count = _budget(ticket)
    rows = _live_flagship_rows(token)

    selected_rows = _distinct_company_rows(rows, expert_count)
    selected_companies = {str(row["company"]) for row in selected_rows}
    recovery_rows = (
        _distinct_company_rows(
            rows,
            recovery_count,
            excluded=selected_companies,
        )
        if recovery_count
        else []
    )

    selected_models = [
        {**_model_record(row, slot=slot), **role}
        for slot, (row, role) in enumerate(
            zip(selected_rows, _roles(expert_count), strict=True), 1
        )
    ]
    recovery_models = [
        _model_record(row, slot=index)
        for index, row in enumerate(recovery_rows, 1)
    ]

    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selection_authority": SELECTION_AUTHORITY,
        "selection_policy": (
            "openrouter-paid-general-purpose-flagships "
            "-> combined-token-price-ascending -> distinct-model-companies"
        ),
        "price_rank_basis": "prompt_usd_per_million + completion_usd_per_million",
        "task_sha256": task_sha256(ticket),
        "expert_count": expert_count,
        "recovery_count": recovery_count,
        "selected_models": selected_models,
        "recovery_models": recovery_models,
        "provider_selection_authority": (
            "expert-runtime-exact-endpoint-resolution-only"
        ),
        "model_substitution_allowed": False,
        "expert_center_reranking_allowed": False,
        "cross_task_history_used": False,
        "source_selector_schema_version": SELECTOR_SCHEMA_VERSION,
        "source_ranking_schema_version": SELECTOR_SCHEMA_VERSION,
        "source_catalog_snapshot_sha256": _catalog_sha256(rows),
        "model_calls": 0,
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical_json(plan)).hexdigest()
    return plan


def enrich_ticket(
    ticket: Mapping[str, Any], token: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    if "governance_model_plan" in ticket:
        raise ExpertPlanError("ticket already contains a governance_model_plan")
    plan = build_plan(ticket, token)
    enriched = dict(ticket)
    enriched["governance_model_plan"] = plan
    return enriched, plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--output-ticket", required=True)
    parser.add_argument("--output-plan", required=True)
    args = parser.parse_args()
    ticket = json.loads(Path(args.ticket).read_text(encoding="utf-8"))
    if not isinstance(ticket, Mapping):
        raise SystemExit("ticket root must be an object")
    enriched, plan = enrich_ticket(
        ticket,
        os.getenv("OPENROUTER_API_KEY", ""),
    )
    Path(args.output_ticket).write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.output_plan).write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "selection_authority": SELECTION_AUTHORITY,
                "expert_count": plan["expert_count"],
                "recovery_count": plan["recovery_count"],
                "plan_sha256": plan["plan_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
