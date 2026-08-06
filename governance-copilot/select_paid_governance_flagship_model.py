"""Select the first paid general-purpose flagship in OpenRouter price order.

The selector has two separated layers:
- ``select_from_catalog`` is a pure deterministic function for offline tests.
- ``select`` performs two read-only OpenRouter GET requests, then calls the pure core.

No model inference endpoint is used. The selector has no repository write capability.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

MODELS_API = "https://openrouter.ai/api/v1/models"
BENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"
REASONING_PARAMETER = "reasoning"

ECONOMY_TIER = re.compile(
    r"(?:^|[-_ /])(luna|flash|mini|nano|micro|small|lite|fast|instant|turbo|haiku|spark)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
UNSTABLE_TIER = re.compile(
    r"(?:^|[-_ /])(preview|experimental|beta)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
STRICT_FLAGSHIP_TIER = re.compile(
    r"(?:^|[-_ /])(pro|max|opus|ultra|premier)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
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
    "search",
)


class SelectorError(RuntimeError):
    """Raised when catalog data cannot produce a valid fail-closed selection."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price_per_million(pricing: Mapping[str, Any], key: str) -> float | None:
    value = _number(pricing.get(key))
    if value is None or value < 0:
        return None
    return value * 1_000_000


def _request_price(pricing: Mapping[str, Any]) -> float | None:
    value = _number(pricing.get("request"))
    return value if value is not None and value >= 0 else None


def _has_complete_paid_token_pricing(pricing: Mapping[str, Any]) -> bool:
    prompt = _number(pricing.get("prompt"))
    completion = _number(pricing.get("completion"))
    return (
        prompt is not None
        and completion is not None
        and prompt >= 0
        and completion >= 0
        and (prompt > 0 or completion > 0)
    )


def _is_general_text(row: Mapping[str, Any]) -> bool:
    architecture = _mapping(row.get("architecture"))
    inputs = architecture.get("input_modalities")
    outputs = architecture.get("output_modalities")
    return (
        isinstance(inputs, list)
        and "text" in inputs
        and isinstance(outputs, list)
        and outputs == ["text"]
    )


def _supports_reasoning(row: Mapping[str, Any]) -> bool:
    parameters = row.get("supported_parameters")
    if not isinstance(parameters, list):
        return False
    return REASONING_PARAMETER in {
        str(value or "").strip().casefold() for value in parameters
    }


def _not_expired(row: Mapping[str, Any]) -> bool:
    raw = row.get("expiration_date")
    if raw in {None, ""}:
        return True
    try:
        return date.fromisoformat(str(raw)[:10]) >= date.today()
    except ValueError:
        return False


def _identity_text(row: Mapping[str, Any], model_id: str, canonical: str) -> str:
    return " ".join((model_id, canonical, str(row.get("name") or "")))


def _is_general_governance_identity(identity: str) -> bool:
    lowered = identity.lower()
    return not any(marker in lowered for marker in SPECIALIZED_MARKERS)


def _geometric_mean(scores: tuple[float, float, float]) -> float:
    if min(scores) <= 0:
        raise SelectorError("benchmark scores must be positive")
    return (scores[0] * scores[1] * scores[2]) ** (1 / 3)


def _natural_high(values: Sequence[float]) -> tuple[list[bool], float, float]:
    """Return a deterministic upper natural group without a fixed score cutoff."""
    if not values:
        raise SelectorError("natural grouping requires at least one value")
    if len(values) == 1:
        value = float(values[0])
        return [True], value, value

    normalized = [float(value) for value in values]
    low_center = min(normalized)
    high_center = max(normalized)
    if math.isclose(low_center, high_center, rel_tol=0, abs_tol=1e-12):
        return [True] * len(normalized), low_center, high_center

    assignments = [False] * len(normalized)
    for _ in range(100):
        next_assignments = [
            abs(value - high_center) <= abs(value - low_center)
            for value in normalized
        ]
        low_values = [
            value for value, is_high in zip(normalized, next_assignments) if not is_high
        ]
        high_values = [
            value for value, is_high in zip(normalized, next_assignments) if is_high
        ]
        if not low_values or not high_values:
            return [True] * len(normalized), min(normalized), max(normalized)
        next_low = statistics.fmean(low_values)
        next_high = statistics.fmean(high_values)
        stable = next_assignments == assignments and math.isclose(
            next_low, low_center, rel_tol=0, abs_tol=1e-12
        ) and math.isclose(next_high, high_center, rel_tol=0, abs_tol=1e-12)
        assignments = next_assignments
        low_center = next_low
        high_center = next_high
        if stable:
            break

    if low_center > high_center:
        assignments = [not value for value in assignments]
        low_center, high_center = high_center, low_center
    return assignments, low_center, high_center


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "decision-system-governance-flagship-selector/1.0",
            "X-Title": "Decision System Governance Flagship Selector",
        },
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise SelectorError(f"invalid JSON object from {url}")
            return payload
        except urllib.error.HTTPError as exc:
            last_error = SelectorError(f"HTTP {exc.code} from {url}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt == 0:
            time.sleep(2)
    raise SelectorError(f"request failed for {url}: {last_error}")


def _fetch_rows(url: str, token: str) -> list[Mapping[str, Any]]:
    payload = _fetch_json(url, token)
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise SelectorError(f"empty data array from {url}")
    return [row for row in rows if isinstance(row, Mapping)]


def select_from_catalog(
    models: Sequence[Mapping[str, Any]],
    benchmark_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Select from an already price-ordered model catalog."""
    benchmark_rows = benchmark_payload.get("data")
    if not isinstance(benchmark_rows, list) or not benchmark_rows:
        raise SelectorError("OpenRouter benchmark feed is empty")

    benchmark_by_slug: dict[str, dict[str, float]] = {}
    for row in benchmark_rows:
        if not isinstance(row, Mapping):
            continue
        slug = row.get("model_permaslug")
        intelligence = _number(row.get("intelligence_index"))
        coding = _number(row.get("coding_index"))
        agentic = _number(row.get("agentic_index"))
        if not isinstance(slug, str) or not slug.strip():
            continue
        if intelligence is None or coding is None or agentic is None:
            continue
        scores = (float(intelligence), float(coding), float(agentic))
        if min(scores) <= 0:
            continue
        benchmark_by_slug[slug.strip()] = {
            "intelligence_index": scores[0],
            "coding_index": scores[1],
            "agentic_index": scores[2],
            "balanced_score": _geometric_mean(scores),
        }

    eligible: list[dict[str, Any]] = []
    seen_model_ids: set[str] = set()
    for pricing_rank, row in enumerate(models, 1):
        model_id = row.get("id")
        canonical = row.get("canonical_slug") or model_id
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if not isinstance(canonical, str) or not canonical.strip():
            continue
        if model_id in seen_model_ids:
            continue
        seen_model_ids.add(model_id)

        pricing = _mapping(row.get("pricing"))
        if not _has_complete_paid_token_pricing(pricing):
            continue
        if (
            not _is_general_text(row)
            or not _not_expired(row)
            or not _supports_reasoning(row)
        ):
            continue

        identity = _identity_text(row, model_id, canonical)
        if UNSTABLE_TIER.search(identity) or ECONOMY_TIER.search(identity):
            continue

        benchmark = benchmark_by_slug.get(canonical) or benchmark_by_slug.get(model_id)
        if benchmark is None:
            continue

        eligible.append(
            {
                "model_id": model_id,
                "canonical_slug": canonical,
                "name": str(row.get("name") or model_id),
                "company": model_id.split("/", 1)[0],
                "pricing_rank": pricing_rank,
                "prompt_usd_per_million": _price_per_million(pricing, "prompt"),
                "completion_usd_per_million": _price_per_million(
                    pricing, "completion"
                ),
                "request_usd": _request_price(pricing),
                "strict_product_tier": bool(STRICT_FLAGSHIP_TIER.search(identity)),
                **benchmark,
            }
        )

    if len(eligible) < 2:
        raise SelectorError("fewer than two paid stable benchmarked full-tier models")

    global_assignments, global_regular_center, global_high_center = _natural_high(
        [float(row["balanced_score"]) for row in eligible]
    )
    globally_high = [
        row for row, is_high in zip(eligible, global_assignments) if is_high
    ]
    if not globally_high:
        raise SelectorError("no globally high paid models identified")

    eligible_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        eligible_by_company[str(row["company"])].append(row)

    high_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    globally_high_ids = {str(row["model_id"]) for row in globally_high}
    for row in globally_high:
        high_by_company[str(row["company"])].append(row)

    flagship_ids: set[str] = set()
    company_evidence: dict[str, Any] = {}
    for company, high_rows in high_by_company.items():
        company_rows = eligible_by_company[company]
        strict = [row for row in high_rows if row["strict_product_tier"]]
        if len(company_rows) == 1:
            chosen = strict
            company_evidence[company] = {
                "eligible_count": 1,
                "eligible_high_count": len(high_rows),
                "method": "singleton-requires-strict-product-tier",
            }
        else:
            assignments, lower_center, flagship_center = _natural_high(
                [float(row["balanced_score"]) for row in company_rows]
            )
            natural_top = [
                row
                for row, is_high in zip(company_rows, assignments)
                if is_high and str(row["model_id"]) in globally_high_ids
            ]
            chosen_by_id = {
                str(row["model_id"]): row for row in natural_top + strict
            }
            chosen = list(chosen_by_id.values())
            company_evidence[company] = {
                "eligible_count": len(company_rows),
                "eligible_high_count": len(high_rows),
                "lower_center": lower_center,
                "flagship_center": flagship_center,
                "method": "company-natural-top-plus-strict-product-tier",
            }
        for row in chosen:
            flagship_ids.add(str(row["model_id"]))

    pre_specialization_flagships = [
        row for row in eligible if row["model_id"] in flagship_ids
    ]
    candidates: list[dict[str, Any]] = []
    specialized_rejected: list[dict[str, str]] = []
    for row in pre_specialization_flagships:
        identity = " ".join(
            (
                str(row.get("model_id") or ""),
                str(row.get("canonical_slug") or ""),
                str(row.get("name") or ""),
            )
        )
        if not _is_general_governance_identity(identity):
            specialized_rejected.append(
                {
                    "model_id": str(row["model_id"]),
                    "reason": "domain-specialized-not-general-governance",
                }
            )
            continue
        row = dict(row)
        row["flagship_basis"] = (
            "strict-product-tier"
            if row["strict_product_tier"]
            else "company-local-natural-top-layer"
        )
        candidates.append(row)

    if not candidates:
        raise SelectorError("no general-purpose paid flagship remains")

    selected = candidates[0]
    benchmark_meta = benchmark_payload.get("meta")
    return {
        "schema_version": "governance-openrouter-paid-governance-flagship-v1",
        "status": "OPENROUTER_PAID_GOVERNANCE_FLAGSHIP_SELECTED",
        "selection_rule": (
            "use the OpenRouter pricing-low-to-high catalog order; require native "
            "reasoning support; exclude free or incomplete pricing, non-text, expired, "
            "preview/beta/experimental, economy and domain-specialized models; require "
            "complete intelligence/coding/agentic benchmarks; retain strict flagship "
            "product tiers or each multi-model company's natural highest layer; select "
            "the first remaining candidate"
        ),
        "selected_model": selected,
        "paid_stable_full_tier_benchmarked_count": len(eligible),
        "globally_high_count": len(globally_high),
        "paid_flagship_count": len(candidates),
        "global_regular_center": global_regular_center,
        "global_high_center": global_high_center,
        "cheapest_paid_flagship_candidates": candidates,
        "company_flagship_evidence": company_evidence,
        "flagship_false_positive_controls": {
            "strict_product_name_tiers": ["pro", "max", "opus", "ultra", "premier"],
            "singleton_company_requires_strict_product_tier": True,
            "generic_marketing_descriptions_do_not_define_flagship": True,
            "specialized_markers": list(SPECIALIZED_MARKERS),
            "domain_specialized_models_rejected": specialized_rejected,
            "native_reasoning_required": True,
            "economy_tiers_include_luna": True,
        },
        "models_catalog_count": len(models),
        "benchmark_catalog_count": len(benchmark_by_slug),
        "benchmark_meta": benchmark_meta if isinstance(benchmark_meta, Mapping) else {},
        "catalog_requests": 2,
        "model_calls": 0,
        "estimated_model_cost_usd": 0,
        "secret_values_exposed": False,
    }


def select(token: str) -> dict[str, Any]:
    model_query = urllib.parse.urlencode(
        {
            "sort": "pricing-low-to-high",
            "output_modalities": "text",
            "supported_parameters": REASONING_PARAMETER,
        }
    )
    benchmark_query = urllib.parse.urlencode({"source": "artificial-analysis"})
    models = _fetch_rows(f"{MODELS_API}?{model_query}", token)
    benchmark_payload = _fetch_json(f"{BENCHMARKS_API}?{benchmark_query}", token)
    return select_from_catalog(models, benchmark_payload)


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):.6g}"


def write_receipts(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected = _mapping(result.get("selected_model"))
    lines = [
        "# OpenRouter 付费通用旗舰模型筛选",
        "",
        f"- 状态：`{result.get('status')}`",
        "- 价格规则：保持 OpenRouter `pricing-low-to-high` 官方目录顺序",
        "- 排除：免费、不完整价格、过期、非纯文本、预览、经济层和领域专用模型",
        "- 旗舰规则：正式产品层级，或多模型公司实时能力分布中的自然最高层",
        f"- 最终第 1 名：`{selected.get('model_id')}`",
        f"- 输入价/M：`{_money(selected.get('prompt_usd_per_million'))}`",
        f"- 输出价/M：`{_money(selected.get('completion_usd_per_million'))}`",
        f"- Intelligence：`{selected.get('intelligence_index')}`",
        f"- Coding：`{selected.get('coding_index')}`",
        f"- Agentic：`{selected.get('agentic_index')}`",
        f"- 通用旗舰候选数：`{result.get('paid_flagship_count')}`",
        "- 模型调用：`0`",
        "- 本次模型费用：`$0`",
        "",
        "## 价格从低到高的候选",
        "",
        "| 名次 | 模型 | 公司 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 旗舰依据 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    candidates = result.get("cheapest_paid_flagship_candidates")
    if isinstance(candidates, list):
        for index, item in enumerate(candidates, 1):
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| {index} | `{model}` | {company} | {prompt} | {completion} | {intel:.2f} | {coding:.2f} | {agentic:.2f} | {basis} |".format(
                    index=index,
                    model=item.get("model_id"),
                    company=item.get("company"),
                    prompt=_money(item.get("prompt_usd_per_million")),
                    completion=_money(item.get("completion_usd_per_million")),
                    intel=float(item.get("intelligence_index", 0)),
                    coding=float(item.get("coding_index", 0)),
                    agentic=float(item.get("agentic_index", 0)),
                    basis=item.get("flagship_basis"),
                )
            )
    lines.append("")
    (output_dir / "selection.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="openrouter-selection")
    args = parser.parse_args()
    token = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token:
        raise SystemExit("OPENROUTER_API_KEY is empty")
    result = select(token)
    output_dir = Path(args.output_dir)
    write_receipts(result, output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
