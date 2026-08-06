#!/usr/bin/env python3
"""Compatibility layer for recoverable and machine-readable GPTs submissions.

The stable control-plane core remains unchanged. This module patches its public
entry functions at runtime so legacy v3 tickets continue to work while v4 adds
client-generated idempotency keys, deterministic recovery and structured status.
A narrowly bounded adapter also repairs the exact legacy alias shape observed in
Governance Issue #153; unknown aliases and unknown ticket fields still fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

V3 = "governance-control-ticket-v3"
V4 = "governance-control-ticket-v4"
SUPPORTED = {V3, V4}
SCHEMA_ALIASES = {
    "4": V4,
    "v4": V4,
    "governance-v4": V4,
}
LEGACY_EXPERT_ROUTE_ALIAS = "research"
LEGACY_EXPERT_FIELDS = {
    "title",
    "user_request",
    "requirements",
    "output_language",
}
REJECTED_ROUTE_ALIASES = {
    "analysis",
    "strategy",
    "api",
    "simulation",
}
CLIENT_REQUEST_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
MACHINE_START = "<!-- governance-machine-status:start -->"
MACHINE_END = "<!-- governance-machine-status:end -->"


def _packet(control: Any, body: str) -> dict[str, Any]:
    try:
        value = control._load_json_text(control._original_request_body(body))
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        if item:
            output.append(item)
    return output


def _normalize_legacy_packet(
    packet: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], str]:
    """Repair only explicit, deterministic legacy aliases; reject all ambiguity."""
    normalized = dict(packet)
    changes: list[str] = []
    error = ""

    raw_schema = str(packet.get("schema_version") or "").strip()
    if raw_schema in SCHEMA_ALIASES:
        normalized["schema_version"] = SCHEMA_ALIASES[raw_schema]
        changes.append(f"schema_version:{raw_schema}->{SCHEMA_ALIASES[raw_schema]}")

    raw_route = str(packet.get("route") or "").strip()
    if raw_route == LEGACY_EXPERT_ROUTE_ALIAS:
        ticket = packet.get("ticket")
        if not isinstance(ticket, Mapping):
            error = "route alias research requires an object ticket"
            return normalized, changes, error
        keys = {str(key) for key in ticket.keys()}
        if "user_request" not in keys or not keys.issubset(LEGACY_EXPERT_FIELDS):
            error = (
                "route alias research is accepted only for the exact legacy "
                "expert ticket fields: title, user_request, requirements, "
                "output_language"
            )
            return normalized, changes, error

        question = str(ticket.get("user_request") or "").strip()
        if not question:
            error = "legacy expert ticket user_request must be a non-empty string"
            return normalized, changes, error
        objective = str(ticket.get("title") or question).strip()
        language = str(ticket.get("output_language") or "zh-CN").strip() or "zh-CN"
        requirements = _string_list(ticket.get("requirements"))
        if not requirements:
            requirements = ["区分事实、推断和未知，并明确证据局限"]

        normalized["route"] = "expert"
        normalized["ticket"] = {
            "objective": objective,
            "pipeline": "expert-team",
            "task": {
                "question": question,
                "requirements": requirements,
                "language": language,
            },
            "execution_acceptance": [
                "发布完整最终综合报告",
                "区分事实、公开立场、推断和未知",
            ],
            "evidence": [],
            "approved_budget": {
                "calls": 8,
                "maximum_recovery_calls": 1,
            },
            "private_output": False,
        }
        changes.extend(
            [
                "route:research->expert",
                "ticket:legacy-expert->governed-expert",
            ]
        )
    elif raw_route in REJECTED_ROUTE_ALIASES:
        error = (
            f"route alias {raw_route} is ambiguous and is not accepted by "
            "the bounded compatibility repair"
        )

    return normalized, changes, error


def _client_request_id(control: Any, body: str) -> str:
    value = _packet(control, body).get("client_request_id")
    return str(value).lower() if isinstance(value, str) else ""


def _fingerprint(control: Any, body: str) -> str:
    packet = _packet(control, body)
    if not packet:
        return ""
    normalized, _, normalization_error = _normalize_legacy_packet(packet)
    material_packet = packet if normalization_error else normalized
    material = {
        "route": material_packet.get("route"),
        "ticket": material_packet.get("ticket"),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prior_with_request_id(
    control: Any,
    rows: list[Mapping[str, Any]],
    *,
    issue_number: int,
    client_request_id: str,
) -> Mapping[str, Any] | None:
    if not client_request_id:
        return None
    candidates = sorted(
        (
            row
            for row in rows
            if control._is_owned_control_issue(row)
            and int(row.get("number") or 0) < issue_number
            and _client_request_id(control, str(row.get("body") or ""))
            == client_request_id
        ),
        key=lambda row: int(row.get("number") or 0),
    )
    return candidates[0] if candidates else None


def _write_machine_status(path: Path, payload: Mapping[str, Any]) -> None:
    existing = path.read_text(encoding="utf-8").rstrip()
    block = "\n".join(
        [
            "",
            MACHINE_START,
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            MACHINE_END,
            "",
        ]
    )
    path.write_text(existing + block, encoding="utf-8")


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def patch(control: Any) -> None:
    """Patch one loaded control_plane module in place."""
    if getattr(control, "_gpts_reliability_patched", False):
        return
    control._gpts_reliability_patched = True

    original_prepare = control.prepare
    original_select = control.select
    original_dispatch = control.dispatch
    original_render = control.render
    original_find_duplicate = control._find_duplicate_issue

    def request_fingerprint(body: str) -> str:
        return _fingerprint(control, body)

    def find_duplicate_issue(
        rows: list[Mapping[str, Any]],
        *,
        issue_number: int,
        fingerprint: str,
    ) -> Mapping[str, Any] | None:
        current = next(
            (
                row
                for row in rows
                if int(row.get("number") or 0) == issue_number
                and control._is_owned_control_issue(row)
            ),
            None,
        )
        if current is not None:
            client_request_id = _client_request_id(
                control, str(current.get("body") or "")
            )
            prior = _prior_with_request_id(
                control,
                rows,
                issue_number=issue_number,
                client_request_id=client_request_id,
            )
            if prior is not None:
                return prior
        return original_find_duplicate(
            rows,
            issue_number=issue_number,
            fingerprint=fingerprint,
        )

    def select(args: argparse.Namespace) -> int:
        result = original_select(args)
        root = Path(args.output_dir)
        status_path = root / "selection-status.json"
        request_path = root / "selected-request.md"
        if not status_path.exists() or not request_path.exists():
            return result
        status = _load_optional(status_path)
        if status.get("has_task") is not True:
            return result

        body = request_path.read_text(encoding="utf-8")
        client_request_id = _client_request_id(control, body)
        status["client_request_id"] = client_request_id
        status["request_schema_version"] = str(
            _packet(control, body).get("schema_version") or ""
        )

        if client_request_id:
            token = os.getenv("GITHUB_TOKEN", "")
            rows = control._list_issues(token, args.repository, state="all")
            prior = _prior_with_request_id(
                control,
                rows,
                issue_number=int(status.get("issue_number") or 0),
                client_request_id=client_request_id,
            )
            if prior is not None:
                prior_body = str(prior.get("body") or "")
                conflict = request_fingerprint(prior_body) != str(
                    status.get("request_fingerprint") or ""
                )
                status.update(
                    {
                        "duplicate": True,
                        "duplicate_of_issue_number": int(prior.get("number") or 0),
                        "duplicate_of_issue_url": str(prior.get("html_url") or ""),
                        "idempotent_reuse": not conflict,
                        "request_id_conflict": conflict,
                    }
                )
                control._write_output("duplicate", "true")
                control._write_output(
                    "duplicate_of_issue_number",
                    status["duplicate_of_issue_number"],
                )
                control._write_output(
                    "duplicate_of_issue_url",
                    status["duplicate_of_issue_url"],
                )
        control._write_json(status_path, status)
        control._write_output("client_request_id", client_request_id)
        return result

    def prepare(args: argparse.Namespace) -> int:
        root = Path(args.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        event_path = Path(args.event_path)
        original_schema_version = ""
        schema_version = ""
        client_request_id = ""
        validation_error = ""
        normalizations: list[str] = []
        effective_args = args

        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
            issue = event.get("issue") if isinstance(event.get("issue"), dict) else {}
            body = control._original_request_body(str(issue.get("body") or ""))
            packet = control._load_json_text(body)
            if not isinstance(packet, dict):
                packet = {}
            original_schema_version = str(packet.get("schema_version") or "")
            normalized, normalizations, normalization_error = _normalize_legacy_packet(
                packet
            )
            schema_version = str(normalized.get("schema_version") or "")
            raw_request_id = normalized.get("client_request_id")
            client_request_id = (
                str(raw_request_id).lower() if isinstance(raw_request_id, str) else ""
            )
            if normalization_error:
                validation_error = normalization_error
            if schema_version == V4:
                if not CLIENT_REQUEST_ID_RE.fullmatch(client_request_id):
                    request_error = (
                        "client_request_id must be a canonical UUID for v4 tickets"
                    )
                    validation_error = (
                        f"{validation_error}; {request_error}"
                        if validation_error
                        else request_error
                    )
                transformed = dict(normalized)
                transformed["schema_version"] = V3
                transformed.pop("client_request_id", None)
            elif schema_version == V3:
                transformed = dict(normalized)
            else:
                transformed = dict(normalized)
                schema_error = f"schema_version must be one of {sorted(SUPPORTED)}"
                validation_error = (
                    f"{validation_error}; {schema_error}"
                    if validation_error
                    else schema_error
                )

            if schema_version in SUPPORTED and (schema_version == V4 or normalizations):
                patched_event = dict(event)
                patched_issue = dict(issue)
                patched_issue["body"] = json.dumps(
                    transformed,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                patched_event["issue"] = patched_issue
                compatibility_event = root / "compatibility-event-v3.json"
                compatibility_event.write_text(
                    json.dumps(patched_event, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                effective_args = argparse.Namespace(**vars(args))
                effective_args.event_path = str(compatibility_event)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            validation_error = f"v4 compatibility parse failed: {exc}"

        original_prepare(effective_args)
        status_path = root / "prepare-status.json"
        status = _load_optional(status_path)
        status["client_request_id"] = client_request_id
        status["request_schema_version"] = schema_version
        status["request_schema_version_original"] = original_schema_version
        status["compatibility_normalized"] = bool(normalizations)
        status["compatibility_normalizations"] = normalizations
        selected_request = root / "selected-request.md"
        source_body = (
            selected_request.read_text(encoding="utf-8")
            if selected_request.exists()
            else event_path.read_text(encoding="utf-8")
        )
        status["request_fingerprint"] = request_fingerprint(source_body)

        if validation_error:
            status["accepted"] = False
            existing = str(status.get("reason") or "")
            status["reason"] = (
                f"{existing}; {validation_error}" if existing else validation_error
            )
            status["target_repository"] = ""
            status["child_issue_title"] = ""
            status["child_command"] = ""
            child_ticket = root / "child-ticket.json"
            if child_ticket.exists():
                child_ticket.unlink()

        control._write_json(status_path, status)
        control._write_output(
            "accepted", str(status.get("accepted") is True).lower()
        )
        control._write_output("reason", status.get("reason") or "")
        control._write_output("client_request_id", client_request_id)
        control._write_output(
            "request_fingerprint", status.get("request_fingerprint") or ""
        )
        return 0 if status.get("accepted") is True else 2

    def dispatch(args: argparse.Namespace) -> int:
        root = Path(args.output_dir)
        status = _load_optional(root / "prepare-status.json")
        repo = str(status.get("target_repository") or "")
        token = os.getenv("CONTROL_PLANE_TOKEN", "")
        try:
            repository = control._github_request(
                "GET", f"/repos/{repo}", token=token
            )
            if not isinstance(repository, Mapping):
                raise RuntimeError("target repository metadata is not an object")
            if str(repository.get("full_name") or "") != repo:
                raise RuntimeError("target repository identity mismatch")
            if repository.get("archived") is True or repository.get("disabled") is True:
                raise RuntimeError("target repository is archived or disabled")
            probe = control._github_request(
                "GET", f"/repos/{repo}/issues?state=all&per_page=1", token=token
            )
            if not isinstance(probe, list):
                raise RuntimeError("target Issue gateway readback failed")
        except RuntimeError as exc:
            control._write_json(
                root / "dispatch-error.json",
                {
                    "error_code": "TARGET_NOT_READY",
                    "retryable": False,
                    "target_repository": repo,
                    "detail": str(exc)[:2000],
                    "client_request_id": status.get("client_request_id") or "",
                },
            )
            raise

        result = original_dispatch(args)
        dispatch_path = root / "dispatch-status.json"
        dispatch_status = _load_optional(dispatch_path)
        dispatch_status["client_request_id"] = status.get("client_request_id") or ""
        dispatch_status["request_fingerprint"] = status.get("request_fingerprint") or ""
        dispatch_status["target_preflight_verified"] = True
        control._write_json(dispatch_path, dispatch_status)
        return result

    def render(args: argparse.Namespace) -> int:
        result = original_render(args)
        root = Path(args.output_dir)
        selection = _load_optional(root / "selection-status.json")
        prepared = _load_optional(root / "prepare-status.json")
        dispatched = _load_optional(root / "dispatch-status.json")
        final = _load_optional(root / "final-status.json")
        merged = {**selection, **prepared, **dispatched, **final}

        state_map = {
            "duplicate": (
                "REQUEST_ID_CONFLICT"
                if selection.get("request_id_conflict")
                else "DUPLICATE_REUSED"
            ),
            "exhausted": "FAILED",
            "running": "RUNNING",
            "rejected": "REJECTED",
            "dispatched": "DISPATCHED",
            "final": "COMPLETED" if final.get("success") else "FAILED",
        }
        state = state_map[args.phase]
        error_code: str | None = None
        retryable = False
        if state == "REQUEST_ID_CONFLICT":
            error_code = "REQUEST_ID_CONFLICT"
        elif args.phase == "exhausted":
            error_code = "CONTROL_RETRY_EXHAUSTED"
        elif args.phase == "rejected":
            error_code = "CONTROL_SCHEMA_REJECTED"
        elif args.phase == "final" and not final.get("success"):
            error_code = str(final.get("final_status") or "CHILD_EXECUTION_FAILED")
            retryable = error_code in {
                "CONTROL_TIMEOUT",
                "CONTROL_MONITOR_ERROR",
                "CONTROL_ASYNC_DEADLINE_EXCEEDED",
            }

        client_request_id = str(merged.get("client_request_id") or "")
        payload = {
            "schema_version": "governance-machine-status-v1",
            "client_request_id": client_request_id or None,
            "issue_number": int(
                merged.get("governance_issue_number")
                or merged.get("issue_number")
                or 0
            ),
            "task_id": str(merged.get("task_id") or "") or None,
            "state": state,
            "route": str(merged.get("route") or "") or None,
            "child_issue_number": int(dispatched.get("issue_number") or 0) or None,
            "body_fingerprint": str(
                merged.get("request_fingerprint") or ""
            )
            or None,
            "read_after_write_verified": None,
            "read_after_write_evidence": (
                "CONTROL_RECEIVED" if client_request_id else None
            ),
            "retryable": retryable,
            "error_code": error_code,
            "canonical_issue_number": int(
                selection.get("duplicate_of_issue_number") or 0
            )
            or None,
            "compatibility_normalized": bool(
                merged.get("compatibility_normalized")
            ),
            "compatibility_normalizations": list(
                merged.get("compatibility_normalizations") or []
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_machine_status(Path(args.output), payload)
        return result

    control._request_fingerprint = request_fingerprint
    control._find_duplicate_issue = find_duplicate_issue
    control.select = select
    control.prepare = prepare
    control.dispatch = dispatch
    control.render = render
