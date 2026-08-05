#!/usr/bin/env python3
"""Build an immutable expert-team model plan in the governance center.

This module is the only active authority for expert model selection. It reads the
current OpenRouter model and benchmark catalogs, identifies paid general-purpose
flagships, ranks them by the expected cost of the submitted task, resolves one
exact provider endpoint for every selected or recovery model, and embeds a
complete execution proposal into the child ticket.

The expert center must only validate and execute this plan. It must never fetch a
catalog, rank models, replace models, or fall back to a local selector.
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

from rank_flagships_by_task_cost import rank_flagships_by_task_cost
from select_paid_governance_flagship_model import (
    BENCHMARKS_API,
    MODELS_API,
    select as select_flagships,
    select_from_catalog,
)

MODELS_ENDPOINT_TEMPLATE = (
    "https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints"
)
MIN_EXPERT_COUNT = 3
DEFAULT_EXPERT_COUNT = 4
MAX_EXPERT_COUNT = 6
MIN_COMPLETION_TOKENS = 1024
DEFAULT_COMPLETION_TOKENS = 4096
SYNTHESIS_COMPLETION_TOKENS = 6144
EXCLUDED_EXPERT_COMPANIES = frozenset({"openai", "anthropic"})


class ExpertModelSelectionError(RuntimeError):
    """Raised when governance cannot produce a complete fail-closed plan."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _company(model_id: str) -> str:
    return str(model_id or "").split("/", 1)[0].strip().casefold()


def _task_text(ticket: Mapping[str, Any]) -> str:
    task = ticket.get("task")
    if not isinstance(task, Mapping):
        raise ExpertModelSelectionError("expert ticket task must be an object")
    question = str(task.get("question") or "").strip()
    if not question:
        raise ExpertModelSelectionError("expert ticket task.question is empty")
    parts = [question]
    requirements = task.get("requirements")
    if isinstance(requirements, Sequence) and not isinstance(
        requirements, (str, bytes)
    ):
        rows = [str(value).strip() for value in requirements if str(value).strip()]
        if rows:
            parts.append("要求：\n" + "\n".join(f"- {value}" for value in rows))
    language = str(task.get("language") or "").strip()
    if language:
        parts.append(f"输出语言：{language}")
    evidence = ticket.get("evidence")
    if evidence:
        parts.append("治理中心提供的证据输入：\n" + _canonical_json(evidence))
    return "\n\n".join(parts)


def _budget(ticket: Mapping[str, Any]) -> tuple[int, int, int]:
    budget = ticket.get("approved_budget")
    if not isinstance(budget, Mapping):
        raise ExpertModelSelectionError("approved_budget is missing")
    total = int(budget.get("calls") or 0)
    recovery = int(budget.get("maximum_recovery_calls") or 0)
    if not 4 <= total <= 16:
        raise ExpertModelSelectionError("approved_budget.calls must be 4..16")
    if not 0 <= recovery < total:
        raise ExpertModelSelectionError("invalid recovery reserve")
    initial = total - recovery
    expert_count = min(DEFAULT_EXPERT_COUNT, initial, MAX_EXPERT_COUNT)
    if expert_count < MIN_EXPERT_COUNT:
        raise ExpertModelSelectionError(
            "budget must leave at least three initial expert calls"
        )
    return total, recovery, expert_count


def _task_envelope(task_text: str) -> dict[str, Any]:
    required_context = max(16_384, len(task_text) + 8_192)
    return {
        "schema_version": "governance-expert-task-envelope-v1",
        "task_sha256": hashlib.sha256(task_text.encode("utf-8")).hexdigest(),
        "task_characters": len(task_text),
        "required_context_tokens": required_context,
        "completion_capacity_advisory_tokens": SYNTHESIS_COMPLETION_TOKENS,
        "completion_advisory_affects_eligibility": False,
        "local_token_ceiling_enforced": False,
        "decomposition_authority": "decision-system-governance",
        "selection_authority": "decision-system-governance",
        "local_task_classification_used": False,
        "cross_task_history_used": False,
    }


def _request_json(url: str, token: str) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "decision-system-governance-expert-selector/1.0",
        "X-Title": "Decision System Governance Expert Selector",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ExpertModelSelectionError(
                    f"OpenRouter returned a non-object for {url}"
                )
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    raise ExpertModelSelectionError(
        f"OpenRouter endpoint resolution failed for {url}: {last_error}"
    )


def _endpoint_url(model_id: str) -> str:
    if "/" not in model_id:
        raise ExpertModelSelectionError(f"invalid model id: {model_id}")
    author, slug = model_id.split("/", 1)
    return MODELS_ENDPOINT_TEMPLATE.format(
        author=urllib.parse.quote(author, safe=""),
        slug=urllib.parse.quote(slug, safe=""),
    )


def _endpoint_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("endpoints"), list):
        return [row for row in data["endpoints"] if isinstance(row, Mapping)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(payload.get("endpoints"), list):
        return [
            row for row in payload["endpoints"] if isinstance(row, Mapping)
        ]
    return []


def _provider(row: Mapping[str, Any]) -> str:
    for key in ("tag", "provider_slug", "provider", "name", "provider_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _ppm(value: Any) -> float:
    result = _number(value, -1.0)
    if result < 0:
        return -1.0
    return result * 1_000_000 if result < 0.1 else result


def _exact_endpoint(
    candidate: Mapping[str, Any],
    *,
    token: str,
    required_context: int,
    prompt_tokens: int,
    completion_tokens: int,
    intelligence_rank: int,
) -> dict[str, Any]:
    model_id = str(candidate.get("model_id") or "").strip()
    rows = _endpoint_rows(_request_json(_endpoint_url(model_id), token))
    eligible: list[dict[str, Any]] = []
    for row in rows:
        provider = _provider(row)
        context = int(row.get("context_length") or 0)
        maximum = int(row.get("max_completion_tokens") or 0)
        pricing = row.get("pricing")
        pricing = pricing if isinstance(pricing, Mapping) else {}
        prompt_price = _ppm(pricing.get("prompt"))
        completion_price = _ppm(pricing.get("completion"))
        if (
            not provider
            or context < required_context
            or maximum < MIN_COMPLETION_TOKENS
            or prompt_price < 0
            or completion_price < 0
        ):
            continue
        expected_output = min(completion_tokens, maximum)
        estimated_cost = (
            prompt_tokens * prompt_price
            + expected_output * completion_price
        ) / 1_000_000
        supported = sorted(
            {
                str(value)
                for value in row.get("supported_parameters", [])
                if str(value)
            }
        )
        eligible.append(
            {
                "model": model_id,
                "company": _company(model_id),
                "official_intelligence_rank": int(intelligence_rank),
                "provider": provider,
                "provider_endpoint": f"{model_id}@{provider}",
                "context_length": context,
                "max_completion_tokens": maximum,
                "prompt_price_per_million": round(prompt_price, 8),
                "completion_price_per_million": round(completion_price, 8),
                "supported_parameters": supported,
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "local_token_ceiling_parameter_required": False,
                "native_completion_capacity_checked": True,
                "synthetic_fixture_only": False,
                "estimated_call_cost_usd": round(estimated_cost, 10),
            }
        )
    if not eligible:
        raise ExpertModelSelectionError(
            f"no exact compatible provider endpoint for {model_id}"
        )
    eligible.sort(
        key=lambda row: (
            float(row["estimated_call_cost_usd"]),
            float(row["prompt_price_per_million"])
            + float(row["completion_price_per_million"]),
            str(row["provider"]),
        )
    )
    return eligible[0]


def _distinct_candidates(
    ranked: Sequence[Mapping[str, Any]],
    required_count: int,
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    companies: set[str] = set()
    for row in ranked:
        model_id = str(row.get("model_id") or "")
        company = _company(model_id)
        if (
            not model_id
            or not company
            or company in EXCLUDED_EXPERT_COMPANIES
            or company in companies
        ):
            continue
        selected.append(row)
        companies.add(company)
        if len(selected) == required_count:
            break
    if len(selected) < required_count:
        raise ExpertModelSelectionError(
            "not enough distinct paid flagship companies for experts and recovery"
        )
    return selected


def _roles(expert_count: int) -> list[dict[str, Any]]:
    independent = expert_count - 2
    lenses = (
        ("evidence", "证据、事实、数据质量、关键假设与不确定性"),
        ("options", "备选方案、机制、因果链与反事实"),
        ("risk", "风险、失败模式、约束、边界与实施条件"),
        ("stakeholders", "利益相关方、激励、二阶效应与现实扰动"),
    )
    result: list[dict[str, Any]] = []
    for index in range(independent):
        lens_id, lens = lenses[index % len(lenses)]
        result.append(
            {
                "kind": "independent",
                "lens_id": lens_id,
                "role": f"独立分析专家：重点检查{lens}",
                "functions": [
                    "independent_analysis",
                    "evidence_assessment",
                    "assumption_testing",
                ],
            }
        )
    result.extend(
        [
            {
                "kind": "review",
                "lens_id": "review",
                "role": "交叉审查专家：比较前序分析，找出冲突、遗漏、薄弱证据和失败模式",
                "functions": [
                    "cross_review",
                    "adversarial_testing",
                    "conflict_resolution",
                ],
            },
            {
                "kind": "synthesis",
                "lens_id": "synthesis",
                "role": "最终综合专家：依据原始任务和全部前序结果形成唯一完整交付",
                "functions": [
                    "final_synthesis",
                    "decision_integration",
                    "output_contract_completion",
                ],
            },
        ]
    )
    return result


def _work_items(roles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    independent_ids = [
        f"work-independent-{index + 1}"
        for index, role in enumerate(roles)
        if role.get("kind") == "independent"
    ]
    result: list[dict[str, Any]] = []
    independent_cursor = 0
    for role in roles:
        kind = str(role.get("kind") or "")
        if kind == "independent":
            work_id = independent_ids[independent_cursor]
            independent_cursor += 1
            dependencies: list[str] = []
            outputs = ["核心判断", "关键证据与依据", "不确定性与反例", "可执行建议"]
        elif kind == "review":
            work_id = "work-cross-review"
            dependencies = list(independent_ids)
            outputs = ["一致结论", "主要冲突", "证据薄弱点", "必须修正事项"]
        else:
            work_id = "work-final-synthesis"
            dependencies = [*independent_ids, "work-cross-review"]
            outputs = ["直接结论", "推理链", "关键证据", "风险与不确定性", "行动方案", "否决条件"]
        result.append(
            {
                "work_id": work_id,
                "objective": str(role["role"]),
                "dependencies": dependencies,
                "required_outputs": outputs,
            }
        )
    return result


def _assign_endpoints(
    selected: Sequence[dict[str, Any]],
    roles: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_quality = sorted(
        selected,
        key=lambda row: (
            int(row["official_intelligence_rank"]),
            float(row["estimated_call_cost_usd"]),
            str(row["model"]),
        ),
    )
    synthesis = by_quality[0]
    review = by_quality[1]
    remaining = [
        row for row in selected if row is not synthesis and row is not review
    ]
    remaining.sort(
        key=lambda row: (
            float(row["estimated_call_cost_usd"]),
            str(row["model"]),
        )
    )
    assigned: list[dict[str, Any]] = []
    cursor = 0
    for role in roles:
        kind = str(role.get("kind") or "")
        if kind == "synthesis":
            assigned.append(synthesis)
        elif kind == "review":
            assigned.append(review)
        else:
            assigned.append(remaining[cursor])
            cursor += 1
    return assigned


def _proposal(
    roles: Sequence[Mapping[str, Any]],
    assigned: Sequence[Mapping[str, Any]],
    recoveries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    work_items = _work_items(roles)
    node_ids: list[str] = []
    nodes: list[dict[str, Any]] = []
    for index, (role, endpoint, work) in enumerate(
        zip(roles, assigned, work_items, strict=True), 1
    ):
        kind = str(role["kind"])
        node_id = (
            "expert-final-synthesis"
            if kind == "synthesis"
            else "expert-cross-review"
            if kind == "review"
            else f"expert-independent-{index}"
        )
        node_ids.append(node_id)
        desired = (
            SYNTHESIS_COMPLETION_TOKENS
            if kind == "synthesis"
            else DEFAULT_COMPLETION_TOKENS
        )
        nodes.append(
            {
                "node_id": node_id,
                "model": endpoint["model"],
                "provider": endpoint["provider"],
                "work_ids": [work["work_id"]],
                "role": role["role"],
                "functions": list(role["functions"]),
                "reasoning_effort": "high" if kind == "synthesis" else "medium",
                "max_output_tokens": max(
                    MIN_COMPLETION_TOKENS,
                    min(desired, int(endpoint["max_completion_tokens"])),
                ),
                "recovery": [],
            }
        )
    priority = [
        node_ids[index]
        for kind in ("synthesis", "review", "independent")
        for index, role in enumerate(roles)
        if role.get("kind") == kind
    ]
    nodes_by_id = {str(row["node_id"]): row for row in nodes}
    for index, endpoint in enumerate(recoveries):
        target = priority[index % len(priority)]
        nodes_by_id[target]["recovery"].append(
            {"model": endpoint["model"], "provider": endpoint["provider"]}
        )

    independent_nodes = [
        node_ids[index]
        for index, role in enumerate(roles)
        if role.get("kind") == "independent"
    ]
    review_node = next(
        node_ids[index]
        for index, role in enumerate(roles)
        if role.get("kind") == "review"
    )
    synthesis_node = next(
        node_ids[index]
        for index, role in enumerate(roles)
        if role.get("kind") == "synthesis"
    )
    edges: list[dict[str, str]] = []
    for node_id in independent_nodes:
        edges.append(
            {
                "source": node_id,
                "target": review_node,
                "relation_type": "analysis-to-review",
            }
        )
        edges.append(
            {
                "source": node_id,
                "target": synthesis_node,
                "relation_type": "analysis-to-synthesis",
            }
        )
    edges.append(
        {
            "source": review_node,
            "target": synthesis_node,
            "relation_type": "review-to-synthesis",
        }
    )
    return {
        "schema_version": "governance-owned-expert-proposal-v1",
        "work_items": work_items,
        "nodes": nodes,
        "edges": edges,
        "final_nodes": [synthesis_node],
    }


def build_selection_plan(
    ticket: Mapping[str, Any],
    selector_receipt: Mapping[str, Any],
    *,
    token: str = "",
    source_commit: str = "",
) -> dict[str, Any]:
    task_text = _task_text(ticket)
    total, recovery, expert_count = _budget(ticket)
    envelope = _task_envelope(task_text)
    ranking = rank_flagships_by_task_cost(
        selector_receipt,
        expected_prompt_tokens=max(10_000, len(task_text) + 8_192),
        expected_completion_tokens=DEFAULT_COMPLETION_TOKENS,
    )
    rows = ranking.get("ranked_paid_flagship_candidates")
    if not isinstance(rows, list):
        raise ExpertModelSelectionError("task-cost ranking is missing")
    candidates = _distinct_candidates(rows, expert_count + recovery)

    intelligence_order = sorted(
        candidates,
        key=lambda row: (
            -float(row.get("intelligence_index") or 0.0),
            -float(row.get("balanced_score") or 0.0),
            str(row.get("model_id") or ""),
        ),
    )
    intelligence_rank = {
        str(row["model_id"]): index
        for index, row in enumerate(intelligence_order, 1)
    }
    endpoints = [
        _exact_endpoint(
            row,
            token=token,
            required_context=int(envelope["required_context_tokens"]),
            prompt_tokens=max(10_000, len(task_text) + 8_192),
            completion_tokens=DEFAULT_COMPLETION_TOKENS,
            intelligence_rank=intelligence_rank[str(row["model_id"])],
        )
        for row in candidates
    ]
    selected_endpoints = endpoints[:expert_count]
    recovery_endpoints = endpoints[expert_count:]
    roles = _roles(expert_count)
    assigned = _assign_endpoints(selected_endpoints, roles)
    proposal = _proposal(roles, assigned, recovery_endpoints)
    catalog = {
        "schema_version": "governance-expert-catalog-view-v1",
        "selection_authority": "decision-system-governance",
        "official_order_only": False,
        "local_score_computed": False,
        "optimizer_used": False,
        "governance_companies_excluded": sorted(EXCLUDED_EXPERT_COMPANIES),
        "required_context_tokens": envelope["required_context_tokens"],
        "minimum_completion_tokens": MIN_COMPLETION_TOKENS,
        "minimum_native_completion_capacity_tokens": MIN_COMPLETION_TOKENS,
        "local_token_ceiling_parameter_required": False,
        "native_completion_capacity_checked": True,
        "endpoints": endpoints,
        "rejected": [],
    }
    selection = {
        "schema_version": "governance-expert-model-selection-v1",
        "status": "PASS",
        "selection_authority": "decision-system-governance",
        "source_repository": "a15280020511/decision-system-governance",
        "source_commit": source_commit,
        "task_text": task_text,
        "task_sha256": envelope["task_sha256"],
        "approved_total_calls": total,
        "approved_recovery_calls": recovery,
        "selected_expert_count": expert_count,
        "selection_rule": (
            "paid general-purpose flagship candidates -> expected task cost "
            "ascending -> distinct model companies -> exact provider endpoint "
            "resolution -> quality-aware role assignment"
        ),
        "task_envelope": envelope,
        "catalog": catalog,
        "catalog_sha256": _sha256(catalog),
        "proposal": proposal,
        "proposal_sha256": _sha256(proposal),
        "selected_models": [
            {
                "node_id": node["node_id"],
                "model": node["model"],
                "provider": node["provider"],
            }
            for node in proposal["nodes"]
        ],
        "recovery_models": [
            {"model": row["model"], "provider": row["provider"]}
            for row in recovery_endpoints
        ],
        "model_calls": 0,
        "cross_task_history_used": False,
        "expert_center_selection_allowed": False,
        "expert_center_catalog_fetch_allowed": False,
        "local_fallback_allowed": False,
    }
    selection["plan_sha256"] = _sha256(selection)
    return selection


def enrich_ticket(
    ticket_path: Path,
    *,
    token: str = "",
    source_commit: str = "",
    output_plan: Path | None = None,
) -> dict[str, Any]:
    ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
    if not isinstance(ticket, dict):
        raise ExpertModelSelectionError("child ticket must be a JSON object")
    if ticket.get("route") != "expert-team":
        raise ExpertModelSelectionError(
            "governance expert selection only accepts route=expert-team"
        )
    if token:
        selector_receipt = select_flagships(token)
    else:
        model_query = urllib.parse.urlencode(
            {"sort": "pricing-low-to-high", "output_modalities": "text"}
        )
        benchmark_query = urllib.parse.urlencode(
            {"source": "artificial-analysis"}
        )
        model_payload = _request_json(f"{MODELS_API}?{model_query}", "")
        model_rows = model_payload.get("data")
        if not isinstance(model_rows, list):
            raise ExpertModelSelectionError(
                "OpenRouter public model catalog is unavailable"
            )
        benchmark_payload = _request_json(
            f"{BENCHMARKS_API}?{benchmark_query}", ""
        )
        selector_receipt = select_from_catalog(
            [row for row in model_rows if isinstance(row, Mapping)],
            benchmark_payload,
        )
    plan = build_selection_plan(
        ticket,
        selector_receipt,
        token=token,
        source_commit=source_commit,
    )
    ticket["governance_selection"] = plan
    ticket_path.write_text(
        json.dumps(ticket, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if output_plan is not None:
        output_plan.parent.mkdir(parents=True, exist_ok=True)
        output_plan.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--output-plan")
    parser.add_argument("--source-commit", default=os.getenv("GITHUB_SHA", ""))
    args = parser.parse_args()
    plan = enrich_ticket(
        Path(args.ticket),
        token=os.getenv("OPENROUTER_API_KEY", ""),
        source_commit=args.source_commit,
        output_plan=Path(args.output_plan) if args.output_plan else None,
    )
    print(
        json.dumps(
            {
                "status": plan["status"],
                "plan_sha256": plan["plan_sha256"],
                "selected_expert_count": plan["selected_expert_count"],
                "selected_models": plan["selected_models"],
                "recovery_models": plan["recovery_models"],
                "selection_authority": plan["selection_authority"],
                "model_calls": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
