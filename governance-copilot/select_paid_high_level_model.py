"""Select the cheapest paid model from the data-derived high-level tier.

The selector is read-only: it fetches the OpenRouter model catalog and official
Artificial Analysis benchmark feed, performs no model inference, and writes a
JSON/Markdown receipt.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Mapping

MODELS_API = "https://openrouter.ai/api/v1/models"
BENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"


class SelectorError(RuntimeError):
    """Raised when the live catalog cannot produce a valid selection."""


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


def _is_paid(pricing: Mapping[str, Any]) -> bool:
    billable = (
        "prompt",
        "completion",
        "request",
        "internal_reasoning",
        "image",
        "web_search",
    )
    values = [_number(pricing.get(key)) for key in billable]
    return any(value is not None and value > 0 for value in values)


def _is_text_governance_model(row: Mapping[str, Any]) -> bool:
    architecture = _mapping(row.get("architecture"))
    inputs = architecture.get("input_modalities")
    outputs = architecture.get("output_modalities")
    if not isinstance(inputs, list) or "text" not in inputs:
        return False
    if not isinstance(outputs, list) or outputs != ["text"]:
        return False
    return True


def _not_expired(row: Mapping[str, Any]) -> bool:
    raw = row.get("expiration_date")
    if raw in {None, ""}:
        return True
    try:
        return date.fromisoformat(str(raw)[:10]) >= date.today()
    except ValueError:
        return False


def _fetch_json(url: str, token: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "decision-system-governance-paid-selector/1.0",
            "X-Title": "Decision System Governance Paid Selector",
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


def _geometric_mean(scores: tuple[float, float, float]) -> float:
    if any(score <= 0 for score in scores):
        raise SelectorError("benchmark scores must be positive")
    return (scores[0] * scores[1] * scores[2]) ** (1 / 3)


def _two_cluster_high_tier(values: list[float]) -> tuple[list[bool], float, float]:
    """Split one-dimensional scores into natural low/high groups.

    This is deterministic 2-means clustering initialized at the observed minimum
    and maximum. It creates a data-derived boundary instead of a fixed benchmark
    cutoff, context requirement, parameter count, or model-name rule.
    """
    if len(values) < 2:
        raise SelectorError("at least two paid benchmarked models are required")
    low_center = min(values)
    high_center = max(values)
    assignments = [False] * len(values)
    for _ in range(100):
        next_assignments = [
            abs(value - high_center) <= abs(value - low_center)
            for value in values
        ]
        low_values = [
            value for value, is_high in zip(values, next_assignments) if not is_high
        ]
        high_values = [
            value for value, is_high in zip(values, next_assignments) if is_high
        ]
        if not low_values or not high_values:
            raise SelectorError("benchmark distribution cannot be split into two tiers")
        next_low = statistics.fmean(low_values)
        next_high = statistics.fmean(high_values)
        if next_assignments == assignments and math.isclose(
            next_low, low_center, rel_tol=0, abs_tol=1e-12
        ) and math.isclose(next_high, high_center, rel_tol=0, abs_tol=1e-12):
            assignments = next_assignments
            low_center = next_low
            high_center = next_high
            break
        assignments = next_assignments
        low_center = next_low
        high_center = next_high
    if low_center > high_center:
        assignments = [not value for value in assignments]
        low_center, high_center = high_center, low_center
    return assignments, low_center, high_center


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):.6g}"


def select(token: str) -> dict[str, Any]:
    models_query = urllib.parse.urlencode(
        {"sort": "pricing-low-to-high", "output_modalities": "text"}
    )
    benchmark_query = urllib.parse.urlencode(
        {"source": "artificial-analysis"}
    )
    models = _fetch_rows(f"{MODELS_API}?{models_query}", token)
    benchmark_payload = _fetch_json(f"{BENCHMARKS_API}?{benchmark_query}", token)
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
        if min(intelligence, coding, agentic) <= 0:
            continue
        benchmark_by_slug[slug.strip()] = {
            "intelligence_index": intelligence,
            "coding_index": coding,
            "agentic_index": agentic,
            "balanced_score": _geometric_mean((intelligence, coding, agentic)),
        }

    joined: list[dict[str, Any]] = []
    for pricing_rank, row in enumerate(models, 1):
        model_id = row.get("id")
        canonical = row.get("canonical_slug") or model_id
        if not isinstance(model_id, str) or not isinstance(canonical, str):
            continue
        pricing = _mapping(row.get("pricing"))
        if not _is_paid(pricing):
            continue
        if not _is_text_governance_model(row) or not _not_expired(row):
            continue
        benchmark = benchmark_by_slug.get(canonical) or benchmark_by_slug.get(model_id)
        if benchmark is None:
            continue
        joined.append(
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
                **benchmark,
            }
        )

    if len(joined) < 2:
        raise SelectorError("fewer than two paid general-text benchmarked models")

    assignments, low_center, high_center = _two_cluster_high_tier(
        [float(row["balanced_score"]) for row in joined]
    )
    high_level = [
        row for row, is_high in zip(joined, assignments) if is_high
    ]
    if not high_level:
        raise SelectorError("no high-level paid models identified")

    # `joined` already follows OpenRouter's official pricing-low-to-high order.
    selected = high_level[0]
    benchmark_meta = benchmark_payload.get("meta")
    result = {
        "schema_version": "governance-openrouter-paid-selection-test-v2",
        "status": "OPENROUTER_PAID_HIGH_LEVEL_SELECTION_COMPLETED",
        "selection_rule": (
            "exclude free/non-text/expired/unbenchmarked models; form a balanced "
            "intelligence-coding-agentic score; split the paid benchmark distribution "
            "into natural high/regular tiers with deterministic two-cluster grouping; "
            "choose the first high-tier model in OpenRouter pricing-low-to-high order"
        ),
        "high_level_definition": (
            "upper natural cluster of the geometric mean of OpenRouter Artificial "
            "Analysis intelligence, coding and agentic indexes"
        ),
        "selected_model": selected,
        "paid_general_text_benchmarked_count": len(joined),
        "paid_high_level_count": len(high_level),
        "regular_tier_center": low_center,
        "high_tier_center": high_center,
        "cheapest_paid_high_level_candidates": high_level[:30],
        "models_catalog_count": len(models),
        "benchmark_catalog_count": len(benchmark_by_slug),
        "benchmark_meta": benchmark_meta if isinstance(benchmark_meta, Mapping) else {},
        "catalog_requests": 2,
        "model_calls": 0,
        "estimated_model_cost_usd": 0,
        "secret_values_exposed": False,
    }
    return result


def write_receipts(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected = _mapping(result["selected_model"])
    lines = [
        "# OpenRouter 付费高等级治理模型筛选",
        "",
        f"- 状态：`{result['status']}`",
        "- 付费规则：至少一个 OpenRouter 计费字段大于 0",
        "- 高等级规则：intelligence、coding、agentic 三项成绩的几何平均值，经数据分布自动分为高等级组和常规组",
        "- 价格规则：只在高等级付费组内，沿 OpenRouter `pricing-low-to-high` 顺序选择最便宜者",
        f"- 最终选中：`{selected.get('model_id')}`",
        f"- 公司：`{selected.get('company')}`",
        f"- 输入价/M：`{_money(selected.get('prompt_usd_per_million'))}`",
        f"- 输出价/M：`{_money(selected.get('completion_usd_per_million'))}`",
        f"- Intelligence：`{selected.get('intelligence_index')}`",
        f"- Coding：`{selected.get('coding_index')}`",
        f"- Agentic：`{selected.get('agentic_index')}`",
        f"- 综合等级分：`{float(selected.get('balanced_score', 0)):.4f}`",
        f"- 付费且可比较模型数：`{result['paid_general_text_benchmarked_count']}`",
        f"- 高等级付费模型数：`{result['paid_high_level_count']}`",
        "- 模型调用：`0`",
        "- 本次模型费用：`$0`",
        "",
        "## 价格最低的付费高等级候选",
        "",
        "| 顺序 | 模型 | 公司 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 综合分 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    candidates = result.get("cheapest_paid_high_level_candidates")
    if isinstance(candidates, list):
        for index, item in enumerate(candidates[:20], 1):
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| {index} | `{model}` | {company} | {prompt} | {completion} | {intel:.2f} | {coding:.2f} | {agentic:.2f} | {balanced:.2f} |".format(
                    index=index,
                    model=item.get("model_id"),
                    company=item.get("company"),
                    prompt=_money(item.get("prompt_usd_per_million")),
                    completion=_money(item.get("completion_usd_per_million")),
                    intel=float(item.get("intelligence_index", 0)),
                    coding=float(item.get("coding_index", 0)),
                    agentic=float(item.get("agentic_index", 0)),
                    balanced=float(item.get("balanced_score", 0)),
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
