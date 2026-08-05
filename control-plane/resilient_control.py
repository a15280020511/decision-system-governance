#!/usr/bin/env python3
"""Control-plane entrypoint with bounded resilient GitHub transport."""
from __future__ import annotations

import importlib.util
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
RELIABILITY = _load("governance_gpts_reliability_runtime", ROOT / "gpts_reliability.py")
CONTROL._github_request = HTTP.github_request
RELIABILITY.patch(CONTROL)


def main() -> int:
    arguments = CONTROL.parser().parse_args()
    return arguments.func(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
