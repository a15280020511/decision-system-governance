"""Build a governance-signed expert roster from the live flagship cost ranking.

The module is deterministic after the OpenRouter catalog snapshot is fetched.
It never calls a model. It selects the lowest-estimated-cost distinct-company
flagships, reserves distinct-company recovery models, assigns one primary model
per explicit work item, and binds the resulting roster to the work-plan digest.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
COPILOT_ROOT = ROOT / "governance-copilot"
if str(COPILOT_ROOT) not in sys.path:
    sys.path.insert(0, str(COPILOT_ROOT))

from rank_flagships_by_task_cost import (  # noqa: E402
    DEFAULT_EXPECTED_COMPLETION_TOKENS,
    DEFAULT_EXPECTED_PROMPT_TOKENS,
    rank_flagships_by_task_cost,
)
from select_paid_governance_flagship_model import select as select_flagships  # noqa: E402

WORK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,63}$")
ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,63}$")
MINIMUM_TEAM_SIZE = 2
MAXIMUM_TEAM_SIZE = 8
MAXIMUM_RECOVERY_MEMBERS = 4


class GovernedExpertRosterError(RuntimeError):
    """Fail-closed roster construction error."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise GovernedExpertRosterError(f"{field} is invalid")
    return value.strip()


def _bounded_string_list(
    value: Any,
    field: str,
    *,
    maximum_items: int,
    maximum_characters: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise GovernedExpertRosterError(f"{field} must be a bounded list")
    rows: list[str] = []
    for index, item in enumerate(value):
        rows.append(
            _bounded_text(
                item,
                f"{field}[{index}]",
                maximum_characters,
            )
        )
    if len(rows) != len(set(rows)):
        raise GovernedExpertRosterError(f"{field} contains duplicates")
    return rows


def _work_items(team_plan: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    if team_plan.get("schema_version") != "expert-team-plan-v1":
        raise GovernedExpertRosterError(
            "team_plan.schema_version must be expert-team-plan-v1"
        )
    raw_items = team_plan.get("work_items")
    if not isinstance(raw_items, list) or not (
        MINIMUM_TEAM_SIZE <= len(raw_items) <= MAXIMUM_TEAM_SIZE
    ):
        raise GovernedExpertRosterError(
            f"team_plan.work_items must contain {MINIMUM_TEAM_SIZE}-{MAXIMUM_TEAM_SIZE} items"
        )

    work_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            raise GovernedExpertRosterError(
                f"team_plan.work_items[{index}] must be an object"
            )
        expected = {
            "work_id",
            "objective",
            "role",
            "dependencies",
            "required_outputs",
        }
        if set(raw) != expected:
            raise GovernedExpertRosterError(
                f"team_plan.work_items[{index}] has missing or extra fields"
            )
        work_id = _bounded_text(raw.get("work_id"), f"work_items[{index}].work_id", 64)
        if not WORK_ID_RE.fullmatch(work_id):
            raise GovernedExpertRosterError(
                f"work_items[{index}].work_id is not a safe identifier"
            )
        if work_id in seen:
            raise GovernedExpertRosterError(f"duplicate work_id: {work_id}")
        seen.add(work_id)
        role = _bounded_text(raw.get("role"), f"work_items[{index}].role", 64)
        if not ROLE_RE.fullmatch(role):
            raise GovernedExpertRosterError(
                f"work_items[{index}].role is not a safe identifier"
            )
        dependencies = _bounded_string_list(
            raw.get("dependencies"),
            f"work_items[{index}].dependencies",
            maximum_items=MAXIMUM_TEAM_SIZE,
            maximum_characters=64,
        )
        required_outputs = _bounded_string_list(
            raw.get("required_outputs"),
            f"work_items[{index}].required_outputs",
            maximum_items=16,
            maximum_characters=240,
        )
        work_items.append(
            {
                "work_id": work_id,
                "objective": _bounded_text(
                    raw.get("objective"),
                    f"work_items[{index}].objective",
                    2_000,
                ),
                "role": role,
                "dependencies": dependencies,
                "required_outputs": required_outputs,
            }
        )

    known = {row["work_id"] for row in work_items}
    for row in work_items:
        unknown = sorted(set(row["dependencies"]) - known)
        if unknown:
            raise GovernedExpertRosterError(
                f"work {row['work_id']} references unknown dependencies: {unknown}"
            )
        if row["work_id"] in row["dependencies"]:
            raise GovernedExpertRosterError(
                f"work {row['work_id']} cannot depend on itself"
            )

    final_work_id = _bounded_text(
        team_plan.get("final_work_id"),
        "team_plan.final_work_id",
        64,
    )
    if final_work_id not in known:
        raise GovernedExpertRosterError("team_plan.final_work_id is unknown")

    dependencies_by_id = {
        row["work_id"]: tuple(row["dependencies"]) for row in work_items
    }
    state: dict[str, int] = {}

    def visit(work_id: str) -> None:
        mark = state.get(work_id, 0)
        if mark == 1:
            raise GovernedExpertRosterError("team_plan contains a dependency cycle")
        if mark == 2:
            return
        state[work_id] = 1
        for dependency in dependencies_by_id[work_id]:
            visit(dependency)
        state[work_id] = 2

    for work_id in sorted(known):
        visit(work_id)

    reverse: dict[str, set[str]] = {work_id: set() for work_id in known}
    for work_id, dependencies in dependencies_by_id.items():
        for dependency in dependencies:
            reverse[dependency].add(work_id)

    reachable_to_final: set[str] = {final_work_id}
    changed = True
    while changed:
        changed = False
        for work_id, targets in reverse.items():
            if work_id in reachable_to_final:
                continue
            if any(target in reachable_to_final for target in targets):
                reachable_to_final.add(work_id)
                changed = True
    missing_from_final = sorted(known - reachable_to_final)
    if missing_from_final:
        raise GovernedExpertRosterError(
            "all work items must feed the final work item; disconnected work: "
            + str(missing_from_final)
        )

    final_row = next(row for row in work_items if row["work_id"] == final_work_id)
    if not final_row["dependencies"]:
        raise GovernedExpertRosterError(
            "final work item must depend on at least one earlier work item"
        )
    return work_items, final_work_id


def _positive_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GovernedExpertRosterError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise GovernedExpertRosterError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _cost_profile(team_plan: Mapping[str, Any]) -> tuple[int, int]:
    prompt = team_plan.get(
        "expected_prompt_tokens_per_call",
        DEFAULT_EXPECTED_PROMPT_TOKENS,
    )
    completion = team_plan.get(
        "expected_completion_tokens_per_call",
        DEFAULT_EXPECTED_COMPLETION_TOKENS,
    )
    return (
        _positive_int(
            prompt,
            "team_plan.expected_prompt_tokens_per_call",
            minimum=1,
            maximum=2_000_000,
        ),
        _positive_int(
            completion,
            "team_plan.expected_completion_tokens_per_call",
            minimum=1,
            maximum=500_000,
        ),
    )


def _budget(ticket: Mapping[str, Any], team_size: int) -> tuple[int, int]:
    budget = ticket.get("approved_budget")
    if not isinstance(budget, Mapping):
        raise GovernedExpertRosterError("approved_budget is required")
    recovery = _positive_int(
        budget.get("maximum_recovery_calls"),
        "approved_budget.maximum_recovery_calls",
        minimum=0,
        maximum=MAXIMUM_RECOVERY_MEMBERS,
    )
    calls = _positive_int(
        budget.get("calls"),
        "approved_budget.calls",
        minimum=MINIMUM_TEAM_SIZE,
        maximum=MAXIMUM_TEAM_SIZE + MAXIMUM_RECOVERY_MEMBERS,
    )
    required_calls = team_size + recovery
    if calls != required_calls:
        raise GovernedExpertRosterError(
            "approved_budget.calls must equal work item count plus recovery reserve "
            f"({team_size}+{recovery}={required_calls})"
        )
    return calls, recovery


def _distinct_company_rows(
    ranked_rows: Sequence[Any],
    required_count: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    companies: set[str] = set()
    for raw in ranked_rows:
        if not isinstance(raw, Mapping):
            raise GovernedExpertRosterError("ranked flagship row is invalid")
        model_id = str(raw.get("model_id") or "").strip()
        company = str(raw.get("company") or "").strip().casefold()
        cost = raw.get("estimated_task_cost_usd")
        try:
            cost_value = float(cost)
        except (TypeError, ValueError) as exc:
            raise GovernedExpertRosterError(
                f"candidate {model_id or '<unknown>'} has invalid cost"
            ) from exc
        if not model_id or not company or not math.isfinite(cost_value) or cost_value < 0:
            raise GovernedExpertRosterError("ranked flagship row is incomplete")
        if company in companies:
            continue
        companies.add(company)
        row = dict(raw)
        row["company"] = company
        row["estimated_task_cost_usd"] = cost_value
        selected.append(row)
        if len(selected) == required_count:
            return selected
    raise GovernedExpertRosterError(
        f"only {len(selected)} distinct model companies are available; {required_count} required"
    )


def _member(
    row: Mapping[str, Any],
    *,
    member_id: str,
    roster_rank: int,
    kind: str,
    assigned_work_id: str | None,
    assigned_role: str | None,
) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "kind": kind,
        "roster_rank": roster_rank,
        "model_id": str(row["model_id"]),
        "company": str(row["company"]),
        "estimated_task_cost_usd": float(row["estimated_task_cost_usd"]),
        "prompt_usd_per_million": float(row.get("prompt_usd_per_million") or 0),
        "completion_usd_per_million": float(
            row.get("completion_usd_per_million") or 0
        ),
        "request_usd": row.get("request_usd"),
        "balanced_score": float(row.get("balanced_score") or 0),
        "intelligence_index": float(row.get("intelligence_index") or 0),
        "coding_index": float(row.get("coding_index") or 0),
        "agentic_index": float(row.get("agentic_index") or 0),
        "assigned_work_id": assigned_work_id,
        "assigned_role": assigned_role,
    }


def build_governed_expert_roster(
    ticket: Mapping[str, Any],
    cost_ranking: Mapping[str, Any],
    *,
    governance_commit_sha: str,
) -> dict[str, Any]:
    """Return an enriched expert ticket with a deterministic governed roster."""
    if not isinstance(ticket, Mapping):
        raise GovernedExpertRosterError("expert ticket must be an object")
    if ticket.get("route") != "expert-team":
        raise GovernedExpertRosterError("expert ticket route must be expert-team")
    if "governance_roster" in ticket:
        raise GovernedExpertRosterError(
            "incoming expert ticket must not supply governance_roster"
        )
    team_plan = ticket.get("team_plan")
    if not isinstance(team_plan, Mapping):
        raise GovernedExpertRosterError("team_plan is required")
    work_items, final_work_id = _work_items(team_plan)
    prompt_tokens, completion_tokens = _cost_profile(team_plan)
    calls, recovery_count = _budget(ticket, len(work_items))

    profile = cost_ranking.get("task_cost_profile")
    if not isinstance(profile, Mapping):
        raise GovernedExpertRosterError("cost ranking task profile is missing")
    if int(profile.get("expected_prompt_tokens") or -1) != prompt_tokens:
        raise GovernedExpertRosterError("cost ranking prompt profile mismatch")
    if int(profile.get("expected_completion_tokens") or -1) != completion_tokens:
        raise GovernedExpertRosterError("cost ranking completion profile mismatch")
    ranked_rows = cost_ranking.get("ranked_paid_flagship_candidates")
    if not isinstance(ranked_rows, list):
        raise GovernedExpertRosterError("cost ranking candidate list is missing")

    all_selected = _distinct_company_rows(
        ranked_rows,
        len(work_items) + recovery_count,
    )
    primary_rows = all_selected[: len(work_items)]
    recovery_rows = all_selected[len(work_items):]

    final_row = max(
        primary_rows,
        key=lambda row: (
            float(row.get("balanced_score") or 0),
            -float(row["estimated_task_cost_usd"]),
            str(row["model_id"]),
        ),
    )
    remaining_rows = [row for row in primary_rows if row is not final_row]
    remaining_rows.sort(
        key=lambda row: (
            float(row["estimated_task_cost_usd"]),
            str(row["model_id"]),
        )
    )
    non_final_work = [
        row for row in work_items if row["work_id"] != final_work_id
    ]
    assignment: dict[str, Mapping[str, Any]] = {
        final_work_id: final_row,
        **{
            work["work_id"]: model
            for work, model in zip(non_final_work, remaining_rows, strict=True)
        },
    }

    primary_members: list[dict[str, Any]] = []
    for rank, row in enumerate(primary_rows, 1):
        work_id = next(
            work_id
            for work_id, assigned in assignment.items()
            if assigned is row
        )
        work = next(item for item in work_items if item["work_id"] == work_id)
        primary_members.append(
            _member(
                row,
                member_id=f"primary-{rank}",
                roster_rank=rank,
                kind="primary",
                assigned_work_id=work_id,
                assigned_role=work["role"],
            )
        )

    recovery_members = [
        _member(
            row,
            member_id=f"recovery-{index}",
            roster_rank=len(primary_members) + index,
            kind="recovery",
            assigned_work_id=None,
            assigned_role="preapproved-recovery",
        )
        for index, row in enumerate(recovery_rows, 1)
    ]

    roster_core = {
        "schema_version": "governed-expert-roster-v1",
        "status": "GOVERNED_EXPERT_ROSTER_READY",
        "selection_policy": (
            "select the mathematically lowest-estimated-cost paid general-purpose "
            "flagships with a task-global all-different company constraint; reserve "
            "the next cheapest distinct companies; assign the strongest selected "
            "primary to final synthesis and the remaining primaries by ascending cost"
        ),
        "governance_repository": "a15280020511/decision-system-governance",
        "governance_commit_sha": governance_commit_sha,
        "source_selector_schema_version": cost_ranking.get(
            "source_selector_schema_version"
        ),
        "source_catalog_snapshot_sha256": cost_ranking.get(
            "source_catalog_snapshot_sha256"
        ),
        "task_cost_profile": {
            "expected_prompt_tokens_per_call": prompt_tokens,
            "expected_completion_tokens_per_call": completion_tokens,
        },
        "team_size": len(primary_members),
        "recovery_size": len(recovery_members),
        "approved_total_calls": calls,
        "final_work_id": final_work_id,
        "team_plan_sha256": _sha256(team_plan),
        "primary_members": primary_members,
        "recovery_members": recovery_members,
        "all_companies_unique": True,
        "model_calls_for_selection": 0,
        "selection_cost_usd": 0,
        "secret_values_exposed": False,
    }
    roster_core["roster_sha256"] = _sha256(roster_core)
    enriched = dict(ticket)
    enriched["governance_roster"] = roster_core
    return enriched


def enrich_expert_ticket_live(
    ticket: Mapping[str, Any],
    *,
    governance_commit_sha: str,
    token: str | None = None,
) -> dict[str, Any]:
    """Fetch the live catalog and return a governed expert ticket."""
    team_plan = ticket.get("team_plan")
    if not isinstance(team_plan, Mapping):
        raise GovernedExpertRosterError("team_plan is required")
    prompt_tokens, completion_tokens = _cost_profile(team_plan)
    api_key = (token or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise GovernedExpertRosterError("OPENROUTER_API_KEY is required")
    selector_receipt = select_flagships(api_key)
    ranking = rank_flagships_by_task_cost(
        selector_receipt,
        expected_prompt_tokens=prompt_tokens,
        expected_completion_tokens=completion_tokens,
    )
    return build_governed_expert_roster(
        ticket,
        ranking,
        governance_commit_sha=governance_commit_sha,
    )
