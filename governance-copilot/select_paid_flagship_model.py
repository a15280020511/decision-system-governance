"""Refine the live paid flagship set and choose its cheapest member.

This wrapper reuses the catalog/benchmark joiner, then removes singleton-company
false positives that have neither explicit flagship tier evidence nor sufficient
cross-model evidence. It performs no model inference.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping

BASE_PATH = Path(__file__).with_name("select_paid_high_level_model.py")


def _load_base():
    spec = importlib.util.spec_from_file_location("governance_flagship_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def refine(result: dict[str, Any]) -> dict[str, Any]:
    evidence = _mapping(result.get("company_flagship_evidence"))
    rows = result.get("cheapest_paid_flagship_candidates")
    if not isinstance(rows, list):
        raise RuntimeError("base selector did not return flagship candidates")

    refined: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        company = str(row.get("company") or "")
        company_row = _mapping(evidence.get(company))
        company_count = int(company_row.get("eligible_high_count") or 0)
        explicit = bool(row.get("explicit_flagship_tier"))
        text = f"{row.get('model_id', '')} {row.get('name', '')}".lower()

        reasons: list[str] = []
        if "spark" in text:
            reasons.append("speed-or-compact-product-tier")
        if company_count <= 1 and not explicit:
            reasons.append("singleton-company-without-explicit-flagship-evidence")

        if reasons:
            rejected.append(
                {
                    "model_id": row.get("model_id"),
                    "company": company,
                    "reasons": reasons,
                }
            )
            continue

        row["flagship_basis"] = (
            "explicit-product-tier"
            if explicit
            else "company-local-natural-top-layer"
        )
        refined.append(row)

    if not refined:
        raise RuntimeError("no flagship models remain after false-positive control")

    result = dict(result)
    result.update(
        {
            "schema_version": "governance-openrouter-paid-flagship-selection-test-v5",
            "status": "OPENROUTER_PAID_FLAGSHIP_SELECTION_REFINED",
            "selected_model": refined[0],
            "paid_flagship_count": len(refined),
            "cheapest_paid_flagship_candidates": refined,
            "flagship_false_positive_controls": {
                "singleton_company_requires_explicit_flagship_evidence": True,
                "speed_or_compact_product_tiers_rejected": ["spark"],
                "rejected_candidates": rejected,
            },
            "selection_rule": (
                "start from paid stable full-tier benchmarked models; exclude free, "
                "preview/beta/experimental and flash/mini/nano/micro/small/lite/fast "
                "tiers; identify company-local highest product layers; reject a "
                "singleton-company model unless OpenRouter product metadata explicitly "
                "identifies a flagship tier; preserve OpenRouter pricing-low-to-high "
                "order and choose the first remaining flagship"
            ),
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="openrouter-selection")
    args = parser.parse_args()
    token = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token:
        raise SystemExit("OPENROUTER_API_KEY is empty")

    base = _load_base()
    result = refine(base.select(token))
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
