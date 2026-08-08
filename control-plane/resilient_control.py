#!/usr/bin/env python3
"""Control-plane entrypoint with dynamic expert candidate attachment.

Transport/authentication remain intact. Governance-side Top20/Top50, budget,
company, flagship, Provider/ZDR and fixed-team selection gates are removed.
Large live candidate inventories are transported as integrity-checked compressed
Issue-comment chunks so GitHub's Issue-body size limit never becomes a model gate.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import sys
import zlib
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
COPILOT_ROOT = ROOT.parent / "governance-copilot"
POOL_CHUNK_SCHEMA = "governance-candidate-pool-chunk-v1"
POOL_TRANSPORT_SCHEMA = "governance-candidate-pool-transport-v1"
POOL_CHUNK_CHARS = 48_000
POOL_FIELDS = (
    "expert_candidate_pool",
    "top50_reasoning_models",
    "top50_expert_selectable_candidates",
    "top20_reasoning_models",
    "top20_expert_selectable_candidates",
)


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
ROUTE_PAUSE = _load(
    "governance_route_pause_policy_runtime",
    ROOT / "route_pause_policy.py",
)
CONTROL._github_request = HTTP.github_request
RELIABILITY.patch(CONTROL)
INGRESS.patch(CONTROL)
ROUTE_PAUSE.patch(CONTROL)

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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


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


def _candidate_pool(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    for field in POOL_FIELDS:
        value = plan.get(field)
        if isinstance(value, list):
            rows = [dict(row) for row in value if isinstance(row, Mapping)]
            if rows:
                return rows
    return []


def _compact_plan_and_chunks(
    plan: Mapping[str, Any],
    task_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Move the unrestricted candidate inventory out of the bounded Issue body."""
    pool = _candidate_pool(plan)
    compact = dict(plan)
    for field in POOL_FIELDS:
        compact.pop(field, None)

    chunks: list[dict[str, Any]] = []
    if pool:
        raw = _canonical_json(pool)
        pool_sha = hashlib.sha256(raw).hexdigest()
        encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
        payload_chunks = [
            encoded[offset : offset + POOL_CHUNK_CHARS]
            for offset in range(0, len(encoded), POOL_CHUNK_CHARS)
        ] or [""]
        transport = {
            "schema_version": POOL_TRANSPORT_SCHEMA,
            "chunk_schema_version": POOL_CHUNK_SCHEMA,
            "encoding": "zlib+base64",
            "candidate_count": len(pool),
            "raw_sha256": pool_sha,
            "chunk_count": len(payload_chunks),
            "compressed_base64_characters": len(encoded),
            "transport": "governance-created-child-issue-comments-before-run-command",
        }
        compact["expert_candidate_pool_size"] = len(pool)
        compact["expert_candidate_pool_sha256"] = pool_sha
        compact["expert_candidate_pool_transport"] = transport
        for index, data in enumerate(payload_chunks, 1):
            chunks.append(
                {
                    "schema_version": POOL_CHUNK_SCHEMA,
                    "task_id": task_id,
                    "sha256": pool_sha,
                    "encoding": "zlib+base64",
                    "index": index,
                    "count": len(payload_chunks),
                    "data": data,
                }
            )

    compact_material = dict(compact)
    compact_material.pop("plan_sha256", None)
    compact["plan_sha256"] = hashlib.sha256(_canonical_json(compact_material)).hexdigest()
    return compact, chunks


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
        enriched, full_plan = EXPERT_SELECTOR.enrich_ticket(
            ticket,
            os.getenv("OPENROUTER_API_KEY", ""),
        )
        compact_plan, chunks = _compact_plan_and_chunks(
            full_plan,
            str(ticket.get("task_id") or ""),
        )
        enriched["governance_model_plan"] = compact_plan
        CONTROL._write_json(ticket_path, enriched)
        CONTROL._write_json(root / "expert-model-plan.json", full_plan)
        CONTROL._write_json(root / "expert-model-plan-transport.json", compact_plan)
        CONTROL._write_json(root / "expert-candidate-pool-chunks.json", chunks)
        status.update(
            {
                "model_selection_authority": "expert-assessment-center-dynamic-ortools",
                "candidate_pool_authority": "decision-system-governance",
                "model_assignment_authority": "expert-assessment-center-dynamic-ortools",
                "model_plan_sha256": compact_plan["plan_sha256"],
                "selected_expert_count": 0,
                "selected_recovery_count": 0,
                "expert_candidate_pool_size": int(compact_plan.get("expert_candidate_pool_size") or 0),
                "expert_candidate_pool_sha256": str(compact_plan.get("expert_candidate_pool_sha256") or ""),
                "expert_candidate_pool_chunk_count": len(chunks),
                "expert_candidate_pool_transport": POOL_TRANSPORT_SCHEMA,
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


_BASE_DISPATCH = CONTROL.dispatch


def _dispatch_with_candidate_chunks(arguments: Any) -> int:
    """Create the child Issue, inject signed pool chunks, then trigger execution."""
    root = Path(arguments.output_dir)
    status_path = root / "prepare-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    command = str(status.get("child_command") or "")

    # Prevent the base dispatcher from triggering the child workflow before all
    # candidate chunks are present. The command is posted only after transport.
    status["child_command"] = ""
    CONTROL._write_json(status_path, status)
    try:
        result = int(_BASE_DISPATCH(arguments))
    finally:
        status["child_command"] = command
        CONTROL._write_json(status_path, status)
    if result:
        return result

    dispatch_path = root / "dispatch-status.json"
    dispatch_status = json.loads(dispatch_path.read_text(encoding="utf-8"))
    repo = str(dispatch_status.get("repository") or status.get("target_repository") or "")
    issue_number = int(dispatch_status.get("issue_number") or 0)
    if not repo or issue_number <= 0:
        raise RuntimeError("child Issue was not materialized before candidate transport")

    chunks_path = root / "expert-candidate-pool-chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    chunks_posted = 0
    for chunk in chunks if isinstance(chunks, list) else []:
        body = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        if not CONTROL._comment_exists(os.getenv("CONTROL_PLANE_TOKEN", ""), repo, issue_number, body):
            CONTROL._github_request(
                "POST",
                f"/repos/{repo}/issues/{issue_number}/comments",
                token=os.getenv("CONTROL_PLANE_TOKEN", ""),
                payload={"body": body},
            )
            chunks_posted += 1

    command_posted = False
    if command and not CONTROL._comment_exists(
        os.getenv("CONTROL_PLANE_TOKEN", ""), repo, issue_number, command
    ):
        CONTROL._github_request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            token=os.getenv("CONTROL_PLANE_TOKEN", ""),
            payload={"body": command},
        )
        command_posted = True

    dispatch_status["candidate_pool_chunks_total"] = len(chunks) if isinstance(chunks, list) else 0
    dispatch_status["candidate_pool_chunks_posted"] = chunks_posted
    dispatch_status["command_posted"] = command_posted
    dispatch_status["candidate_transport_completed_before_command"] = True
    CONTROL._write_json(dispatch_path, dispatch_status)
    return 0


CONTROL.dispatch = _dispatch_with_candidate_chunks


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
