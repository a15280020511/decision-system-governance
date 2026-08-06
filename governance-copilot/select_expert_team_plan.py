#!/usr/bin/env python3
"""Create the authoritative expert-model plan in the governance center.

The expert center receives the resulting immutable plan and may only resolve an
exact provider endpoint for each named model. It must never rank, replace, or
select a different model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import rank_flagships_by_task_cost as cost_ranker
import select_paid_governance_flagship_model as flagship_selector

SCHEMA_VERSION = "governance-expert-model-plan-v1"
SELECTION_AUTHORITY = "decision-system-governance"
DEFAULT_EXPERT_COUNT = 4
MIN_EXPERT_COUNT = 3
MAX_EXPERT_COUNT = 6


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
        "User-Agent": "decision-system-governance-expert-selector/1.0",
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
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise ExpertPlanError(f"OpenRouter catalog request failed: {last_error}")


def _live_flagship_receipt(token: str) -> Mapping[str, Any]:
    model_query = urllib.parse.urlencode(
        {"sort": "pricing-low-to-high", "output_modalities": "text"}
    )
    benchmark_query = urllib.parse.urlencode({"source": "artificial-analysis"})
    model_payload = _fetch_json(
        f"{flagship_selector.MODELS_API}?{model_query}", token
    )
    rows = model_payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ExpertPlanError("OpenRouter model catalog is empty")
    benchmark_payload = _fetch_json(
        f"{flagship_selector.BENCHMARKS_API}?{benchmark_query}", token
    )
    return flagship_selector.select_from_catalog(
        [row for row in rows if isinstance(row, Mapping)],
        benchmark_payload,
    )


def _task_text(ticket: Mapping[str, Any]) -> str:
    task = ticket.get("task") if isinstance(ticket.get("task"), Mapping) else {}
    question = str(task.get("question") or "")
    requirements = task.get("requirements")
    requirement_text = "\n".join(
        str(value) for value in requirements or [] if isinstance(value, str)
    ) if isinstance(requirements, list) else ""
    return (question + "\n" + requirement_text).strip()


def _task_profile(ticket: Mapping[str, Any]) -> tuple[int, int]:
    text = _task_text(ticket)
    prompt_tokens = max(2_048, min(64_000, len(text) * 2 + 4_096))
    completion_tokens = 4_096
    return prompt_tokens, completion_tokens


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
        {
            "role_id": lens_id,
            "role_kind": "independent",
            "role": label,
        }
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
        raise ExpertPlanError("ranked model has no valid estimated task cost") from exc
    if not math.isfinite(value) or value < 0:
        raise ExpertPlanError("ranked model has invalid estimated task cost")
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
        f"not enough distinct-company strict flagship models: need {count}, found {len(chosen)}"
    )


def _model_record(row: Mapping[str, Any], *, slot: int) -> dict[str, Any]:
    return {
        "slot": slot,
        "model": str(row["model_id"]),
        "company": str(row["company"]),
        "estimated_task_cost_usd": _finite_cost(row),
        "prompt_usd_per_million": float(row.get("prompt_usd_per_million") or 0),
        "completion_usd_per_million": float(
            row.get("completion_usd_per_million") or 0
        ),
        "balanced_score": float(row.get("balanced_score") or 0),
        "selection_evidence": str(row.get("flagship_basis") or "qualified-flagship"),
    }


def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
    _, recovery_count, expert_count = _budget(ticket)
    prompt_tokens, completion_tokens = _task_profile(ticket)
    flagship_receipt = _live_flagship_receipt(token)
    ranking = cost_ranker.rank_flagships_by_task_cost(
        flagship_receipt,
        expected_prompt_tokens=prompt_tokens,
        expected_completion_tokens=completion_tokens,
    )
    rows = ranking.get("ranked_paid_flagship_candidates")
    if not isinstance(rows, list):
        raise ExpertPlanError("governance cost ranking produced no candidate list")

    strict_rows = [
        row
        for row in rows
        if row.get("strict_product_tier") is True
        and str(row.get("flagship_basis") or "") == "strict-product-tier"
    ]
    if not strict_rows:
        raise ExpertPlanError(
            "governance cost ranking produced no strict flagship candidates"
        )

    selected_rows = _distinct_company_rows(strict_rows, expert_count)
    selected_companies = {str(row["company"]) for row in selected_rows}
    recovery_rows = _distinct_company_rows(
        strict_rows,
        recovery_count,
        excluded=selected_companies,
    ) if recovery_count else []

    selected_models: list[dict[str, Any]] = []
    for slot, (row, role) in enumerate(zip(selected_rows, _roles(expert_count), strict=True), 1):
        selected_models.append({**_model_record(row, slot=slot), **role})
    recovery_models = [
        _model_record(row, slot=index)
        for index, row in enumerate(recovery_rows, 1)
    ]

    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selection_authority": SELECTION_AUTHORITY,
        "selection_policy": (
            "strict-product-tier-paid-general-purpose-flagships "
            "-> estimated-task-cost-ascending -> distinct-model-companies"
        ),
        "task_sha256": task_sha256(ticket),
        "task_cost_profile": {
            "expected_prompt_tokens": prompt_tokens,
            "expected_completion_tokens": completion_tokens,
        },
        "expert_count": expert_count,
        "recovery_count": recovery_count,
        "selected_models": selected_models,
        "recovery_models": recovery_models,
        "provider_selection_authority": "expert-runtime-exact-endpoint-resolution-only",
        "model_substitution_allowed": False,
        "expert_center_reranking_allowed": False,
        "cross_task_history_used": False,
        "source_selector_schema_version": flagship_receipt.get("schema_version"),
        "source_ranking_schema_version": ranking.get("schema_version"),
        "source_catalog_snapshot_sha256": ranking.get(
            "source_catalog_snapshot_sha256"
        ),
        "model_calls": 0,
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical_json(plan)).hexdigest()
    return plan


def enrich_ticket(ticket: Mapping[str, Any], token: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
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
