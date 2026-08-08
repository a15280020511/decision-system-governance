#!/usr/bin/env python3
"""Build a governance candidate plan without selecting a fixed expert team.

Governance owns live candidate discovery and ticket integrity only. It does not
apply flagship, price, intelligence-rank, company, Provider, ZDR, Top-N, fixed
team-size, recovery, free-first, Canary, or optimizer-status admission gates.
Expert composition is delegated to the Expert Center and recomputed from the
current task.

The single hard model-execution boundary declared here is ``no-tools``. Every
model supplied to the Expert Center must execute without tools/functions/search,
browser, MCP, code execution, file search, connectors, or equivalent external
action capabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

MODELS_API = "https://openrouter.ai/api/v1/models"
BENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"
ENDPOINTS_API = "https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints"
SCHEMA_VERSION = "governance-expert-dynamic-candidate-plan-v1"
SELECTOR_SCHEMA_VERSION = "governance-openrouter-unrestricted-candidate-inventory-v1"
CANDIDATE_POOL_AUTHORITY = "decision-system-governance"
MODEL_ASSIGNMENT_AUTHORITY = "expert-assessment-center-dynamic-ortools"
# Compatibility export: ``selection_authority`` now names the component that
# actually selects models, not the component that supplies the candidate pool.
SELECTION_AUTHORITY = MODEL_ASSIGNMENT_AUTHORITY
DEFAULT_EXPERT_COUNT = 0
MIN_EXPERT_COUNT = 1
MAX_EXPERT_COUNT = 0
OFFICIAL_INTELLIGENCE_RANK_LIMIT = 0
MINIMUM_COMPLETION_TOKENS = 0
FIXED_PROTOCOL_RESERVE = 0
REASONING_PARAMETER = "reasoning"
GOVERNANCE_COMPANIES = frozenset()
FORBIDDEN_MODEL_TERMS: tuple[str, ...] = ()


class ExpertPlanError(RuntimeError):
    """Raised only when required live catalog data cannot be represented."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def task_sha256(ticket: Mapping[str, Any]) -> str:
    task = ticket.get("task")
    material = task if isinstance(task, Mapping) else ticket
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def _required_context_tokens(ticket: Mapping[str, Any]) -> int:
    task = ticket.get("task")
    material = task if isinstance(task, Mapping) else ticket
    # Advisory estimate only; never an eligibility threshold.
    return max(0, len(_canonical_json(material).decode("utf-8")))


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "decision-system-governance-dynamic-candidate-selector/1.0",
        "X-Title": "Decision System Governance Dynamic Expert Candidates",
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
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stable_model_id(model_id: str) -> bool:
    return bool(str(model_id or "").strip())


def _required_plan_fields(ticket: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "selector_schema_version": SELECTOR_SCHEMA_VERSION,
        "selection_authority": MODEL_ASSIGNMENT_AUTHORITY,
        "candidate_pool_authority": CANDIDATE_POOL_AUTHORITY,
        "model_assignment_authority": MODEL_ASSIGNMENT_AUTHORITY,
        "task_sha256": task_sha256(ticket),
        "required_context_tokens": _required_context_tokens(ticket),
        "selected_models": [],
        "recovery_models": [],
        "expert_count": 0,
        "recovery_count": 0,
        "model_calls": 0,
        "governance_model_calls": 0,
        "selection_performed_by_governance": False,
        "candidate_pool_selection_performed_by_governance": True,
        "expert_center_pool_selection_allowed": True,
        "expert_center_reranking_allowed": True,
        "model_substitution_allowed": True,
        "task_adaptive_assignment_required": True,
        "assignment_recomputed_from_current_task": True,
        "company_heterogeneity_optimization_authority": (
            "expert-assessment-center-current-task"
        ),
        "company_heterogeneity_hard_gate_required": False,
        "fixed_company_count_required": False,
        "fixed_team_size_required": False,
        "fixed_four_plus_four_required": False,
        "fixed_role_topology_required": False,
        "flagship_filter_required": False,
        "price_filter_required": False,
        "intelligence_rank_required": False,
        "company_uniqueness_required": False,
        "provider_endpoint_qualification_required": False,
        "zdr_endpoint_qualification_required": False,
        "endpoint_qualification_performed_by_governance": False,
        "provider_routing_mode": "unrestricted-openrouter",
        "provider_restrictions_applied": False,
        "free_first_required": False,
        "canary_required_before_execution": False,
        "cross_task_history_allowed": False,
        "tool_use_forbidden": True,
        "tools_allowed": False,
        "only_hard_model_boundary": "no-tools",
    }


def build_plan(ticket: Mapping[str, Any], token: str = "") -> dict[str, Any]:
    del token
    plan = _required_plan_fields(ticket)
    plan["plan_sha256"] = hashlib.sha256(_canonical_json(plan)).hexdigest()
    return plan


def enrich_ticket(
    ticket: Mapping[str, Any], token: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = build_plan(ticket, token)
    signed = dict(ticket)
    signed["governance_model_plan"] = plan
    return signed, plan


__all__ = [
    "BENCHMARKS_API",
    "CANDIDATE_POOL_AUTHORITY",
    "ENDPOINTS_API",
    "ExpertPlanError",
    "MODELS_API",
    "MODEL_ASSIGNMENT_AUTHORITY",
    "SCHEMA_VERSION",
    "SELECTION_AUTHORITY",
    "SELECTOR_SCHEMA_VERSION",
    "_fetch_json",
    "_required_context_tokens",
    "_stable_model_id",
    "build_plan",
    "enrich_ticket",
    "task_sha256",
]
