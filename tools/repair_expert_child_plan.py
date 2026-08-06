#!/usr/bin/env python3
"""Regenerate only the immutable governance model plan for one expert child Issue."""
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
RETRY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
EXPECTED_ROUTE = "expert-team"


class ExpertChildRepairError(RuntimeError):
    """Raised when an existing child ticket cannot be repaired safely."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExpertChildRepairError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTOR = _load_module(
    "governance_expert_child_repair_selector",
    SELECTOR_PATH,
)
TASK_ENVELOPE = _load_module(
    "governance_expert_child_repair_task_envelope",
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


def _load_mapping(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpertChildRepairError(f"cannot read {field}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ExpertChildRepairError(f"{field} root must be an object")
    return dict(value)


def prepare_base_ticket(
    source: Mapping[str, Any], expected_task_id: str
) -> dict[str, Any]:
    task_id = str(source.get("task_id") or "").strip()
    if not expected_task_id or task_id != expected_task_id:
        raise ExpertChildRepairError(
            f"task_id mismatch: expected {expected_task_id!r}, found {task_id!r}"
        )
    if source.get("route") != EXPECTED_ROUTE:
        raise ExpertChildRepairError("expert child route must be expert-team")
    if source.get("private_output") is not False:
        raise ExpertChildRepairError("expert child private_output must be false")
    if not isinstance(source.get("task"), Mapping):
        raise ExpertChildRepairError("expert child task object is missing")
    if not isinstance(source.get("approved_budget"), Mapping):
        raise ExpertChildRepairError("expert child approved_budget object is missing")
    if not isinstance(source.get("governance_model_plan"), Mapping):
        raise ExpertChildRepairError("existing governance_model_plan is missing")
    base = dict(source)
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
    if source_without_plan != repaired_without_plan:
        raise ExpertChildRepairError(
            "repair changed child ticket fields outside governance_model_plan"
        )
    if repaired_plan != plan:
        raise ExpertChildRepairError("repaired ticket and plan output disagree")
    if plan.get("plan_sha256") != _plan_digest(plan):
        raise ExpertChildRepairError("regenerated plan digest mismatch")
    if plan.get("task_sha256") != SELECTOR.task_sha256(repaired):
        raise ExpertChildRepairError("regenerated plan task hash mismatch")
    if plan.get("endpoint_qualification_performed_by_governance") is not True:
        raise ExpertChildRepairError("regenerated plan lacks endpoint qualification")

    expected_context = TASK_ENVELOPE.required_context_tokens(repaired)
    if plan.get("required_context_tokens") != expected_context:
        raise ExpertChildRepairError(
            "regenerated plan does not match the frozen expert task envelope"
        )
    if expected_context < TASK_ENVELOPE.MINIMUM_CONTEXT_LENGTH:
        raise ExpertChildRepairError("expert context floor was not enforced")

    selected_rows = list(plan.get("selected_models") or [])
    recovery_rows = list(plan.get("recovery_models") or [])
    companies: set[str] = set()
    models: set[str] = set()
    for field, rows in (
        ("selected_models", selected_rows),
        ("recovery_models", recovery_rows),
    ):
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ExpertChildRepairError(
                    f"{field}[{index}] is not an object"
                )
            model = str(row.get("model") or "").strip()
            company = str(row.get("company") or "").strip().casefold()
            endpoint_hash = str(row.get("endpoint_inventory_sha256") or "")
            provider_count = row.get("qualified_provider_count")
            evidence = str(row.get("selection_evidence") or "")
            if not model or model in models:
                raise ExpertChildRepairError(
                    "regenerated plan contains duplicate model"
                )
            if not company:
                raise ExpertChildRepairError(
                    "regenerated plan model company is missing"
                )
            if company in companies:
                raise ExpertChildRepairError(
                    "regenerated plan reuses a model company"
                )
            if "strict-tier+company-highest-intelligence-reasoning-flagship" not in evidence:
                raise ExpertChildRepairError(
                    "regenerated model lacks strict-tier reasoning flagship evidence"
                )
            if (
                isinstance(provider_count, bool)
                or not isinstance(provider_count, int)
                or provider_count < TASK_ENVELOPE.MINIMUM_QUALIFIED_PROVIDER_COUNT
            ):
                raise ExpertChildRepairError(
                    "model does not satisfy the qualified ZDR provider floor"
                )
            if len(endpoint_hash) != 64 or any(
                character not in "0123456789abcdef"
                for character in endpoint_hash
            ):
                raise ExpertChildRepairError(
                    "model endpoint inventory hash is invalid"
                )
            models.add(model)
            companies.add(company)


def regenerate(
    source: Mapping[str, Any], expected_task_id: str, token: str
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    token = os.getenv("OPENROUTER_API_KEY", "")
    if not token:
        raise ExpertChildRepairError("OPENROUTER_API_KEY is required")
    repaired, plan = regenerate(source, args.expected_task_id, token)
    Path(args.output_ticket).write_text(
        json.dumps(repaired, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.output_plan).write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "task_id": args.expected_task_id,
                "retry_id": args.retry_id,
                "plan_sha256": plan["plan_sha256"],
                "expert_count": plan["expert_count"],
                "recovery_count": plan["recovery_count"],
                "required_context_tokens": plan["required_context_tokens"],
                "task_envelope_schema_version": (
                    TASK_ENVELOPE.EXPERT_RUNTIME_SCHEMA_VERSION
                ),
                "minimum_qualified_provider_count": (
                    TASK_ENVELOPE.MINIMUM_QUALIFIED_PROVIDER_COUNT
                ),
                "selected_models": [
                    row["model"] for row in plan["selected_models"]
                ],
                "recovery_models": [
                    row["model"] for row in plan["recovery_models"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
