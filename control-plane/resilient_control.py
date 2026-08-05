#!/usr/bin/env python3
"""Control-plane entrypoint with bounded transport and expert-roster signing."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_resilient_control_runtime", ROOT / "control_plane.py")
HTTP = _load("governance_resilient_http_runtime", ROOT / "resilient_http.py")
ROSTER = _load(
    "governance_expert_admission_runtime",
    ROOT / "governed_expert_admission.py",
)
CONTROL._github_request = HTTP.github_request


def _write_output(name: str, value: object) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    text = str(value).replace("\r", " ").replace("\n", " ")
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={text}\n")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_with_governed_roster(arguments) -> int:
    code = int(CONTROL.prepare(arguments))
    root = Path(arguments.output_dir)
    status_path = root / "prepare-status.json"
    if code or not status_path.exists():
        return code
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("accepted") is not True or status.get("route") != "expert":
        return code

    child_path = root / "child-ticket.json"
    try:
        ticket = json.loads(child_path.read_text(encoding="utf-8"))
        enriched = ROSTER.enrich_expert_ticket_live(
            ticket,
            governance_commit_sha=os.getenv("GITHUB_SHA", "").strip(),
        )
        roster = enriched["governance_roster"]
        _write_json(child_path, enriched)
        status.update(
            {
                "expert_roster_status": roster["status"],
                "expert_roster_sha256": roster["roster_sha256"],
                "expert_team_size": roster["team_size"],
                "expert_recovery_size": roster["recovery_size"],
                "expert_zdr_filter_required": roster["zdr_filter_required"],
                "expert_zdr_snapshot_sha256": roster["zdr_snapshot_sha256"],
                "expert_zdr_eligible_flagship_count": roster[
                    "zdr_eligible_flagship_count"
                ],
                "expert_selection_model_calls": 0,
                "expert_selection_cost_usd": 0,
            }
        )
        _write_json(status_path, status)
        for key in (
            "expert_roster_status",
            "expert_roster_sha256",
            "expert_team_size",
            "expert_recovery_size",
            "expert_zdr_filter_required",
            "expert_zdr_snapshot_sha256",
            "expert_zdr_eligible_flagship_count",
            "expert_selection_model_calls",
            "expert_selection_cost_usd",
        ):
            _write_output(key, status[key])
        return 0
    except Exception as exc:  # noqa: BLE001
        status.update(
            {
                "accepted": False,
                "reason": f"governed expert roster failed: {exc}",
                "expert_roster_status": "FAIL",
            }
        )
        _write_json(status_path, status)
        _write_output("accepted", "false")
        _write_output("reason", status["reason"])
        _write_output("expert_roster_status", "FAIL")
        return 2


def main() -> int:
    arguments = CONTROL.parser().parse_args()
    if arguments.command == "prepare":
        return _prepare_with_governed_roster(arguments)
    return arguments.func(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
