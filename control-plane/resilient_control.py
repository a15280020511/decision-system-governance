#!/usr/bin/env python3
"""Control-plane entrypoint with dynamic expert candidate attachment.

Transport/authentication remain intact. Governance-side Top20/Top50, budget,
company, flagship, Provider/ZDR and fixed-team selection gates are removed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
COPILOT_ROOT = ROOT.parent / "governance-copilot"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_resilient_control_runtime", ROOT / "control_plane.py")
HTTP = _load("governance_resilient_http_runtime", ROOT / "resilient_http.py")
RELIABILITY = _load("governance_gpts_reliability_runtime", ROOT / "gpts_reliability.py")
INGRESS = _load(
    "governance_gpts_ingress_normalization_runtime",
    ROOT / "gpts_ingress_normalization.py",
)
CONTROL._github_request = HTTP.github_request
RELIABILITY.patch(CONTROL)
INGRESS.patch(CONTROL)

if str(COPILOT_ROOT) not in sys.path:
    sys.path.insert(0, str(COPILOT_ROOT))
EXPERT_SELECTOR = _load(
    "governance_dynamic_expert_candidates_runtime",
    COPILOT_ROOT / "select_expert_team_plan.py",
)
DYNAMIC_POOL = _load(
    "governance_dynamic_reasoning_pool_runtime",
    COPILOT_ROOT / "top50_reasoning_pool_extension.py",
)
DYNAMIC_POOL.patch_selector(EXPERT_SELECTOR)


def _write_status(root: Path, status: dict[str, Any]) -> None:
    CONTROL._write_json(root / "prepare-status.json", status)
    for key in (
        "accepted",
        "reason",
        "model_plan_sha256",
        "selected_expert_count",
        "selected_recovery_count",
        "expert_candidate_pool_size",
    ):
        if key in status:
            value = status[key]
            CONTROL._write_output(
                key,
                str(value).lower() if isinstance(value, bool) else value,
            )


def _adapt_expert_execution_contract(ticket: dict[str, Any]) -> dict[str, Any]:
    """Normalize only fields needed for routing; do not impose business gates."""
    adapted = dict(ticket)
    task_id = str(adapted.get("task_id") or "").strip()
    if not task_id:
        task_id = "governance-dynamic-expert-task"
        adapted["task_id"] = task_id
    adapted["route"] = "expert-team"
    pipeline = adapted.get("pipeline")
    if not isinstance(pipeline, dict):
        adapted["pipeline"] = {
            "pipeline_id": task_id,
            "stage_id": "expert",
            "sequence_reason": "Governance-routed dynamic expert assessment",
        }
    adapted["private_output"] = False
    return adapted


def _attach_expert_model_plan(arguments: Any) -> int:
    root = Path(arguments.output_dir)
    status_path = root / "prepare-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("accepted") is not True or status.get("route") != "expert":
        return 0

    ticket_path = root / "child-ticket.json"
    try:
        ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        if not isinstance(ticket, dict):
            raise EXPERT_SELECTOR.ExpertPlanError("child expert ticket root must be an object")
        ticket = _adapt_expert_execution_contract(ticket)
        enriched, plan = EXPERT_SELECTOR.enrich_ticket(
            ticket,
            os.getenv("OPENROUTER_API_KEY", ""),
        )
        CONTROL._write_json(ticket_path, enriched)
        CONTROL._write_json(root / "expert-model-plan.json", plan)
        status.update(
            {
                "model_selection_authority": "expert-assessment-center-dynamic-ortools",
                "candidate_pool_authority": "decision-system-governance",
                "model_assignment_authority": "expert-assessment-center-dynamic-ortools",
                "model_plan_sha256": plan["plan_sha256"],
                "selected_expert_count": 0,
                "selected_recovery_count": 0,
                "expert_candidate_pool_size": int(plan.get("expert_candidate_pool_size") or 0),
                "expert_candidate_pool_sha256": str(plan.get("expert_candidate_pool_sha256") or ""),
                "expert_center_model_selection_allowed": True,
                "expert_center_selection_scope": "all-live-governance-candidates-task-dynamic",
                "expert_child_contract": "dynamic-execution-ticket-v5",
                "expert_child_route": "expert-team",
                "fixed_team_size_required": False,
                "fixed_four_plus_four_required": False,
                "top20_only_required": False,
                "top50_only_required": False,
                "company_uniqueness_required": False,
                "flagship_filter_required": False,
                "price_filter_required": False,
                "provider_endpoint_qualification_required": False,
                "zdr_endpoint_qualification_required": False,
                "free_first_required": False,
                "canary_required_before_execution": False,
                "provider_routing_mode": "unrestricted-openrouter",
            }
        )
        _write_status(root, status)
        return 0
    except Exception as exc:  # noqa: BLE001
        # A missing live candidate inventory is an execution dependency failure,
        # not a policy rejection. Preserve that distinction in the receipt.
        status["accepted"] = False
        status["reason"] = f"dynamic candidate inventory unavailable: {exc}"
        status["rejection_kind"] = "functional-dependency-unavailable"
        status["business_gate_rejection"] = False
        status["candidate_pool_authority"] = "decision-system-governance"
        status["expert_center_model_selection_allowed"] = True
        _write_status(root, status)
        return 2


def main() -> int:
    arguments = CONTROL.parser().parse_args()
    result = int(arguments.func(arguments))
    if result == 0 and getattr(arguments, "command", "") == "prepare":
        plan_result = _attach_expert_model_plan(arguments)
        if plan_result:
            return plan_result
    return result


if __name__ == "__main__":
    raise SystemExit(main())
