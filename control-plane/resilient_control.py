#!/usr/bin/env python3
"""Control-plane entrypoint with resilient transport and expert-plan ownership."""
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
    "governance_expert_model_plan_runtime",
    COPILOT_ROOT / "select_expert_team_plan.py",
)


def _write_status(root: Path, status: dict[str, Any]) -> None:
    CONTROL._write_json(root / "prepare-status.json", status)
    for key in (
        "accepted",
        "reason",
        "model_plan_sha256",
        "selected_expert_count",
        "selected_recovery_count",
    ):
        if key in status:
            value = status[key]
            CONTROL._write_output(
                key,
                str(value).lower() if isinstance(value, bool) else value,
            )


def _adapt_expert_execution_contract(ticket: dict[str, Any]) -> dict[str, Any]:
    """Translate the governance expert ticket into the center's public schema."""
    adapted = dict(ticket)
    task_id = str(adapted.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("expert child ticket task_id is required")

    adapted["route"] = "expert-team"

    pipeline = adapted.get("pipeline")
    if isinstance(pipeline, str):
        adapted["pipeline"] = {
            "pipeline_id": task_id,
            "stage_id": "expert",
            "sequence_reason": "Governance-routed expert assessment",
        }
    elif pipeline is None:
        adapted["pipeline"] = {
            "pipeline_id": task_id,
            "stage_id": "expert",
            "sequence_reason": "Governance-routed expert assessment",
        }
    elif not isinstance(pipeline, dict):
        raise ValueError("expert child ticket pipeline must be a string or object")

    budget = adapted.get("approved_budget")
    if not isinstance(budget, dict):
        raise ValueError("expert child ticket approved_budget must be an object")
    governed_budget = dict(budget)
    governed_budget.setdefault("cost_policy", "prompt_led_soft_governance")
    adapted["approved_budget"] = governed_budget

    if adapted.get("private_output") not in (None, False):
        raise ValueError("expert child ticket private_output must be false")
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
            raise EXPERT_SELECTOR.ExpertPlanError(
                "child expert ticket root must be an object"
            )
        ticket = _adapt_expert_execution_contract(ticket)
        enriched, plan = EXPERT_SELECTOR.enrich_ticket(
            ticket,
            os.getenv("OPENROUTER_API_KEY", ""),
        )
        CONTROL._write_json(ticket_path, enriched)
        CONTROL._write_json(root / "expert-model-plan.json", plan)
        status.update(
            {
                "model_selection_authority": "decision-system-governance",
                "model_plan_sha256": plan["plan_sha256"],
                "selected_expert_count": plan["expert_count"],
                "selected_recovery_count": plan["recovery_count"],
                "expert_center_model_selection_allowed": False,
                "expert_child_contract": "execution-ticket-v5",
                "expert_child_route": "expert-team",
                "expert_child_cost_policy": "prompt_led_soft_governance",
            }
        )
        _write_status(root, status)
        return 0
    except Exception as exc:  # noqa: BLE001 - fail closed at the boundary
        status["accepted"] = False
        status["reason"] = f"governance expert-model selection failed: {exc}"
        status["model_selection_authority"] = "decision-system-governance"
        status["expert_center_model_selection_allowed"] = False
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
