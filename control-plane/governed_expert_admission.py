"""Live governed expert admission with ZDR-executable model filtering.

This module performs only read-only OpenRouter catalog requests. It never calls a
model. It filters the governance flagship task-cost ranking to model identities
that currently have at least one ZDR endpoint, then delegates deterministic
company-unique roster construction to ``governed_expert_roster``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import governed_expert_roster as roster_core  # noqa: E402

ZDR_ENDPOINTS_API = "https://openrouter.ai/api/v1/endpoints/zdr"


class GovernedExpertAdmissionError(RuntimeError):
    """Fail-closed live admission error."""


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "decision-system-governed-expert-admission/1.0",
            "X-Title": "Decision System Governed Expert Admission",
        },
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise GovernedExpertAdmissionError("ZDR endpoint response is not an object")
            return payload
        except urllib.error.HTTPError as exc:
            last_error = GovernedExpertAdmissionError(
                f"OpenRouter ZDR endpoint request returned HTTP {exc.code}"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt == 0:
            time.sleep(2)
    raise GovernedExpertAdmissionError(
        f"OpenRouter ZDR endpoint request failed: {last_error}"
    )


def _zdr_model_ids(payload: Mapping[str, Any]) -> tuple[set[str], str]:
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise GovernedExpertAdmissionError("OpenRouter ZDR endpoint inventory is empty")
    normalized = [dict(row) for row in rows if isinstance(row, Mapping)]
    model_ids = {
        str(row.get("model_id") or "").strip()
        for row in normalized
        if str(row.get("model_id") or "").strip()
    }
    if not model_ids:
        raise GovernedExpertAdmissionError(
            "OpenRouter ZDR endpoint inventory contains no model identities"
        )
    snapshot = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return model_ids, snapshot


def _filter_ranking_to_zdr(
    ranking: Mapping[str, Any],
    model_ids: set[str],
    snapshot_sha256: str,
) -> dict[str, Any]:
    rows = ranking.get("ranked_paid_flagship_candidates")
    if not isinstance(rows, list):
        raise GovernedExpertAdmissionError("task-cost ranking candidate list is missing")
    eligible = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("model_id") or "").strip() in model_ids
    ]
    if not eligible:
        raise GovernedExpertAdmissionError(
            "no paid general-purpose flagship has a live ZDR endpoint"
        )
    result = dict(ranking)
    result["ranked_paid_flagship_candidates"] = eligible
    result["zdr_filter"] = {
        "required": True,
        "source": ZDR_ENDPOINTS_API,
        "source_snapshot_sha256": snapshot_sha256,
        "source_model_count": len(model_ids),
        "eligible_flagship_count": len(eligible),
        "model_calls": 0,
        "cost_usd": 0,
        "secret_values_exposed": False,
    }
    return result


def enrich_expert_ticket_live(
    ticket: Mapping[str, Any],
    *,
    governance_commit_sha: str,
    token: str | None = None,
) -> dict[str, Any]:
    team_plan = ticket.get("team_plan")
    if not isinstance(team_plan, Mapping):
        raise GovernedExpertAdmissionError("team_plan is required")
    prompt_tokens, completion_tokens = roster_core._cost_profile(team_plan)
    api_key = (token or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise GovernedExpertAdmissionError("OPENROUTER_API_KEY is required")
    selector_receipt = roster_core.select_flagships(api_key)
    ranking = roster_core.rank_flagships_by_task_cost(
        selector_receipt,
        expected_prompt_tokens=prompt_tokens,
        expected_completion_tokens=completion_tokens,
    )
    zdr_payload = _fetch_json(ZDR_ENDPOINTS_API, api_key)
    model_ids, snapshot = _zdr_model_ids(zdr_payload)
    executable_ranking = _filter_ranking_to_zdr(ranking, model_ids, snapshot)
    enriched = roster_core.build_governed_expert_roster(
        ticket,
        executable_ranking,
        governance_commit_sha=governance_commit_sha,
    )
    roster = enriched["governance_roster"]
    roster["zdr_filter_required"] = True
    roster["zdr_snapshot_sha256"] = snapshot
    roster["zdr_eligible_flagship_count"] = len(
        executable_ranking["ranked_paid_flagship_candidates"]
    )
    roster.pop("roster_sha256", None)
    roster["roster_sha256"] = roster_core._sha256(roster)
    return enriched


__all__ = [
    "GovernedExpertAdmissionError",
    "ZDR_ENDPOINTS_API",
    "enrich_expert_ticket_live",
]
