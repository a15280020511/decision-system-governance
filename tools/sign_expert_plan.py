#!/usr/bin/env python3
"""Sign one expert ticket with the frozen governance production contract.

This entrypoint performs catalog and endpoint qualification only. It never
creates a child Issue, posts an expert execution command, or calls a model.
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
TASK_ENVELOPE_PATH = ROOT / "governance-copilot" / "expert_task_envelope.py"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
ALLOWED_FIELDS = {
    "task_id",
    "objective",
    "pipeline",
    "route",
    "task",
    "execution_acceptance",
    "evidence",
    "approved_budget",
    "private_output",
}


class ExpertPlanSigningError(RuntimeError):
    """Raised when an expert plan cannot be signed without weakening policy."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExpertPlanSigningError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = _load_module("governance_plan_preview_selector", SELECTOR_PATH)
TASK_ENVELOPE = _load_module(
    "governance_plan_preview_task_envelope",
    TASK_ENVELOPE_PATH,
)
TASK_ENVELOPE.patch_selector(SELECTOR)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
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
        raise ExpertPlanSigningError("Issue body must be exactly one JSON object") from exc
    if not isinstance(ticket, Mapping):
        raise ExpertPlanSigningError("Issue body must be exactly one JSON object")
    return dict(ticket)


def validate_unsigned_ticket(ticket: Mapping[str, Any]) -> None:
    if "governance_model_plan" in ticket:
        raise ExpertPlanSigningError(
            "unsigned ticket must not contain governance_model_plan"
        )
    unknown = sorted(set(ticket) - ALLOWED_FIELDS)
    if unknown:
        raise ExpertPlanSigningError(f"unknown expert ticket fields: {unknown}")
    task_id = str(ticket.get("task_id") or "")
    if not TASK_ID_RE.fullmatch(task_id):
        raise ExpertPlanSigningError("task_id is invalid")
    if ticket.get("route") != "expert-team":
        raise ExpertPlanSigningError("route must be expert-team")
    if ticket.get("private_output") is not False:
        raise ExpertPlanSigningError("private_output must be false")

    pipeline = ticket.get("pipeline")
    if not isinstance(pipeline, Mapping):
        raise ExpertPlanSigningError("pipeline must be an object")
    if not str(pipeline.get("pipeline_id") or ""):
        raise ExpertPlanSigningError("pipeline.pipeline_id is required")
    if not str(pipeline.get("stage_id") or ""):
        raise ExpertPlanSigningError("pipeline.stage_id is required")

    task = ticket.get("task")
    if not isinstance(task, Mapping) or not str(task.get("question") or "").strip():
        raise ExpertPlanSigningError("task.question is required")

    budget = ticket.get("approved_budget")
    if not isinstance(budget, Mapping):
        raise ExpertPlanSigningError("approved_budget is required")
    calls = budget.get("calls")
    recovery = budget.get("maximum_recovery_calls")
    if isinstance(calls, bool) or not isinstance(calls, int) or not 4 <= calls <= 16:
        raise ExpertPlanSigningError("approved_budget.calls must be 4..16")
    if (
        isinstance(recovery, bool)
        or not isinstance(recovery, int)
        or not 0 <= recovery <= 4
    ):
        raise ExpertPlanSigningError(
            "approved_budget.maximum_recovery_calls must be 0..4"
        )
    if calls - recovery < 3:
        raise ExpertPlanSigningError(
            "budget must leave at least three initial expert calls"
        )
    if budget.get("cost_policy") not in {
        "prompt_led_soft_governance",
        "unbounded_with_anomaly_guard",
    }:
        raise ExpertPlanSigningError("approved_budget.cost_policy is invalid")


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
    if signed_without_plan != dict(unsigned):
        raise ExpertPlanSigningError("signing changed ticket fields outside the plan")
    if signed_plan != plan:
        raise ExpertPlanSigningError("signed ticket and plan file differ")
    if plan.get("plan_sha256") != _plan_digest(plan):
        raise ExpertPlanSigningError("plan digest mismatch")
    if plan.get("task_sha256") != SELECTOR.task_sha256(signed):
        raise ExpertPlanSigningError("plan task hash mismatch")
    if plan.get("selection_authority") != "decision-system-governance":
        raise ExpertPlanSigningError("selection authority is not governance")
    if plan.get("model_calls") != 0:
        raise ExpertPlanSigningError("plan does not prove zero model calls")
    if plan.get("endpoint_qualification_performed_by_governance") is not True:
        raise ExpertPlanSigningError("live exact endpoint qualification is missing")
    if plan.get("zdr_endpoint_qualification_required") is not True:
        raise ExpertPlanSigningError("authenticated ZDR qualification is missing")
    if plan.get("model_substitution_allowed") is not False:
        raise ExpertPlanSigningError("model substitution must be disabled")
    if plan.get("expert_center_reranking_allowed") is not False:
        raise ExpertPlanSigningError("expert center reranking must be disabled")
    if plan.get("reasoning_model_required") is not True:
        raise ExpertPlanSigningError("reasoning model requirement is missing")
    expected_flagship = (
        "highest-official-intelligence-ranked-eligible-reasoning-model-per-company"
    )
    if plan.get("flagship_definition") != expected_flagship:
        raise ExpertPlanSigningError("company reasoning flagship definition mismatch")

    expected_context = TASK_ENVELOPE.required_context_tokens(unsigned)
    if plan.get("required_context_tokens") != expected_context:
        raise ExpertPlanSigningError(
            "plan does not match the frozen expert task envelope"
        )
    if expected_context < TASK_ENVELOPE.MINIMUM_CONTEXT_LENGTH:
        raise ExpertPlanSigningError("expert context floor was not enforced")
    if plan.get("minimum_qualified_provider_count") != (
        TASK_ENVELOPE.MINIMUM_QUALIFIED_PROVIDER_COUNT
    ):
        raise ExpertPlanSigningError("ZDR provider floor is not frozen")

    selected = plan.get("selected_models")
    recovery = plan.get("recovery_models")
    if not isinstance(selected, list) or not 3 <= len(selected) <= 6:
        raise ExpertPlanSigningError("selected expert count is invalid")
    if not isinstance(recovery, list):
        raise ExpertPlanSigningError("recovery model list is invalid")

    companies: set[str] = set()
    models: set[str] = set()
    for field, rows in (("selected_models", selected), ("recovery_models", recovery)):
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ExpertPlanSigningError(
                    f"{field}[{index}] is not an object"
                )
            model = str(row.get("model") or "").strip()
            company = str(row.get("company") or "").strip().casefold()
            provider_count = row.get("qualified_provider_count")
            endpoint_hash = str(row.get("endpoint_inventory_sha256") or "")
            evidence = str(row.get("selection_evidence") or "")
            reasoning_evidence = str(row.get("reasoning_evidence") or "").strip()
            if not model or model in models:
                raise ExpertPlanSigningError(
                    "expert models are not globally distinct"
                )
            if not company:
                raise ExpertPlanSigningError("expert model company is missing")
            if company in companies:
                raise ExpertPlanSigningError(
                    "expert model companies are not globally distinct"
                )
            if row.get("reasoning_capable") is not True:
                raise ExpertPlanSigningError("expert model is not reasoning-capable")
            if not reasoning_evidence:
                raise ExpertPlanSigningError("expert model lacks reasoning evidence")
            if row.get("flagship_basis") != expected_flagship:
                raise ExpertPlanSigningError("expert model is not its company reasoning flagship")
            if (
                isinstance(provider_count, bool)
                or not isinstance(provider_count, int)
                or provider_count < TASK_ENVELOPE.MINIMUM_QUALIFIED_PROVIDER_COUNT
            ):
                raise ExpertPlanSigningError(
                    "model does not satisfy the qualified ZDR provider floor"
                )
            if "authenticated-zdr-endpoint-qualified" not in evidence:
                raise ExpertPlanSigningError(
                    "model lacks authenticated ZDR selection evidence"
                )
            if len(endpoint_hash) != 64 or any(
                character not in "0123456789abcdef"
                for character in endpoint_hash
            ):
                raise ExpertPlanSigningError(
                    "model endpoint inventory hash is invalid"
                )
            models.add(model)
            companies.add(company)


def sign(ticket: Mapping[str, Any], token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_unsigned_ticket(ticket)
    if not str(token or "").strip():
        raise ExpertPlanSigningError("OPENROUTER_API_KEY is required")
    signed, plan = SELECTOR.enrich_ticket(ticket, token)
    verify_signed_plan(ticket, signed, plan)
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

    (output / "unsigned-ticket.json").write_text(
        json.dumps(ticket, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
        "task_id": signed["task_id"],
        "plan_sha256": plan["plan_sha256"],
        "selected_models": [row["model"] for row in plan["selected_models"]],
        "recovery_models": [row["model"] for row in plan["recovery_models"]],
        "required_context_tokens": plan["required_context_tokens"],
        "minimum_qualified_provider_count": plan[
            "minimum_qualified_provider_count"
        ],
        "model_calls": 0,
        "child_dispatch": False,
    }
    (output / "plan-preview-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
