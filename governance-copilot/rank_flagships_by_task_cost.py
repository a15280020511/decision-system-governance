"""Rank already-qualified OpenRouter flagship candidates by expected task cost.

This module does not identify model capability tiers and does not call a model.
It consumes the deterministic flagship selector receipt, estimates the charge for
an explicit governance task profile, and selects the mathematically cheapest
candidate. The ranking is stable and fails closed on incomplete pricing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_EXPECTED_PROMPT_TOKENS = 10_000
DEFAULT_EXPECTED_COMPLETION_TOKENS = 2_000


class CostRankingError(RuntimeError):
    """Raised when a flagship receipt cannot produce a valid cost ranking."""


def _finite_nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CostRankingError(f"{field} is not numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise CostRankingError(f"{field} must be finite and nonnegative")
    return number


def _token_count(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise CostRankingError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CostRankingError(f"{field} must be an integer") from exc
    if number < 0:
        raise CostRankingError(f"{field} must be nonnegative")
    return number


def estimate_task_cost_usd(
    candidate: Mapping[str, Any],
    expected_prompt_tokens: int,
    expected_completion_tokens: int,
) -> float:
    """Estimate one request's charge from token rates and optional request fee."""
    prompt_tokens = _token_count(expected_prompt_tokens, "expected_prompt_tokens")
    completion_tokens = _token_count(
        expected_completion_tokens, "expected_completion_tokens"
    )
    if prompt_tokens == 0 and completion_tokens == 0:
        raise CostRankingError("task profile cannot contain zero total tokens")

    prompt_rate = _finite_nonnegative(
        candidate.get("prompt_usd_per_million"), "prompt_usd_per_million"
    )
    completion_rate = _finite_nonnegative(
        candidate.get("completion_usd_per_million"),
        "completion_usd_per_million",
    )
    request_raw = candidate.get("request_usd")
    request_fee = (
        0.0
        if request_raw in {None, ""}
        else _finite_nonnegative(request_raw, "request_usd")
    )
    return (
        prompt_rate * prompt_tokens / 1_000_000
        + completion_rate * completion_tokens / 1_000_000
        + request_fee
    )


def rank_flagships_by_task_cost(
    selector_receipt: Mapping[str, Any],
    *,
    expected_prompt_tokens: int = DEFAULT_EXPECTED_PROMPT_TOKENS,
    expected_completion_tokens: int = DEFAULT_EXPECTED_COMPLETION_TOKENS,
) -> dict[str, Any]:
    """Return a deterministic lowest-estimated-cost ranking."""
    prompt_tokens = _token_count(expected_prompt_tokens, "expected_prompt_tokens")
    completion_tokens = _token_count(
        expected_completion_tokens, "expected_completion_tokens"
    )
    if prompt_tokens == 0 and completion_tokens == 0:
        raise CostRankingError("task profile cannot contain zero total tokens")

    candidates_raw = selector_receipt.get("cheapest_paid_flagship_candidates")
    if not isinstance(candidates_raw, Sequence) or isinstance(
        candidates_raw, (str, bytes)
    ):
        raise CostRankingError("flagship candidate list is missing")

    ranked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in candidates_raw:
        if not isinstance(item, Mapping):
            raise CostRankingError("flagship candidate is not an object")
        model_id = item.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise CostRankingError("flagship candidate has no model_id")
        if model_id in seen_ids:
            raise CostRankingError(f"duplicate flagship candidate: {model_id}")
        seen_ids.add(model_id)
        row = dict(item)
        row["estimated_task_cost_usd"] = estimate_task_cost_usd(
            row,
            prompt_tokens,
            completion_tokens,
        )
        ranked.append(row)

    if not ranked:
        raise CostRankingError("no flagship candidates are available")

    ranked.sort(
        key=lambda row: (
            float(row["estimated_task_cost_usd"]),
            float(row["prompt_usd_per_million"]),
            float(row["completion_usd_per_million"]),
            -float(row.get("balanced_score") or 0),
            str(row["model_id"]),
        )
    )

    source_view = [
        {
            "model_id": row["model_id"],
            "prompt_usd_per_million": row["prompt_usd_per_million"],
            "completion_usd_per_million": row[
                "completion_usd_per_million"
            ],
            "request_usd": row.get("request_usd"),
            "balanced_score": row.get("balanced_score"),
        }
        for row in ranked
    ]
    source_sha256 = hashlib.sha256(
        json.dumps(source_view, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    return {
        "schema_version": "governance-openrouter-task-cost-ranking-v1",
        "status": "OPENROUTER_LOWEST_ESTIMATED_COST_FLAGSHIP_SELECTED",
        "selection_rule": (
            "identify paid general-purpose flagship models first; estimate each "
            "candidate's cost for the explicit governance task token profile; "
            "include any request fee; sort by estimated total USD and use "
            "deterministic price, capability, and model-id tie breakers"
        ),
        "task_cost_profile": {
            "expected_prompt_tokens": prompt_tokens,
            "expected_completion_tokens": completion_tokens,
        },
        "selected_model": ranked[0],
        "ranked_paid_flagship_candidates": ranked,
        "paid_flagship_count": len(ranked),
        "source_selector_schema_version": selector_receipt.get("schema_version"),
        "source_catalog_snapshot_sha256": source_sha256,
        "model_calls": 0,
        "estimated_model_cost_usd": 0,
        "secret_values_exposed": False,
    }


def write_receipts(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cost-selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected = result.get("selected_model")
    selected = selected if isinstance(selected, Mapping) else {}
    profile = result.get("task_cost_profile")
    profile = profile if isinstance(profile, Mapping) else {}
    lines = [
        "# OpenRouter 治理任务实际成本排序",
        "",
        f"- 状态：`{result.get('status')}`",
        f"- 预计输入 Token：`{profile.get('expected_prompt_tokens')}`",
        f"- 预计输出 Token：`{profile.get('expected_completion_tokens')}`",
        f"- 最低成本旗舰：`{selected.get('model_id')}`",
        f"- 预计单任务费用：`${float(selected.get('estimated_task_cost_usd', 0)):.8f}`",
        "- 模型调用：`0`",
        "- 排序费用：`$0`",
        "",
        "| 排名 | 模型 | 输入价/M | 输出价/M | 预计单任务费用 | 综合能力分 |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    rows = result.get("ranked_paid_flagship_candidates")
    if isinstance(rows, list):
        for index, row in enumerate(rows, 1):
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "| {rank} | `{model}` | ${prompt:.6g} | ${completion:.6g} | ${cost:.8f} | {score:.2f} |".format(
                    rank=index,
                    model=row.get("model_id"),
                    prompt=float(row.get("prompt_usd_per_million", 0)),
                    completion=float(row.get("completion_usd_per_million", 0)),
                    cost=float(row.get("estimated_task_cost_usd", 0)),
                    score=float(row.get("balanced_score", 0)),
                )
            )
    lines.append("")
    (output_dir / "cost-selection.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="openrouter-cost-selection")
    parser.add_argument(
        "--expected-prompt-tokens",
        type=int,
        default=int(
            os.environ.get(
                "GOVERNANCE_EXPECTED_PROMPT_TOKENS",
                DEFAULT_EXPECTED_PROMPT_TOKENS,
            )
        ),
    )
    parser.add_argument(
        "--expected-completion-tokens",
        type=int,
        default=int(
            os.environ.get(
                "GOVERNANCE_EXPECTED_COMPLETION_TOKENS",
                DEFAULT_EXPECTED_COMPLETION_TOKENS,
            )
        ),
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text("utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("selector receipt is not a JSON object")
    result = rank_flagships_by_task_cost(
        payload,
        expected_prompt_tokens=args.expected_prompt_tokens,
        expected_completion_tokens=args.expected_completion_tokens,
    )
    write_receipts(result, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
