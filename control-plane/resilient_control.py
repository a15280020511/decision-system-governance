#!/usr/bin/env python3
"""Control-plane entrypoint with bounded resilient GitHub transport.

For expert routes this wrapper enriches the child ticket with an immutable
governance-owned model-selection plan before dispatch. A selection failure turns
the control ticket into a rejection; the expert center never receives a ticket
that could trigger local model selection.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent
COPILOT = REPOSITORY_ROOT / "governance-copilot"
if str(COPILOT) not in sys.path:
    sys.path.insert(0, str(COPILOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_resilient_control_runtime", ROOT / "control_plane.py")
HTTP = _load("governance_resilient_http_runtime", ROOT / "resilient_http.py")
RELIABILITY = _load(
    "governance_gpts_reliability_runtime", ROOT / "gpts_reliability.py"
)
EXPERT_SELECTOR = _load(
    "governance_expert_model_selector",
    COPILOT / "select_expert_team_models.py",
)
CONTROL._github_request = HTTP.github_request
RELIABILITY.patch(CONTROL)

_ORIGINAL_PREPARE = CONTROL.prepare


def _prepare_with_governance_selection(arguments) -> int:
    code = int(_ORIGINAL_PREPARE(arguments))
    root = Path(arguments.output_dir)
    status_path = root / "prepare-status.json"
    if code != 0 or not status_path.is_file():
        return code
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("accepted") is not True or status.get("route") != "expert":
        return code
    try:
        plan = EXPERT_SELECTOR.enrich_ticket(
            root / "child-ticket.json",
            token=os.getenv("OPENROUTER_API_KEY", ""),
            source_commit=os.getenv("GITHUB_SHA", ""),
            output_plan=root / "expert-model-selection.json",
        )
    except Exception as exc:  # noqa: BLE001
        status["accepted"] = False
        status["reason"] = (
            "governance expert-model selection failed closed: "
            f"{type(exc).__name__}: {exc}"
        )
        status["child_issue_title"] = ""
        status["child_command"] = ""
        status_path.write_text(
            json.dumps(
                status,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        CONTROL._write_output("accepted", "false")
        CONTROL._write_output("reason", status["reason"])
        CONTROL._write_output("child_issue_title", "")
        CONTROL._write_output("child_command", "")
        return 2

    status.update(
        {
            "expert_model_selection_status": plan["status"],
            "expert_model_selection_authority": plan[
                "selection_authority"
            ],
            "expert_model_selection_plan_sha256": plan["plan_sha256"],
            "expert_model_selection_model_calls": plan["model_calls"],
            "expert_center_local_selection_allowed": False,
        }
    )
    status_path.write_text(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


CONTROL.prepare = _prepare_with_governance_selection


def main() -> int:
    arguments = CONTROL.parser().parse_args()
    return arguments.func(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
