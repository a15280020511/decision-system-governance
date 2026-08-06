#!/usr/bin/env python3
"""Create a governance-owned, price-ordered, executable expert model plan.

Selection remains deliberately simple: use OpenRouter's official intelligence
order as the eligibility ceiling, retain explicit paid flagship tiers, verify a
real exact provider endpoint for the current task, sort by combined token price,
choose active experts from different companies, and continue down the same price
order for distinct standby models.
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
ENDPOINTS_API = "https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints"
SCHEMA_VERSION = "governance-expert-model-plan-v1"
SELECTOR_SCHEMA_VERSION = "governance-openrouter-executable-flagship-price-v3"
SELECTION_AUTHORITY = "decision-system-governance"
DEFAULT_EXPERT_COUNT = 4
MIN_EXPERT_COUNT = 3
MAX_EXPERT_COUNT = 6
OFFICIAL_INTELLIGENCE_RANK_LIMIT = 150
MINIMUM_COMPLETION_TOKENS = 1_024
FIXED_PROTOCOL_RESERVE = 8_192
GOVERNANCE_COMPANIES = frozenset({"openai", "anthropic"})
FORBIDDEN_MODEL_TERMS = (
    "openrouter/",
    ":online",
    ":batch",
    ":free",
    "preview",
)

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


def _required_context_tokens(ticket: Mapping[str, Any]) -> int:
    task = ticket.get("task")
    if not isinstance(task, Mapping):
        raise ExpertPlanError("expert ticket has no task object")
    task_characters = len(_canonical_json(task).decode("utf-8"))
    return max(FIXED_PROTOCOL_RESERVE, task_characters + FIXED_PROTOCOL_RESERVE)


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "decision-system-governance-expert-selector/3.0",
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


def _positive_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _price_per_million(pricing: Mapping[str, Any], key: str) -> float | None:
    value = _number(pricing.get(key))
    if value is None or value < 0:
        return None
    return value * 1_000_000 if value < 0.1 else value


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
        and "text" in outputs
    )


def _not_expired(row: Mapping[str, Any]) -> bool:
    raw = row.get("expiration_date")
    if raw in {None, ""}:
        return True
    try:
        return date.fromisoformat(str(raw)[:10]) >= date.today()
    except ValueError:
        return False


def _stable_model_id(model_id: str) -> bool:
    folded = str(model_id or "").strip().casefold()
    return bool(
        folded
        and "/" in folded
        and not any(term in folded for term in FORBIDDEN_MODEL_TERMS)
    )


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
    for official_rank, row in enumerate(rows, 1):
        if official_rank > OFFICIAL_INTELLIGENCE_RANK_LIMIT:
            break
        if not isinstance(row, Mapping):
            continue
        model_id = str(row.get("id") or "").strip()
        if not _stable_model_id(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        company = model_id.split("/", 1)[0].casefold()
        if not _is_general_text(row) or not _not_expired(row):
            continue
        if not _is_general_flagship(_identity(row, model_id)):
            continue

        pricing = _mapping(row.get("pricing"))
        prompt = _price_per_million(pricing, "prompt")
        completion = _price_per_million(pricing, "completion")
        if prompt is None or completion is None or prompt + completion <= 0:
            continue

        combined = prompt + completion
        candidates.append(
            {
                "model_id": model_id,
                "company": company,
                "official_intelligence_rank": official_rank,
                "context_length": _positive_int(row.get("context_length")),
                "max_completion_tokens": _positive_int(
                    row.get("max_completion_tokens")
                ),
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
            int(row["official_intelligence_rank"]),
            str(row["model_id"]),
        )
    )
    if not candidates:
        raise ExpertPlanError(
            "no paid general-purpose flagship model is available within the "
            "official intelligence top 150"
        )
    return candidates


def _endpoint_url(model_id: str) -> str:
    if not _stable_model_id(model_id):
        raise ExpertPlanError(f"unstable model id: {model_id}")
    author, slug = model_id.split("/", 1)
    return ENDPOINTS_API.format(
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
        return [row for row in payload["endpoints"] if isinstance(row, Mapping)]
    return []


def _provider_slug(endpoint: Mapping[str, Any]) -> str:
    for key in ("tag", "provider_slug", "provider", "name", "provider_name"):
        value = str(endpoint.get(key) or "").strip()
        if value:
            return value
    return ""


def _compatible_endpoint_inventory(
    candidate: Mapping[str, Any],
    payload: Mapping[str, Any],
    required_context_tokens: int,
) -> list[dict[str, Any]]:
    compatible: list[dict[str, Any]] = []
    aggregate_context = _positive_int(candidate.get("context_length"))
    aggregate_completion = _positive_int(candidate.get("max_completion_tokens"))
    for endpoint in _endpoint_rows(payload):
        provider = _provider_slug(endpoint)
        context = _positive_int(endpoint.get("context_length"), aggregate_context)
        maximum = _positive_int(
            endpoint.get("max_completion_tokens"), aggregate_completion
        )
        pricing = _mapping(endpoint.get("pricing"))
        prompt = _price_per_million(pricing, "prompt")
        completion = _price_per_million(pricing, "completion")
        if prompt is None:
            prompt = float(candidate["prompt_usd_per_million"])
        if completion is None:
            completion = float(candidate["completion_usd_per_million"])
        if (
            not provider
            or context < required_context_tokens
            or maximum < MINIMUM_COMPLETION_TOKENS
            or prompt < 0
            or completion < 0
            or endpoint.get("synthetic_fixture_only") is True
        ):
            continue
        compatible.append(
            {
                "provider": provider,
                "provider_endpoint": f"{candidate['model_id']}@{provider}",
                "context_length": context,
                "max_completion_tokens": maximum,
                "prompt_usd_per_million": prompt,
                "completion_usd_per_million": completion,
            }
        )
    compatible.sort(
        key=lambda row: (
            float(row["prompt_usd_per_million"])
            + float(row["completion_usd_per_million"]),
            str(row["provider"]),
        )
    )
    return compatible


def _qualify_candidate(
    candidate: Mapping[str, Any],
    token: str,
    required_context_tokens: int,
) -> dict[str, Any] | None:
    payload = _fetch_json(_endpoint_url(str(candidate["model_id"])), token)
    compatible = _compatible_endpoint_inventory(
        candidate,
        payload,
        required_context_tokens,
    )
    if not compatible:
        return None
    qualified = dict(candidate)
    qualified.update(
        {
            "exact_endpoint_qualified": True,
            "qualified_provider_count": len(compatible),
            "endpoint_inventory_sha256": hashlib.sha256(
                _canonical_json(compatible)
            ).hexdigest(),
            "required_context_tokens": required_context_tokens,
            "minimum_completion_tokens": MINIMUM_COMPLETION_TOKENS,
        }
    )
    return qualified


def _live_flagship_rows(token: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"sort": "intelligence-high-to-low", "output_modalities": "text"}
    )
    payload = _fetch_json(f"{MODELS_API}?{query}", token)
    return _catalog_candidates(payload)


def _live_executable_flagship_rows(
    ticket: Mapping[str, Any],
    token: str,
    required_company_count: int,
    required_model_count: int | None = None,
) -> list[dict[str, Any]]:
    required_context = _required_context_tokens(ticket)
    required_models = (
        required_company_count
        if required_model_count is None
        else required_model_count
    )
    if required_company_count < 1 or required_models < required_company_count:
        raise ExpertPlanError("invalid executable flagship selection target")

    candidates = _live_flagship_rows(token)
    qualified: list[dict[str, Any]] = []
    companies: set[str] = set()
    models: set[str] = set()
    for candidate in candidates:
        model_id = str(candidate.get("model_id") or "").strip()
        company = str(candidate.get("company") or "").strip()
        if not model_id or not company or model_id in models:
            continue
        row = _qualify_candidate(candidate, token, required_context)
        if row is None:
            continue
        qualified.append(row)
        models.add(model_id)
        companies.add(company)
        if (
            len(qualified) >= required_models
            and len(companies) >= required_company_count
        ):
            break
    if len(companies) < required_company_count:
        raise ExpertPlanError(
            "not enough distinct-company executable flagship models: "
            f"need {required_company_count}, found {len(companies)}"
        )
    if len(qualified) < required_models:
        raise ExpertPlanError(
            "not enough executable flagship models for primary and recovery slots: "
            f"need {required_models}, found {len(qualified)}"
        )
    return qualified


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
    if row.get("exact_endpoint_qualified") is not True:
        raise ExpertPlanError("ranked model has no executable endpoint qualification")
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
        if (
            not model
            or not company
            or company in GOVERNANCE_COMPANIES
            or model in models
            or company in companies
        ):
            continue
        _finite_cost(row)
        chosen.append(row)
        models.add(model)
        companies.add(company)
        if len(chosen) == count:
            return chosen
    raise ExpertPlanError(
        f"not enough distinct-company executable flagship models: need {count}, "
        f"found {len(chosen)}"
    )


def _distinct_model_rows(
    rows: Sequence[Mapping[str, Any]],
    count: int,
    excluded_models: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    excluded = set(excluded_models or ())
    chosen: list[Mapping[str, Any]] = []
    models = set(excluded)
    for row in rows:
        model = str(row.get("model_id") or "").strip()
        company = str(row.get("company") or "").strip()
        if not model or not company or model in models:
            continue
        _finite_cost(row)
        chosen.append(row)
        models.add(model)
        if len(chosen) == count:
            return chosen
    raise ExpertPlanError(
        f"not enough unique executable flagship recovery models: need {count}, "
        f"found {len(chosen)}"
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
        "official_intelligence_rank": int(row["official_intelligence_rank"]),
        "qualified_provider_count": int(row["qualified_provider_count"]),
        "endpoint_inventory_sha256": str(row["endpoint_inventory_sha256"]),
        "selection_evidence": (
            "explicit-product-tier-price-order+live-exact-endpoint-qualified"
        ),
    }


def _catalog_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    source = [
        {
            "model_id": row["model_id"],
            "company": row["company"],
            "official_intelligence_rank": row["official_intelligence_rank"],
            "prompt_usd_per_million": row["prompt_usd_per_million"],
            "completion_usd_per_million": row["completion_usd_per_million"],
            "request_usd": row["request_usd"],
            "price_rank_usd_per_million": row["price_rank_usd_per_million"],
            "qualified_provider_count": row["qualified_provider_count"],
            "endpoint_inventory_sha256": row["endpoint_inventory_sha256"],
            "required_context_tokens": row["required_context_tokens"],
            "minimum_completion_tokens": row["minimum_completion_tokens"],
        }
        for row in rows
    ]
    return hashlib.sha256(_canonical_json(source)).hexdigest()


def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
    _, recovery_count, expert_count = _budget(ticket)
    required_model_count = expert_count + recovery_count
    rows = _live_executable_flagship_rows(
        ticket,
        token,
        expert_count,
        required_model_count,
    )

    selected_rows = _distinct_company_rows(rows, expert_count)
    selected_model_ids = {str(row["model_id"]) for row in selected_rows}
    recovery_rows = (
        _distinct_model_rows(
            rows,
            recovery_count,
            excluded_models=selected_model_ids,
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
            "openrouter-official-intelligence-top-150 -> paid-general-purpose-"
            "flagships -> live-exact-endpoint-qualified -> combined-token-price-"
            "ascending -> primary-excludes-governance-vendors -> "
            "distinct-primary-companies -> unique-recovery-models"
        ),
        "price_rank_basis": "prompt_usd_per_million + completion_usd_per_million",
        "task_sha256": task_sha256(ticket),
        "required_context_tokens": _required_context_tokens(ticket),
        "minimum_native_completion_tokens": MINIMUM_COMPLETION_TOKENS,
        "expert_count": expert_count,
        "recovery_count": recovery_count,
        "selected_models": selected_models,
        "recovery_models": recovery_models,
        "endpoint_qualification_performed_by_governance": True,
        "governance_companies_excluded_from_primary": sorted(
            GOVERNANCE_COMPANIES
        ),
        "governance_companies_allowed_in_recovery": True,
        "provider_selection_authority": (
            "expert-runtime-cheapest-compatible-exact-endpoint-resolution-only"
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

    ticket_path = Path(args.ticket)
    value = json.loads(ticket_path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ExpertPlanError("ticket root must be an object")
    enriched, plan = enrich_ticket(value, os.getenv("OPENROUTER_API_KEY", ""))
    Path(args.output_ticket).write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.output_plan).write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
