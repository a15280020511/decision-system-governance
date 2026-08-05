"""Select the cheapest paid general-purpose flagship for governance assistance.

This final test wrapper retains the paid flagship logic, then removes models whose
product identity is explicitly domain-specialized rather than general governance.
It performs catalog reads only and makes no model inference call.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

FLAGSHIP_PATH = Path(__file__).with_name("select_paid_flagship_model.py")
SPECIALIZED_MARKERS = (
    "coder",
    "code-",
    "-code",
    "content-safety",
    "safety",
    "guard",
    "embedding",
    "embed",
    "rerank",
    "moderation",
)


def _load_flagship():
    spec = importlib.util.spec_from_file_location("governance_flagship", FLAGSHIP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load flagship selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def is_general_governance_model(row: Mapping[str, Any]) -> bool:
    text = " ".join(
        (
            str(row.get("model_id") or ""),
            str(row.get("name") or ""),
            str(row.get("canonical_slug") or ""),
        )
    ).lower()
    return not any(marker in text for marker in SPECIALIZED_MARKERS)


def finalize(result: Mapping[str, Any]) -> dict[str, Any]:
    raw = result.get("cheapest_paid_flagship_candidates")
    if not isinstance(raw, list):
        raise RuntimeError("flagship selector returned no candidate list")

    candidates = [
        dict(row)
        for row in raw
        if isinstance(row, Mapping) and is_general_governance_model(row)
    ]
    rejected = [
        {
            "model_id": str(row.get("model_id") or ""),
            "reason": "domain-specialized-not-general-governance",
        }
        for row in raw
        if isinstance(row, Mapping) and not is_general_governance_model(row)
    ]
    if not candidates:
        raise RuntimeError("no general-purpose paid flagship remains")

    final = dict(result)
    controls = dict(_mapping(final.get("flagship_false_positive_controls")))
    controls["domain_specialized_models_rejected"] = rejected
    controls["specialized_markers"] = list(SPECIALIZED_MARKERS)
    final.update(
        {
            "schema_version": "governance-openrouter-paid-governance-flagship-test-v7",
            "status": "OPENROUTER_PAID_GOVERNANCE_FLAGSHIP_SELECTED",
            "selected_model": candidates[0],
            "paid_flagship_count": len(candidates),
            "cheapest_paid_flagship_candidates": candidates,
            "flagship_false_positive_controls": controls,
            "selection_rule": (
                "identify paid stable benchmarked flagship products; exclude free, "
                "preview/beta/experimental, economy and domain-specialized models; "
                "preserve OpenRouter pricing-low-to-high order and select the first "
                "remaining general-purpose flagship"
            ),
            "model_calls": 0,
            "estimated_model_cost_usd": 0,
            "secret_values_exposed": False,
        }
    )
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="openrouter-selection")
    args = parser.parse_args()
    token = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token:
        raise SystemExit("OPENROUTER_API_KEY is empty")

    flagship = _load_flagship()
    base = flagship._load_base()
    result = finalize(flagship.refine(base.select(token)))
    output_dir = Path(args.output_dir)
    base.write_receipts(result, output_dir)
    (output_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
