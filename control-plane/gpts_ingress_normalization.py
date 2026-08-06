#!/usr/bin/env python3
"""Deterministic ingress normalization for safely recoverable GPT control tickets.

This adapter runs outside the stable control-plane validator. It repairs only
representations whose canonical route and payload meaning can be inferred from
ticket structure without model calls. Route labels are hints, not authorities:
ambiguous or malformed payloads still fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

V3 = "governance-control-ticket-v3"
V4 = "governance-control-ticket-v4"

SCHEMA_ALIASES = {
    "3": V3,
    "3.0": V3,
    "v3": V3,
    "governance-v3": V3,
    "governance-control-ticket-v3.0": V3,
    "4": V4,
    "4.0": V4,
    "v4": V4,
    "governance-v4": V4,
    "governance-control-ticket-v4.0": V4,
}

CANONICAL_ROUTES = {"compute", "expert", "intelligence"}
ROUTE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,127}$")

NARRATIVE_FIELDS = {
    "title",
    "user_request",
    "requirements",
    "language",
    "output_language",
}
STRATEGIC_ANALYSIS_FIELDS = {
    "task",
    "constraints",
    "evidence_requirements",
    "language",
    "output_language",
    "output_structure",
    "scope",
    "title",
    "objective",
    "private_output",
}
EXPERT_FIELDS = {
    "objective",
    "pipeline",
    "task",
    "execution_acceptance",
    "evidence",
    "approved_budget",
    "private_output",
}
INTELLIGENCE_REQUIRED_FIELDS = {
    "objective",
    "data_policy",
    "requests",
    "acceptance",
}


def _packet(control: Any, body: str) -> dict[str, Any]:
    try:
        value = control._load_json_text(control._original_request_body(body))
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _schema_key(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return str(value).strip().lower()
        return f"{int(value)}.0" if isinstance(value, float) else str(value)
    return str(value).strip().lower()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for raw in value:
        if isinstance(raw, str) and raw.strip():
            output.append(raw.strip())
    return output


def _optional_string_list(
    ticket: Mapping[str, Any], field: str
) -> tuple[list[str], str]:
    if field not in ticket:
        return [], ""
    value = ticket.get(field)
    if isinstance(value, str):
        item = value.strip()
        if not item:
            return [], f"{field} must not be an empty string"
        return [item], ""
    if not isinstance(value, list):
        return [], f"{field} must be a string or an array of non-empty strings"
    output: list[str] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, str) or not raw.strip():
            return [], f"{field}[{index}] must be a non-empty string"
        output.append(raw.strip())
    return output, ""


def _governed_expert_ticket(
    *,
    objective: str,
    question: str,
    requirements: list[str],
    language: str,
    private_output: bool = False,
) -> dict[str, Any]:
    return {
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
        "private_output": private_output,
    }


def _narrative_expert_ticket(ticket: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    keys = {str(key) for key in ticket}
    if "user_request" not in keys or not keys.issubset(NARRATIVE_FIELDS):
        return {}, (
            "narrative compatibility shape requires only title, user_request, "
            "requirements, language or output_language"
        )
    question = str(ticket.get("user_request") or "").strip()
    if not question:
        return {}, "narrative compatibility shape requires a non-empty user_request"
    objective = str(ticket.get("title") or question).strip() or question
    raw_language = ticket.get("language") or ticket.get("output_language") or "zh-CN"
    if not isinstance(raw_language, str) or not raw_language.strip():
        return {}, "language must be a non-empty string"
    language = raw_language.strip()
    requirements, error = _optional_string_list(ticket, "requirements")
    if error:
        return {}, error
    if not requirements:
        requirements = ["区分事实、推断和未知，并说明证据局限"]
    return _governed_expert_ticket(
        objective=objective,
        question=question,
        requirements=requirements,
        language=language,
    ), ""


def _strategic_expert_ticket(ticket: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    keys = {str(key) for key in ticket}
    if "task" not in keys or not keys.issubset(STRATEGIC_ANALYSIS_FIELDS):
        return {}, (
            "strategic analysis compatibility shape requires task and only "
            "constraints, evidence_requirements, language, output_language, "
            "output_structure, scope, title, objective or private_output"
        )

    raw_task = ticket.get("task")
    if not isinstance(raw_task, str) or not raw_task.strip():
        return {}, "strategic analysis task must be a non-empty string"
    question = raw_task.strip()

    raw_language = ticket.get("language") or ticket.get("output_language") or "zh-CN"
    if not isinstance(raw_language, str) or not raw_language.strip():
        return {}, "language must be a non-empty string"
    language = raw_language.strip()

    requirements: list[str] = []
    for field in ("constraints", "evidence_requirements"):
        values, error = _optional_string_list(ticket, field)
        if error:
            return {}, error
        requirements.extend(values)

    output_structure, error = _optional_string_list(ticket, "output_structure")
    if error:
        return {}, error
    if output_structure:
        requirements.append(
            "输出结构必须依次包含：" + "；".join(output_structure)
        )

    scope = ticket.get("scope")
    if scope is not None:
        if not isinstance(scope, Mapping):
            return {}, "scope must be an object"
        try:
            scope_text = json.dumps(
                dict(scope),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return {}, "scope must be JSON-serializable without NaN or Infinity"
        requirements.append("分析范围（必须遵守）：" + scope_text)

    if not requirements:
        requirements = ["区分事实、推断和未知，并说明证据局限"]

    raw_objective = ticket.get("objective") or ticket.get("title") or question
    if not isinstance(raw_objective, str) or not raw_objective.strip():
        return {}, "objective or title must be a non-empty string when supplied"
    objective = raw_objective.strip()

    private_output = ticket.get("private_output", False)
    if not isinstance(private_output, bool):
        return {}, "private_output must be a boolean"

    return _governed_expert_ticket(
        objective=objective,
        question=question,
        requirements=requirements,
        language=language,
        private_output=private_output,
    ), ""


def _infer_route_and_ticket(
    route_label: str, ticket: Any
) -> tuple[str, dict[str, Any], list[str], str]:
    """Infer one canonical route from structure; never from an alias list."""
    if not isinstance(ticket, Mapping):
        return "", {}, [], "non-canonical route requires an object ticket"

    keys = {str(key) for key in ticket}
    changes: list[str] = []

    if "operation" in keys:
        operation = ticket.get("operation")
        if not isinstance(operation, str) or not operation.strip():
            return "", {}, [], "compute-shaped ticket requires a non-empty operation"
        changes.append(f"route:{route_label}->compute")
        return "compute", dict(ticket), changes, ""

    if INTELLIGENCE_REQUIRED_FIELDS.issubset(keys):
        changes.append(f"route:{route_label}->intelligence")
        return "intelligence", dict(ticket), changes, ""

    if {"objective", "task"}.issubset(keys) and keys.issubset(EXPERT_FIELDS):
        changes.append(f"route:{route_label}->expert")
        return "expert", dict(ticket), changes, ""

    if keys.issubset(NARRATIVE_FIELDS) and "user_request" in keys:
        transformed, error = _narrative_expert_ticket(ticket)
        if error:
            return "", {}, [], error
        changes.extend(
            [
                f"route:{route_label}->expert",
                "ticket:narrative->governed-expert",
            ]
        )
        return "expert", transformed, changes, ""

    if (
        keys.issubset(STRATEGIC_ANALYSIS_FIELDS)
        and "task" in keys
        and isinstance(ticket.get("task"), str)
    ):
        transformed, error = _strategic_expert_ticket(ticket)
        if error:
            return "", {}, [], error
        changes.extend(
            [
                f"route:{route_label}->expert",
                "ticket:strategic-analysis->governed-expert",
            ]
        )
        return "expert", transformed, changes, ""

    if keys.issubset({"query", "requirements", "language"}) and "query" in keys:
        return "", {}, [], (
            "generic intelligence query tickets cannot be dispatched safely because "
            "the intelligence center requires an explicit connector request plan"
        )

    return "", {}, [], (
        f"route {route_label} is ambiguous for ticket fields {sorted(keys)}"
    )


def _normalize_canonical_expert_ticket(
    ticket: Any,
) -> tuple[dict[str, Any] | None, str, str]:
    """Repair safe expert representations even when route is already canonical."""
    if not isinstance(ticket, Mapping):
        return None, "", ""
    keys = {str(key) for key in ticket}
    if keys.issubset(NARRATIVE_FIELDS) and "user_request" in keys:
        transformed, error = _narrative_expert_ticket(ticket)
        return transformed if not error else None, "ticket:narrative->governed-expert", error
    if (
        keys.issubset(STRATEGIC_ANALYSIS_FIELDS)
        and "task" in keys
        and isinstance(ticket.get("task"), str)
    ):
        transformed, error = _strategic_expert_ticket(ticket)
        return (
            transformed if not error else None,
            "ticket:strategic-analysis->governed-expert",
            error,
        )
    return None, "", ""


def _normalize_wait(value: Any) -> tuple[Any, str, str]:
    if value is None:
        return value, "", ""
    parsed: int | None = None
    if isinstance(value, int) and not isinstance(value, bool):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("+-").isdigit():
            parsed = int(stripped)
    if parsed is None:
        return value, "", ""
    bounded = min(2700, max(60, parsed))
    if bounded == parsed and isinstance(value, int) and not isinstance(value, bool):
        return parsed, "", ""
    return bounded, f"wait_seconds:{value}->{bounded}", ""


def normalize_packet(
    packet: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], str]:
    """Return a canonical packet, an audit trail and a fail-closed error."""
    normalized = dict(packet)
    changes: list[str] = []

    raw_schema = packet.get("schema_version")
    schema_key = _schema_key(raw_schema)
    if schema_key in SCHEMA_ALIASES:
        canonical = SCHEMA_ALIASES[schema_key]
        if raw_schema != canonical:
            normalized["schema_version"] = canonical
            changes.append(f"schema_version:{raw_schema}->{canonical}")

    raw_route_value = packet.get("route")
    raw_route_text = str(raw_route_value or "").strip()
    raw_route = raw_route_text.lower()

    if raw_route in CANONICAL_ROUTES:
        if raw_route_text != raw_route:
            normalized["route"] = raw_route
            changes.append(f"route:{raw_route_text}->{raw_route}")
        if raw_route == "expert":
            transformed, ticket_change, error = _normalize_canonical_expert_ticket(
                packet.get("ticket")
            )
            if error:
                return normalized, changes, error
            if transformed is not None:
                normalized["ticket"] = transformed
                changes.append(ticket_change)
    elif raw_route:
        if not ROUTE_NAME_PATTERN.fullmatch(raw_route):
            return normalized, changes, (
                "non-canonical route must use 1-128 lowercase letters, digits, "
                "periods, underscores, colons, slashes or hyphens"
            )
        route, ticket, route_changes, error = _infer_route_and_ticket(
            raw_route, packet.get("ticket")
        )
        if error:
            return normalized, changes, error
        normalized["route"] = route
        normalized["ticket"] = ticket
        changes.extend(route_changes)

    if "wait_seconds" in packet:
        bounded, wait_change, wait_error = _normalize_wait(packet.get("wait_seconds"))
        if wait_error:
            return normalized, changes, wait_error
        normalized["wait_seconds"] = bounded
        if wait_change:
            changes.append(wait_change)

    return normalized, changes, ""


def _canonical_body(packet: Mapping[str, Any]) -> str:
    return json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def patch(control: Any) -> None:
    """Patch the already reliability-wrapped control module in place."""
    if getattr(control, "_gpts_ingress_normalization_patched", False):
        return
    control._gpts_ingress_normalization_patched = True

    original_prepare = control.prepare
    original_fingerprint = control._request_fingerprint

    def request_fingerprint(body: str) -> str:
        packet = _packet(control, body)
        if not packet:
            return ""
        normalized, _, error = normalize_packet(packet)
        material = packet if error else normalized
        return original_fingerprint(_canonical_body(material))

    def prepare(args: argparse.Namespace) -> int:
        root = Path(args.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        event_path = Path(args.event_path)
        effective_args = args
        changes: list[str] = []
        normalization_error = ""
        original_schema = ""
        canonical_schema = ""

        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
            issue = event.get("issue") if isinstance(event.get("issue"), dict) else {}
            body = control._original_request_body(str(issue.get("body") or ""))
            packet = control._load_json_text(body)
            if not isinstance(packet, dict):
                raise ValueError("control ticket must be a JSON object")
            original_schema = str(packet.get("schema_version") or "")
            normalized, changes, normalization_error = normalize_packet(packet)
            canonical_schema = str(normalized.get("schema_version") or "")
            if not normalization_error and changes:
                canonical = _canonical_body(normalized)
                patched_event = dict(event)
                patched_issue = dict(issue)
                patched_issue["body"] = canonical
                patched_event["issue"] = patched_issue
                compatibility_event = root / "generic-ingress-event.json"
                compatibility_event.write_text(
                    json.dumps(patched_event, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                selected_request = root / "selected-request.md"
                if selected_request.exists():
                    selected_request.write_text(canonical + "\n", encoding="utf-8")
                effective_args = argparse.Namespace(**vars(args))
                effective_args.event_path = str(compatibility_event)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            normalization_error = f"generic ingress normalization failed: {exc}"

        original_prepare(effective_args)
        status_path = root / "prepare-status.json"
        status = _load_optional(status_path)
        existing_changes = list(status.get("compatibility_normalizations") or [])
        merged_changes: list[str] = []
        for item in [*changes, *existing_changes]:
            if item not in merged_changes:
                merged_changes.append(item)
        if original_schema:
            status["request_schema_version_original"] = original_schema
        if canonical_schema:
            status["request_schema_version"] = canonical_schema
        status["compatibility_normalized"] = bool(merged_changes)
        status["compatibility_normalizations"] = merged_changes

        if normalization_error:
            status["accepted"] = False
            existing_reason = str(status.get("reason") or "")
            status["reason"] = (
                f"{existing_reason}; {normalization_error}"
                if existing_reason
                else normalization_error
            )
            status["target_repository"] = ""
            status["child_issue_title"] = ""
            status["child_command"] = ""
            child_path = root / "child-ticket.json"
            if child_path.exists():
                child_path.unlink()

        control._write_json(status_path, status)
        control._write_output(
            "accepted", str(status.get("accepted") is True).lower()
        )
        control._write_output("reason", status.get("reason") or "")
        return 0 if status.get("accepted") is True else 2

    control._request_fingerprint = request_fingerprint
    control.prepare = prepare
