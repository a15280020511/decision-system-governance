#!/usr/bin/env python3
"""Read-only query and deterministic report views for the private justice dataset."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from huggingface_hub import HfApi, hf_hub_download

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("justice_gateway", HERE / "gateway.py")
GATEWAY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GATEWAY
SPEC.loader.exec_module(GATEWAY)
MAX_BATCH_FILES = 250
MAX_RESULTS = 100


class QueryError(RuntimeError):
    pass


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _token_repo() -> tuple[HfApi, str, str]:
    contract = GATEWAY.validate_contract()
    token = str(os.getenv("HF_TOKEN") or "").strip()
    if not token:
        raise QueryError("HF_TOKEN is not configured in governance")
    api = HfApi()
    repo_id = GATEWAY._repo_id(api, token, contract)
    info = api.repo_info(repo_id=repo_id, repo_type="dataset", token=token)
    if bool(getattr(info, "private", False)) is not True:
        raise QueryError("justice intelligence dataset must remain private")
    return api, token, repo_id


def _load_records(api: HfApi, token: str, repo_id: str) -> list[dict[str, Any]]:
    files = sorted(
        (path for path in api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token) if path.startswith("records/") and path.endswith(".jsonl")),
        reverse=True,
    )[:MAX_BATCH_FILES]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        local = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=path, token=token, force_download=True)
        for raw in Path(local).read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise QueryError(f"invalid dataset row in {path}")
            record_id = str(row.get("record_id") or "")
            if record_id and record_id not in seen:
                GATEWAY._validate_record(row, len(rows))
                seen.add(record_id)
                rows.append(row)
    return rows


def _date_value(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _contains(values: Any, target: str) -> bool:
    return isinstance(values, list) and any(target.casefold() in str(item).casefold() for item in values)


def filter_records(rows: list[dict[str, Any]], query: Mapping[str, Any]) -> list[dict[str, Any]]:
    allowed = {"days","institution_type","region","signal_type","subject_type","capability_id","technology_term","legal_domain","confidence","limit"}
    if set(query) - allowed:
        raise QueryError("query contains unsupported fields")
    days = int(query.get("days") or 365)
    if not 1 <= days <= 1095:
        raise QueryError("days must be 1..1095")
    limit = int(query.get("limit") or 50)
    if not 1 <= limit <= MAX_RESULTS:
        raise QueryError(f"limit must be 1..{MAX_RESULTS}")
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    result: list[dict[str, Any]] = []
    for row in rows:
        event_date = _date_value(row.get("event_date") or row.get("as_of_date"))
        if event_date and event_date < cutoff:
            continue
        if query.get("institution_type") and row.get("institution_type") != query["institution_type"]:
            continue
        if query.get("region") and str(query["region"]).casefold() not in str(row.get("region") or "").casefold():
            continue
        if query.get("signal_type") and row.get("signal_type") != query["signal_type"]:
            continue
        if query.get("subject_type") and row.get("subject_type") != query["subject_type"]:
            continue
        if query.get("confidence") and row.get("confidence") != query["confidence"]:
            continue
        if query.get("capability_id") and not _contains(row.get("capability_ids"), str(query["capability_id"])):
            continue
        if query.get("technology_term") and not _contains(row.get("technology_terms"), str(query["technology_term"])):
            continue
        if query.get("legal_domain") and not _contains(row.get("legal_domains"), str(query["legal_domain"])):
            continue
        result.append(row)
    result.sort(key=lambda row: (str(row.get("event_date") or row.get("as_of_date") or ""), str(row.get("record_id") or "")), reverse=True)
    return result[:limit]


def query(query_value: Mapping[str, Any], output: Path) -> dict[str, Any]:
    api, token, repo_id = _token_repo()
    all_rows = _load_records(api, token, repo_id)
    rows = filter_records(all_rows, query_value)
    result = {
        "schema_version": "governance-prc-justice-query-result-v1",
        "status": "HF_JUSTICE_QUERY_COMPLETED",
        "repository_private": True,
        "query": dict(query_value),
        "matched_record_count": len(rows),
        "records": rows,
        "raw_source_text_returned": False,
        "raw_source_url_returned": False,
        "raw_model_response_returned": False,
        "model_calls": 0,
    }
    _dump(output / "query-results.json", result)
    return result


def _top(counter: Counter[str], n: int = 12) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(n) if name]


def report(days: int, output: Path) -> dict[str, Any]:
    if days not in {7,30,90,180,365,1095}:
        raise QueryError("report days must be one of 7,30,90,180,365,1095")
    api, token, repo_id = _token_repo()
    all_rows = _load_records(api, token, repo_id)
    rows = filter_records(all_rows, {"days":days,"limit":MAX_RESULTS})
    institution = Counter(str(row.get("institution_type") or "") for row in rows)
    signals = Counter(str(row.get("signal_type") or "") for row in rows)
    subjects = Counter(str(row.get("subject_type") or "") for row in rows)
    lifecycle = Counter(str(row.get("lifecycle_stage") or "UNSPECIFIED") for row in rows)
    trends = Counter(str(row.get("trend_direction") or "INSUFFICIENT_DATA") for row in rows)
    confidence = Counter(str(row.get("confidence") or "") for row in rows)
    regions = Counter(str(row.get("region") or "UNSPECIFIED") for row in rows)
    capabilities: Counter[str] = Counter()
    technologies: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    for row in rows:
        capabilities.update(str(item) for item in row.get("capability_ids") or [])
        technologies.update(str(item) for item in row.get("technology_terms") or [])
        domains.update(str(item) for item in row.get("legal_domains") or [])
    notable = [row for row in rows if row.get("trend_direction") in {"NEW","RISING","CONTESTED"} or row.get("confidence") == "HIGH"][:20]
    practice = [row for row in rows if row.get("practice_standard_summary")][:20]
    doctrine = [row for row in rows if row.get("doctrine_or_enforcement_summary")][:20]
    build = [row for row in rows if row.get("signal_type") in {"education_and_training","research","standard","procurement_and_budget","talent_and_recruitment","infrastructure_and_deployment"}][:20]
    result = {
        "schema_version": "governance-prc-justice-report-v1",
        "status": "HF_JUSTICE_REPORT_COMPLETED",
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
        "window_days": days,
        "record_count": len(rows),
        "distribution": {
            "institution": _top(institution),
            "signal_type": _top(signals),
            "subject_type": _top(subjects),
            "lifecycle_stage": _top(lifecycle),
            "trend_direction": _top(trends),
            "confidence": _top(confidence),
            "region": _top(regions),
            "capability": _top(capabilities),
            "technology_term": _top(technologies),
            "legal_domain": _top(domains),
        },
        "notable_changes": notable,
        "practice_standard_changes": practice,
        "doctrine_and_enforcement_changes": doctrine,
        "capacity_building_leading_signals": build,
        "limitations": [
            "This view contains derived public/authorized intelligence only.",
            "Record counts are not equivalent to nationwide deployment or absolute capability.",
            "Absence of a public record does not prove absence of a capability.",
            "Cross-record model synthesis and deterministic compute indices remain separate governed analysis stages."
        ],
        "raw_source_text_returned": False,
        "raw_source_url_returned": False,
        "raw_model_response_returned": False,
        "model_calls": 0,
    }
    _dump(output / "report.json", result)
    lines = [
        f"# 中国大陆司法衍生情报报告（最近{days}天）",
        "",
        f"- 截止日期：{result['as_of_date']}",
        f"- 衍生记录：{len(rows)}",
        "- 数据：公开/授权来源经一手验证后，由Cloudflare固定Schema模型转换；本报告不含原始网页正文或URL。",
        "",
        "## 1. 机关分布",
    ]
    lines += [f"- {row['name']}: {row['count']}" for row in result["distribution"]["institution"]] or ["- 暂无足够记录"]
    lines += ["", "## 2. 技术/能力信号"]
    lines += [f"- {row['name']}: {row['count']}" for row in result["distribution"]["capability"]] or ["- 暂无足够记录"]
    lines += ["", "## 3. 技术术语"]
    lines += [f"- {row['name']}: {row['count']}" for row in result["distribution"]["technology_term"]] or ["- 暂无足够记录"]
    lines += ["", "## 4. 生命周期/趋势"]
    lines += [f"- {row['name']}: {row['count']}" for row in result["distribution"]["lifecycle_stage"]]
    lines += [f"- trend/{row['name']}: {row['count']}" for row in result["distribution"]["trend_direction"]]
    lines += ["", "## 5. 实践标准变化"]
    lines += [f"- {row.get('event_date') or row.get('as_of_date')} | {row.get('institution_type')} | {row.get('practice_standard_summary')}" for row in practice[:10]] or ["- 暂无足够记录"]
    lines += ["", "## 6. 法律理论与执行变化"]
    lines += [f"- {row.get('event_date') or row.get('as_of_date')} | {row.get('institution_type')} | {row.get('doctrine_or_enforcement_summary')}" for row in doctrine[:10]] or ["- 暂无足够记录"]
    lines += ["", "## 7. 能力建设领先信号"]
    lines += [f"- {row.get('event_date') or row.get('as_of_date')} | {row.get('signal_type')} | {row.get('summary')}" for row in build[:10]] or ["- 暂无足够记录"]
    lines += ["", "## 8. 重要变化/争议"]
    lines += [f"- {row.get('event_date') or row.get('as_of_date')} | {row.get('trend_direction')} | {row.get('summary')}" for row in notable[:10]] or ["- 暂无足够记录"]
    lines += ["", "## 9. 限制", "- 公开证据不等于全国部署；单一记录不作全国外推；无公开记录不证明能力不存在。", "- 更高阶跨案例语义综合与CES/PSS/TMS/DI/DSI/ESI由治理路由到专家/计算中心后另行生成。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["query","report"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--query-json")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "query":
            if not args.query_json:
                raise QueryError("--query-json is required")
            value = json.loads(args.query_json)
            if not isinstance(value, Mapping):
                raise QueryError("query JSON must be an object")
            result = query(value, output)
        else:
            result = report(args.days, output)
        print(json.dumps({"status":result["status"],"record_count":result.get("record_count",result.get("matched_record_count",0)),"model_calls":0}, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
