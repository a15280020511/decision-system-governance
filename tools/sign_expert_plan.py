#!/usr/bin/env python3
"""Attach governance integrity metadata and a live dynamic expert candidate pool.

Signing no longer preselects models or enforces Top20/Top50, 4+4, company,
flagship, price, intelligence, Provider, ZDR, budget or recovery constraints.
The Expert Center composes the actual team from the current task.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SELECTOR_PATH = ROOT / "governance-copilot" / "select_expert_team_plan.py"
DYNAMIC_POOL_PATH = ROOT / "governance-copilot" / "top50_reasoning_pool_extension.py"


class ExpertPlanSigningError(RuntimeError):
    """Raised only when a ticket or live candidate inventory cannot be represented."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExpertPlanSigningError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = _load_module("governance_dynamic_selector", SELECTOR_PATH)
DYNAMIC_POOL = _load_module("governance_dynamic_pool", DYNAMIC_POOL_PATH)
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


def _load_issue_ticket(event_path: Path) -> dict[str, Any]:
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpertPlanSigningError(f"cannot read Issue event: {exc}") from exc
    issue = event.get("issue") if isinstance(event, Mapping) else None
    raw = str(issue.get("body") or "").strip() if isinstance(issue, Mapping) else ""
    try:
        ticket = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExpertPlanSigningError("Issue body must be one JSON object") from exc
    if not isinstance(ticket, Mapping):
        raise ExpertPlanSigningError("Issue body must be one JSON object")
    return dict(ticket)


def validate_unsigned_ticket(ticket: Mapping[str, Any]) -> None:
    if not isinstance(ticket, Mapping):
        raise ExpertPlanSigningError("ticket must be an object")
    task = ticket.get("task")
    if task is not None and not isinstance(task, Mapping):
        raise ExpertPlanSigningError("task must be an object when supplied")


def _plan_digest(plan: Mapping[str, Any]) -> str:
    material = dict(plan)
    material.pop("plan_sha256", None)
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def verify_signed_plan(
    unsigned: Mapping[str, Any],
    signed: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    signed_without_plan = dict(signed)
    signed_plan = signed_without_plan.pop("governance_model_plan", None)
    unsigned_without_plan = dict(unsigned)
    unsigned_without_plan.pop("governance_model_plan", None)
    if signed_without_plan != unsigned_without_plan:
        raise ExpertPlanSigningError("signing changed ticket content outside governance_model_plan")
    if signed_plan != plan:
        raise ExpertPlanSigningError("signed ticket and plan differ")
    if plan.get("plan_sha256") != _plan_digest(plan):
        raise ExpertPlanSigningError("plan digest mismatch")
    if plan.get("task_sha256") != SELECTOR.task_sha256(unsigned_without_plan):
        raise ExpertPlanSigningError("plan task hash mismatch")
    candidates = plan.get("expert_candidate_pool")
    if not isinstance(candidates, list) or not candidates:
        raise ExpertPlanSigningError("live candidate inventory is empty")
    if plan.get("candidate_pool_authority") != "decision-system-governance":
        raise ExpertPlanSigningError("candidate pool authority mismatch")
    if plan.get("provider_routing_mode") != "unrestricted-openrouter":
        raise ExpertPlanSigningError("Provider routing is not unrestricted")


def sign(ticket: Mapping[str, Any], token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_unsigned_ticket(ticket)
    if not str(token or "").strip():
        raise ExpertPlanSigningError("OPENROUTER_API_KEY is required to read the live catalog")
    unsigned = dict(ticket)
    unsigned.pop("governance_model_plan", None)
    signed, plan = SELECTOR.enrich_ticket(unsigned, token)
    verify_signed_plan(unsigned, signed, plan)
    return signed, plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ticket = _load_issue_ticket(Path(args.event_path))
    signed, plan = sign(ticket, os.getenv("OPENROUTER_API_KEY", ""))

    unsigned = dict(ticket)
    unsigned.pop("governance_model_plan", None)
    (output / "unsigned-ticket.json").write_text(
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "signed-ticket.json").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "signed-ticket-body.md").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "governance-model-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "status": "PASS",
        "task_id": str(signed.get("task_id") or ""),
        "plan_sha256": plan["plan_sha256"],
        "candidate_pool_authority": plan["candidate_pool_authority"],
        "model_assignment_authority": plan["model_assignment_authority"],
        "candidate_count": int(plan.get("expert_candidate_pool_size") or 0),
        "candidate_pool_sha256": str(plan.get("expert_candidate_pool_sha256") or ""),
        "governance_selected_model_count": 0,
        "governance_recovery_model_count": 0,
        "expert_center_dynamic_composition_required": True,
        "fixed_team_size_required": False,
        "fixed_four_plus_four_required": False,
        "company_uniqueness_required": False,
        "flagship_filter_required": False,
        "price_filter_required": False,
        "intelligence_rank_required": False,
        "provider_endpoint_qualification_required": False,
        "zdr_endpoint_qualification_required": False,
        "free_first_required": False,
        "canary_required_before_execution": False,
        "provider_routing_mode": "unrestricted-openrouter",
        "model_calls": 0,
    }
    (output / "governance-signing-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
