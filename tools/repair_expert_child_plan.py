#!/usr/bin/env python3
"""Refresh the governance candidate inventory for one existing expert child Issue.

Repair is limited to replacing governance_model_plan with a fresh, unrestricted
OpenRouter model catalog snapshot. It does not impose TopN, reasoning-only,
company, flagship, price, budget, Provider/ZDR, fixed-team or recovery gates.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = ROOT / "governance-copilot" / "select_expert_team_plan.py"
DYNAMIC_POOL_PATH = ROOT / "governance-copilot" / "top50_reasoning_pool_extension.py"
RETRY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
EXPECTED_ROUTE = "expert-team"


class ExpertChildRepairError(RuntimeError):
    """Raised when an existing child ticket cannot be represented safely."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExpertChildRepairError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = _load_module("governance_dynamic_repair_selector", SELECTOR_PATH)
DYNAMIC_POOL = _load_module("governance_dynamic_repair_pool", DYNAMIC_POOL_PATH)
DYNAMIC_POOL.patch_selector(SELECTOR)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _load_mapping(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpertChildRepairError(f"cannot read {field}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ExpertChildRepairError(f"{field} root must be an object")
    return dict(value)


def prepare_base_ticket(source: Mapping[str, Any], expected_task_id: str) -> dict[str, Any]:
    task_id = str(source.get("task_id") or "").strip()
    if not expected_task_id or task_id != expected_task_id:
        raise ExpertChildRepairError(
            f"task_id mismatch: expected {expected_task_id!r}, found {task_id!r}"
        )
    base = dict(source)
    base.setdefault("route", EXPECTED_ROUTE)
    if not isinstance(base.get("task"), Mapping):
        # Legacy tickets may encode the task at the root; the selector supports
        # that shape, so do not reject it merely for missing a nested task.
        base.pop("task", None)
    base.pop("governance_model_plan", None)
    return base


def _plan_digest(plan: Mapping[str, Any]) -> str:
    material = dict(plan)
    material.pop("plan_sha256", None)
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def verify_repair(
    source: Mapping[str, Any],
    repaired: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    source_without_plan = dict(source)
    source_without_plan.pop("governance_model_plan", None)
    repaired_without_plan = dict(repaired)
    repaired_plan = repaired_without_plan.pop("governance_model_plan", None)

    # The repair may only normalize a missing route; every other user/task field
    # remains untouched.
    expected = dict(source_without_plan)
    expected.setdefault("route", EXPECTED_ROUTE)
    if repaired_without_plan != expected:
        raise ExpertChildRepairError(
            "repair changed child ticket content outside governance_model_plan"
        )
    if repaired_plan != plan:
        raise ExpertChildRepairError("repaired ticket and plan output disagree")
    if plan.get("plan_sha256") != _plan_digest(plan):
        raise ExpertChildRepairError("regenerated plan digest mismatch")
    if plan.get("task_sha256") != SELECTOR.task_sha256(expected):
        raise ExpertChildRepairError("regenerated plan task hash mismatch")

    candidates = plan.get("expert_candidate_pool")
    if not isinstance(candidates, list) or not candidates:
        raise ExpertChildRepairError("regenerated live candidate inventory is empty")
    if plan.get("candidate_pool_authority") != "decision-system-governance":
        raise ExpertChildRepairError("regenerated candidate pool authority is invalid")
    if plan.get("model_assignment_authority") != "expert-assessment-center-dynamic-ortools":
        raise ExpertChildRepairError("regenerated model assignment authority is invalid")
    if plan.get("provider_routing_mode") != "unrestricted-openrouter":
        raise ExpertChildRepairError("regenerated Provider routing is restricted")
    if plan.get("provider_restrictions_applied") is not False:
        raise ExpertChildRepairError("regenerated plan applied Provider restrictions")
    for gate in (
        "fixed_team_size_required",
        "fixed_four_plus_four_required",
        "company_uniqueness_required",
        "flagship_filter_required",
        "price_filter_required",
        "intelligence_rank_required",
        "provider_endpoint_qualification_required",
        "zdr_endpoint_qualification_required",
        "free_first_required",
        "canary_required_before_execution",
    ):
        if plan.get(gate) is not False:
            raise ExpertChildRepairError(f"regenerated plan unexpectedly enables {gate}")


def regenerate(
    source: Mapping[str, Any], expected_task_id: str, token: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not str(token or "").strip():
        raise ExpertChildRepairError("OPENROUTER_API_KEY is required to read the live catalog")
    base = prepare_base_ticket(source, expected_task_id)
    repaired, plan = SELECTOR.enrich_ticket(base, token)
    verify_repair(source, repaired, plan)
    return repaired, plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-body", required=True)
    parser.add_argument("--expected-task-id", required=True)
    parser.add_argument("--retry-id", required=True)
    parser.add_argument("--output-ticket", required=True)
    parser.add_argument("--output-plan", required=True)
    args = parser.parse_args()

    if not RETRY_ID_RE.fullmatch(args.retry_id):
        raise ExpertChildRepairError("retry_id has an invalid format")
    source = _load_mapping(Path(args.source_body), "source issue body")
    repaired, plan = regenerate(
        source,
        args.expected_task_id,
        os.getenv("OPENROUTER_API_KEY", ""),
    )
    Path(args.output_ticket).write_text(
        json.dumps(repaired, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
                "task_id": args.expected_task_id,
                "retry_id": args.retry_id,
                "plan_sha256": plan["plan_sha256"],
                "candidate_count": int(plan.get("expert_candidate_pool_size") or 0),
                "candidate_pool_sha256": str(plan.get("expert_candidate_pool_sha256") or ""),
                "model_assignment_authority": plan["model_assignment_authority"],
                "provider_routing_mode": "unrestricted-openrouter",
                "governance_selected_model_count": 0,
                "governance_recovery_model_count": 0,
                "qualification_gates_applied": False,
                "model_calls": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
