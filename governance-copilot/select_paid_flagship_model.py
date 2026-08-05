"""Refine the live paid flagship set and choose its cheapest member.

The selector performs no inference. It rejects economy tiers and distinguishes
an actual flagship product tier from generic capability marketing language.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

BASE_PATH = Path(__file__).with_name("select_paid_high_level_model.py")
STRICT_FLAGSHIP_NAME = re.compile(
    r"(?:^|[-_ /])(pro|max|opus|ultra|premier)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)


def _load_base():
    spec = importlib.util.spec_from_file_location("governance_flagship_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _two_cluster_top(rows: list[dict[str, Any]]) -> set[str]:
    if len(rows) < 2:
        return set()
    values = [float(row.get("balanced_score") or 0) for row in rows]
    low_center, high_center = min(values), max(values)
    assignments = [False] * len(values)
    for _ in range(100):
        nxt = [abs(v - high_center) <= abs(v - low_center) for v in values]
        low = [v for v, high in zip(values, nxt) if not high]
        high = [v for v, is_high in zip(values, nxt) if is_high]
        if not low or not high:
            return {str(rows[values.index(max(values))].get("model_id"))}
        next_low, next_high = statistics.fmean(low), statistics.fmean(high)
        stable = nxt == assignments and math.isclose(
            next_low, low_center, rel_tol=0, abs_tol=1e-12
        ) and math.isclose(next_high, high_center, rel_tol=0, abs_tol=1e-12)
        assignments, low_center, high_center = nxt, next_low, next_high
        if stable:
            break
    return {
        str(row.get("model_id"))
        for row, is_top in zip(rows, assignments)
        if is_top
    }


def refine(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("cheapest_paid_flagship_candidates")
    if not isinstance(rows, list):
        raise RuntimeError("base selector did not return flagship candidates")

    candidates = [dict(row) for row in rows if isinstance(row, Mapping)]
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_company[str(row.get("company") or "")].append(row)

    natural_top_ids: set[str] = set()
    for company_rows in by_company.values():
        natural_top_ids.update(_two_cluster_top(company_rows))

    refined: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in candidates:
        model_id = str(row.get("model_id") or "")
        name = str(row.get("name") or "")
        company = str(row.get("company") or "")
        company_count = len(by_company[company])
        strict_product_tier = bool(STRICT_FLAGSHIP_NAME.search(f"{model_id} {name}"))
        company_natural_top = model_id in natural_top_ids
        text = f"{model_id} {name}".lower()

        reasons: list[str] = []
        if "spark" in text:
            reasons.append("speed-or-compact-product-tier")
        if company_count <= 1 and not strict_product_tier:
            reasons.append("singleton-company-without-strict-product-tier")
        elif company_count > 1 and not (strict_product_tier or company_natural_top):
            reasons.append("not-company-flagship-product-tier-or-natural-top")

        if reasons:
            rejected.append({"model_id": model_id, "company": company, "reasons": reasons})
            continue

        row["strict_product_tier"] = strict_product_tier
        row["company_natural_top"] = company_natural_top
        row["flagship_basis"] = (
            "strict-product-tier"
            if strict_product_tier
            else "company-local-natural-top-layer"
        )
        refined.append(row)

    if not refined:
        raise RuntimeError("no flagship models remain after strict product-tier control")

    result = dict(result)
    result.update(
        {
            "schema_version": "governance-openrouter-paid-flagship-selection-test-v6",
            "status": "OPENROUTER_PAID_FLAGSHIP_SELECTION_STRICT",
            "selected_model": refined[0],
            "paid_flagship_count": len(refined),
            "cheapest_paid_flagship_candidates": refined,
            "flagship_false_positive_controls": {
                "strict_product_name_tiers": ["pro", "max", "opus", "ultra", "premier"],
                "generic_capability_phrases_do_not_define_flagship": True,
                "singleton_company_requires_strict_product_tier": True,
                "rejected_candidates": rejected,
            },
            "selection_rule": (
                "start from paid stable benchmarked full-tier models; exclude free, "
                "preview/beta/experimental and economy tiers; treat Pro/Max/Opus/Ultra/"
                "Premier product names as strict flagship evidence; otherwise require "
                "membership in the company's natural highest capability layer; generic "
                "phrases such as frontier, top-tier, state-of-the-art or Pro-level do not "
                "by themselves define a flagship; preserve OpenRouter pricing-low-to-high "
                "order and choose the first remaining model"
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
