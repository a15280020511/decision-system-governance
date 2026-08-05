"""Select the cheapest paid flagship model from the live OpenRouter catalog.

The selector is read-only. It uses OpenRouter pricing plus its Artificial Analysis
benchmark feed, performs no inference call, and writes auditable receipts.
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
from typing import Any, Mapping

MODELS_API = "https://openrouter.ai/api/v1/models"
BENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"

ECONOMY_TIER = re.compile(
    r"(?:^|[-_ /])(flash|mini|nano|micro|small|lite|fast|instant|turbo|haiku)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
UNSTABLE_TIER = re.compile(
    r"(?:^|[-_ /])(preview|experimental|beta)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
FLAGSHIP_WORDS = re.compile(
    r"(?:^|[-_ /])(pro|max|opus|ultra|premier|flagship)(?:$|[-_ /0-9])",
    re.IGNORECASE,
)
FLAGSHIP_DESCRIPTION = re.compile(
    r"\b(flagship|most capable|frontier|top[- ]tier|state[- ]of[- ]the[- ]art)\b",
    re.IGNORECASE,
)


class SelectorError(RuntimeError):
    pass


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
    return None if value is None or value < 0 else value * 1_000_000


def _request_price(pricing: Mapping[str, Any]) -> float | None:
    value = _number(pricing.get("request"))
    return value if value is not None and value >= 0 else None


def _is_paid(pricing: Mapping[str, Any]) -> bool:
    keys = ("prompt", "completion", "request", "internal_reasoning", "image", "web_search")
    return any((_number(pricing.get(key)) or 0) > 0 for key in keys)


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


def _geometric_mean(scores: tuple[float, float, float]) -> float:
    if any(score <= 0 for score in scores):
        raise SelectorError("benchmark scores must be positive")
    return (scores[0] * scores[1] * scores[2]) ** (1 / 3)


def _two_cluster_high(values: list[float]) -> tuple[list[bool], float, float]:
    if len(values) < 2:
        raise SelectorError("at least two values are required for natural grouping")
    low_center, high_center = min(values), max(values)
    assignments = [False] * len(values)
    for _ in range(100):
        next_assignments = [
            abs(value - high_center) <= abs(value - low_center) for value in values
        ]
        low = [v for v, high in zip(values, next_assignments) if not high]
        high = [v for v, is_high in zip(values, next_assignments) if is_high]
        if not low or not high:
            raise SelectorError("score distribution cannot be split")
        next_low, next_high = statistics.fmean(low), statistics.fmean(high)
        stable = next_assignments == assignments and math.isclose(
            next_low, low_center, rel_tol=0, abs_tol=1e-12
        ) and math.isclose(next_high, high_center, rel_tol=0, abs_tol=1e-12)
        assignments, low_center, high_center = next_assignments, next_low, next_high
        if stable:
            break
    if low_center > high_center:
        assignments = [not item for item in assignments]
        low_center, high_center = high_center, low_center
    return assignments, low_center, high_center


def _tier_text(row: Mapping[str, Any], model_id: str, canonical: str) -> str:
    return " ".join(
        (model_id, canonical, str(row.get("name") or ""), str(row.get("description") or ""))
    )


def _money(value: Any) -> str:
    return "n/a" if value is None else f"${float(value):.6g}"


def select(token: str) -> dict[str, Any]:
    model_query = urllib.parse.urlencode(
        {"sort": "pricing-low-to-high", "output_modalities": "text"}
    )
    benchmark_query = urllib.parse.urlencode({"source": "artificial-analysis"})
    models = _fetch_rows(f"{MODELS_API}?{model_query}", token)
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
    for pricing_rank, row in enumerate(models, 1):
        model_id = row.get("id")
        canonical = row.get("canonical_slug") or model_id
        if not isinstance(model_id, str) or not isinstance(canonical, str):
            continue
        pricing = _mapping(row.get("pricing"))
        if not _is_paid(pricing) or not _is_general_text(row) or not _not_expired(row):
            continue
        text = _tier_text(row, model_id, canonical)
        if UNSTABLE_TIER.search(text) or ECONOMY_TIER.search(text):
            continue
        benchmark = benchmark_by_slug.get(canonical) or benchmark_by_slug.get(model_id)
        if benchmark is None:
            continue
        explicit_flagship = bool(FLAGSHIP_WORDS.search(text) or FLAGSHIP_DESCRIPTION.search(text))
        eligible.append(
            {
                "model_id": model_id,
                "canonical_slug": canonical,
                "name": str(row.get("name") or model_id),
                "company": model_id.split("/", 1)[0],
                "pricing_rank": pricing_rank,
                "prompt_usd_per_million": _price_per_million(pricing, "prompt"),
                "completion_usd_per_million": _price_per_million(pricing, "completion"),
                "request_usd": _request_price(pricing),
                "explicit_flagship_tier": explicit_flagship,
                **benchmark,
            }
        )

    if len(eligible) < 2:
        raise SelectorError("fewer than two eligible paid benchmarked models")

    global_assignments, global_regular_center, global_high_center = _two_cluster_high(
        [float(row["balanced_score"]) for row in eligible]
    )
    globally_high = [row for row, is_high in zip(eligible, global_assignments) if is_high]

    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in globally_high:
        by_company[str(row["company"])].append(row)

    flagship_ids: set[str] = set()
    company_evidence: dict[str, Any] = {}
    for company, rows in by_company.items():
        explicit = [row for row in rows if row["explicit_flagship_tier"]]
        if len(rows) == 1:
            chosen = explicit or rows
            company_evidence[company] = {
                "eligible_high_count": 1,
                "method": "single globally-high stable full-tier model",
            }
        else:
            assignments, lower_center, flagship_center = _two_cluster_high(
                [float(row["balanced_score"]) for row in rows]
            )
            natural_top = [row for row, high in zip(rows, assignments) if high]
            chosen_by_id = {row["model_id"]: row for row in natural_top + explicit}
            chosen = list(chosen_by_id.values())
            company_evidence[company] = {
                "eligible_high_count": len(rows),
                "lower_center": lower_center,
                "flagship_center": flagship_center,
                "method": "company-local natural top layer plus explicit flagship tier",
            }
        for row in chosen:
            flagship_ids.add(str(row["model_id"]))

    flagships = [row for row in eligible if row["model_id"] in flagship_ids]
    if not flagships:
        raise SelectorError("no paid flagship models identified")
    selected = flagships[0]

    return {
        "schema_version": "governance-openrouter-paid-flagship-selection-test-v4",
        "status": "OPENROUTER_PAID_FLAGSHIP_SELECTION_COMPLETED",
        "selection_rule": (
            "exclude free/non-text/expired/preview/beta/experimental and economy-tier "
            "flash/mini/nano/micro/small/lite/fast models; identify globally high models "
            "from the live intelligence-coding-agentic distribution; identify each "
            "company's natural highest product layer, augmented by explicit flagship "
            "tier wording; choose the first flagship in OpenRouter pricing-low-to-high order"
        ),
        "selected_model": selected,
        "paid_stable_full_tier_benchmarked_count": len(eligible),
        "globally_high_count": len(globally_high),
        "paid_flagship_count": len(flagships),
        "global_regular_center": global_regular_center,
        "global_high_center": global_high_center,
        "cheapest_paid_flagship_candidates": flagships[:40],
        "company_flagship_evidence": company_evidence,
        "models_catalog_count": len(models),
        "benchmark_catalog_count": len(benchmark_by_slug),
        "benchmark_meta": benchmark_payload.get("meta") if isinstance(benchmark_payload.get("meta"), Mapping) else {},
        "catalog_requests": 2,
        "model_calls": 0,
        "estimated_model_cost_usd": 0,
        "secret_values_exposed": False,
    }


def write_receipts(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected = _mapping(result["selected_model"])
    lines = [
        "# OpenRouter 付费旗舰治理模型筛选",
        "",
        f"- 状态：`{result['status']}`",
        "- 定义：排除免费、预览和 Flash/Mini/Nano/Small 等经济层；再识别每家公司实时能力分布中的最高产品层",
        "- 价格：在所有公司旗舰模型的合集中，沿 OpenRouter `pricing-low-to-high` 选择第一个",
        f"- 最终第 1 名：`{selected.get('model_id')}`",
        f"- 公司：`{selected.get('company')}`",
        f"- 输入价/M：`{_money(selected.get('prompt_usd_per_million'))}`",
        f"- 输出价/M：`{_money(selected.get('completion_usd_per_million'))}`",
        f"- Intelligence：`{selected.get('intelligence_index')}`",
        f"- Coding：`{selected.get('coding_index')}`",
        f"- Agentic：`{selected.get('agentic_index')}`",
        f"- 综合分：`{float(selected.get('balanced_score', 0)):.4f}`",
        f"- 付费稳定全尺寸可比较模型：`{result['paid_stable_full_tier_benchmarked_count']}`",
        f"- 全球高等级模型：`{result['globally_high_count']}`",
        f"- 最终旗舰模型：`{result['paid_flagship_count']}`",
        "- 模型调用：`0`",
        "- 本次模型费用：`$0`",
        "",
        "## 价格从低到高的付费旗舰模型",
        "",
        "| 名次 | 模型 | 公司 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 综合分 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    candidates = result.get("cheapest_paid_flagship_candidates")
    if isinstance(candidates, list):
        for index, item in enumerate(candidates, 1):
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
    write_receipts(result, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
