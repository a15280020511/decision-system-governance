from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact match, found {count}")
    return text.replace(old, new)


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, found {count}")
    return updated


# 1. Governance-wide flagship selector: require reasoning and reject Luna/search.
path = Path("governance-copilot/select_paid_governance_flagship_model.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    r"(?:^|[-_ /])(flash|mini|nano|micro|small|lite|fast|instant|turbo|haiku|spark)(?:$|[-_ /0-9])",',
    '    r"(?:^|[-_ /])(luna|flash|mini|nano|micro|small|lite|fast|instant|turbo|haiku|spark)(?:$|[-_ /0-9])",',
    "governance Luna economy exclusion",
)
text = replace_once(
    text,
    '    "moderation",\n)',
    '    "moderation",\n    "search",\n)',
    "governance search specialization exclusion",
)
text = replace_once(
    text,
    'MODELS_API = "https://openrouter.ai/api/v1/models"\nBENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"\n',
    'MODELS_API = "https://openrouter.ai/api/v1/models"\nBENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"\nREASONING_PARAMETER = "reasoning"\n',
    "governance reasoning constant",
)
text = replace_once(
    text,
    'def _not_expired(row: Mapping[str, Any]) -> bool:\n',
    'def _supports_reasoning(row: Mapping[str, Any]) -> bool:\n'
    '    parameters = row.get("supported_parameters")\n'
    '    if not isinstance(parameters, list):\n'
    '        return False\n'
    '    return REASONING_PARAMETER in {\n'
    '        str(value or "").strip().casefold() for value in parameters\n'
    '    }\n\n\n'
    'def _not_expired(row: Mapping[str, Any]) -> bool:\n',
    "governance reasoning helper",
)
text = replace_once(
    text,
    '        if not _is_general_text(row) or not _not_expired(row):\n            continue\n',
    '        if (\n            not _is_general_text(row)\n            or not _not_expired(row)\n            or not _supports_reasoning(row)\n        ):\n            continue\n',
    "governance reasoning eligibility",
)
text = replace_once(
    text,
    '        "selection_rule": (\n            "use the OpenRouter pricing-low-to-high catalog order; exclude free or "\n            "incomplete pricing, non-text, expired, preview/beta/experimental, economy "\n            "and domain-specialized models; require complete intelligence/coding/agentic "\n            "benchmarks; retain strict flagship product tiers or each multi-model "\n            "company\'s natural highest layer; select the first remaining candidate"\n        ),',
    '        "selection_rule": (\n            "use the OpenRouter pricing-low-to-high catalog order; require native "\n            "reasoning support; exclude free or incomplete pricing, non-text, expired, "\n            "preview/beta/experimental, economy and domain-specialized models; require "\n            "complete intelligence/coding/agentic benchmarks; retain strict flagship "\n            "product tiers or each multi-model company\'s natural highest layer; select "\n            "the first remaining candidate"\n        ),',
    "governance reasoning selection rule",
)
text = replace_once(
    text,
    '            "domain_specialized_models_rejected": specialized_rejected,\n        },',
    '            "domain_specialized_models_rejected": specialized_rejected,\n            "native_reasoning_required": True,\n            "economy_tiers_include_luna": True,\n        },',
    "governance controls metadata",
)
text = replace_once(
    text,
    '    model_query = urllib.parse.urlencode(\n        {"sort": "pricing-low-to-high", "output_modalities": "text"}\n    )',
    '    model_query = urllib.parse.urlencode(\n        {\n            "sort": "pricing-low-to-high",\n            "output_modalities": "text",\n            "supported_parameters": REASONING_PARAMETER,\n        }\n    )',
    "governance live reasoning query",
)
path.write_text(text, encoding="utf-8")


# 2. Expert selector: reuse benchmarked natural-top flagship policy, then price rank.
path = Path("governance-copilot/select_expert_team_plan.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'from typing import Any, Mapping, Sequence\n',
    'from typing import Any, Mapping, Sequence\n\nimport select_paid_governance_flagship_model as FLAGSHIP_POLICY\n',
    "expert shared flagship policy import",
)
text = replace_once(
    text,
    'MODELS_API = "https://openrouter.ai/api/v1/models"\nENDPOINTS_API = "https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints"\n',
    'MODELS_API = "https://openrouter.ai/api/v1/models"\nBENCHMARKS_API = "https://openrouter.ai/api/v1/benchmarks"\nENDPOINTS_API = "https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints"\n',
    "expert benchmark API",
)
text = replace_once(
    text,
    'SELECTOR_SCHEMA_VERSION = "governance-openrouter-general-reasoning-flagship-price-v7"',
    'SELECTOR_SCHEMA_VERSION = "governance-openrouter-benchmarked-company-reasoning-flagship-price-v8"',
    "expert selector schema",
)
text = replace_once(
    text,
    'Selection remains deliberately simple: use OpenRouter\'s official intelligence\norder, require native reasoning support, retain only each company\'s highest-ranked\nstrict-tier stable paid general-purpose non-search reasoning model as that company\'s flagship, verify a\nreal exact provider endpoint, then sort company flagships by combined token price.\nThe first four companies are active experts and the next four are ordered standbys.',
    'Selection remains deliberately simple: read OpenRouter\'s live model and Artificial\nAnalysis benchmark feeds, require native reasoning support, reject economy and\nspecialized models, identify strict product tiers or a multi-model company\'s natural\nhighest benchmark layer, keep one strongest verified flagship per company, verify a\nreal exact provider endpoint, then sort company flagships by combined token price.\nThe first four companies are active experts and the next four are ordered standbys.',
    "expert selector docstring",
)
replacement = '''def _is_general_reasoning_candidate(identity: str) -> bool:
    return (
        not FLAGSHIP_POLICY.UNSTABLE_TIER.search(identity)
        and not FLAGSHIP_POLICY.ECONOMY_TIER.search(identity)
        and FLAGSHIP_POLICY._is_general_governance_identity(identity)
    )


def _catalog_candidates(
    payload: Mapping[str, Any],
    benchmark_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ExpertPlanError("OpenRouter model catalog is empty")

    bounded_models: list[Mapping[str, Any]] = []
    source_by_id: dict[str, Mapping[str, Any]] = {}
    official_rank_by_id: dict[str, int] = {}
    seen_models: set[str] = set()
    for official_rank, row in enumerate(rows, 1):
        if official_rank > OFFICIAL_INTELLIGENCE_RANK_LIMIT:
            break
        if not isinstance(row, Mapping):
            continue
        model_id = str(row.get("id") or "").strip()
        if not _stable_model_id(model_id) or model_id in seen_models:
            continue
        seen_models.add(model_id)
        if (
            not _is_general_text(row)
            or not _not_expired(row)
            or not _supports_reasoning(row)
            or not _is_general_reasoning_candidate(_identity(row, model_id))
        ):
            continue
        bounded_models.append(row)
        source_by_id[model_id] = row
        official_rank_by_id[model_id] = official_rank

    try:
        flagship_result = FLAGSHIP_POLICY.select_from_catalog(
            bounded_models,
            benchmark_payload,
        )
    except FLAGSHIP_POLICY.SelectorError as exc:
        raise ExpertPlanError(f"benchmarked flagship classification failed: {exc}") from exc

    raw_candidates = flagship_result.get("cheapest_paid_flagship_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ExpertPlanError("benchmarked flagship classification returned no candidates")

    # The shared policy may retain several models in a company's natural top layer.
    # Keep only the official intelligence-high-to-low leader from that verified layer.
    by_company: dict[str, list[Mapping[str, Any]]] = {}
    for row in raw_candidates:
        if not isinstance(row, Mapping):
            continue
        model_id = str(row.get("model_id") or "").strip()
        company = str(row.get("company") or "").strip().casefold()
        if model_id not in source_by_id or not company:
            continue
        by_company.setdefault(company, []).append(row)

    company_evidence = flagship_result.get("company_flagship_evidence")
    evidence_map = company_evidence if isinstance(company_evidence, Mapping) else {}
    selected: list[dict[str, Any]] = []
    for company, company_rows in by_company.items():
        winner = min(
            company_rows,
            key=lambda row: (
                official_rank_by_id.get(str(row.get("model_id") or ""), 10**9),
                -float(row.get("balanced_score") or 0.0),
                str(row.get("model_id") or ""),
            ),
        )
        model_id = str(winner.get("model_id") or "")
        source = source_by_id[model_id]
        pricing = _mapping(source.get("pricing"))
        prompt = _price_per_million(pricing, "prompt")
        completion = _price_per_million(pricing, "completion")
        if prompt is None or completion is None or prompt + completion <= 0:
            continue
        basis = str(winner.get("flagship_basis") or "")
        if basis not in {"strict-product-tier", "company-local-natural-top-layer"}:
            continue
        company_row_evidence = evidence_map.get(company)
        method = (
            str(company_row_evidence.get("method") or "")
            if isinstance(company_row_evidence, Mapping)
            else ""
        )
        benchmark_material = {
            "model_id": model_id,
            "company": company,
            "basis": basis,
            "method": method,
            "intelligence_index": winner.get("intelligence_index"),
            "coding_index": winner.get("coding_index"),
            "agentic_index": winner.get("agentic_index"),
            "balanced_score": winner.get("balanced_score"),
            "benchmark_meta": flagship_result.get("benchmark_meta"),
        }
        combined = prompt + completion
        selected.append(
            {
                "model_id": model_id,
                "company": company,
                "official_intelligence_rank": official_rank_by_id[model_id],
                "context_length": _positive_int(source.get("context_length")),
                "max_completion_tokens": _positive_int(
                    source.get("max_completion_tokens")
                ),
                "prompt_usd_per_million": prompt,
                "completion_usd_per_million": completion,
                "request_usd": _request_price(pricing),
                "price_rank_usd_per_million": combined,
                "estimated_task_cost_usd": combined,
                "reasoning_parameter_required": True,
                "flagship_verified": True,
                "flagship_basis": basis,
                "company_flagship_method": method,
                "benchmark_source": "artificial-analysis-via-openrouter",
                "intelligence_index": float(winner["intelligence_index"]),
                "coding_index": float(winner["coding_index"]),
                "agentic_index": float(winner["agentic_index"]),
                "balanced_score": float(winner["balanced_score"]),
                "benchmark_evidence_sha256": hashlib.sha256(
                    _canonical_json(benchmark_material)
                ).hexdigest(),
            }
        )

    selected.sort(
        key=lambda row: (
            float(row["price_rank_usd_per_million"]),
            float(row["request_usd"]),
            float(row["prompt_usd_per_million"]),
            float(row["completion_usd_per_million"]),
            int(row["official_intelligence_rank"]),
            str(row["model_id"]),
        )
    )
    if not selected:
        raise ExpertPlanError(
            "no benchmarked paid general-purpose reasoning company flagship is available"
        )
    return selected


def _endpoint_url'''
text = sub_once(
    text,
    r'def _is_general_reasoning_candidate\(identity: str\) -> bool:\n.*?\n\ndef _endpoint_url',
    replacement,
    "expert benchmarked catalog classification",
)
text = sub_once(
    text,
    r'def _live_flagship_rows\(token: str\) -> list\[dict\[str, Any\]\]:\n.*?\n\ndef _live_executable_flagship_rows',
    '''def _live_flagship_rows(token: str) -> list[dict[str, Any]]:
    model_query = urllib.parse.urlencode(
        {
            "sort": "intelligence-high-to-low",
            "output_modalities": "text",
            "supported_parameters": REASONING_PARAMETER,
        }
    )
    benchmark_query = urllib.parse.urlencode({"source": "artificial-analysis"})
    payload = _fetch_json(f"{MODELS_API}?{model_query}", token)
    benchmark_payload = _fetch_json(f"{BENCHMARKS_API}?{benchmark_query}", token)
    return _catalog_candidates(payload, benchmark_payload)


def _live_executable_flagship_rows''',
    "expert live benchmark fetch",
)
text = sub_once(
    text,
    r'def _model_record\(row: Mapping\[str, Any\], \*, slot: int\) -> dict\[str, Any\]:\n.*?\n\ndef _catalog_sha256',
    '''def _model_record(row: Mapping[str, Any], *, slot: int) -> dict[str, Any]:
    basis = str(row.get("flagship_basis") or "")
    if basis not in {"strict-product-tier", "company-local-natural-top-layer"}:
        raise ExpertPlanError("ranked model lacks verified company flagship basis")
    return {
        "slot": slot,
        "model": str(row["model_id"]),
        "company": str(row["company"]),
        "estimated_task_cost_usd": _finite_cost(row),
        "price_rank_usd_per_million": float(row["price_rank_usd_per_million"]),
        "prompt_usd_per_million": float(row["prompt_usd_per_million"]),
        "completion_usd_per_million": float(row["completion_usd_per_million"]),
        "official_intelligence_rank": int(row["official_intelligence_rank"]),
        "qualified_provider_count": int(row["qualified_provider_count"]),
        "endpoint_inventory_sha256": str(row["endpoint_inventory_sha256"]),
        "flagship_verified": True,
        "flagship_basis": basis,
        "company_flagship_method": str(row.get("company_flagship_method") or ""),
        "benchmark_source": str(row.get("benchmark_source") or ""),
        "intelligence_index": float(row["intelligence_index"]),
        "coding_index": float(row["coding_index"]),
        "agentic_index": float(row["agentic_index"]),
        "balanced_score": float(row["balanced_score"]),
        "benchmark_evidence_sha256": str(row["benchmark_evidence_sha256"]),
        "selection_evidence": (
            "non-search+verified-company-flagship-reasoning+"
            f"{basis}+price-order+live-exact-endpoint-qualified"
        ),
    }


def _catalog_sha256''',
    "expert model record evidence",
)
text = replace_once(
    text,
    '            "minimum_completion_tokens": row["minimum_completion_tokens"],\n',
    '            "minimum_completion_tokens": row["minimum_completion_tokens"],\n'
    '            "flagship_basis": row["flagship_basis"],\n'
    '            "company_flagship_method": row["company_flagship_method"],\n'
    '            "benchmark_source": row["benchmark_source"],\n'
    '            "intelligence_index": row["intelligence_index"],\n'
    '            "coding_index": row["coding_index"],\n'
    '            "agentic_index": row["agentic_index"],\n'
    '            "balanced_score": row["balanced_score"],\n'
    '            "benchmark_evidence_sha256": row["benchmark_evidence_sha256"],\n',
    "expert catalog digest benchmark fields",
)
text = replace_once(
    text,
    '            "openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n            "strict-flagship-tier-required -> search-specialists-excluded -> "\n            "stable-paid-general-purpose-models -> "\n            "highest-intelligence-model-per-"\n            "company-as-flagship -> live-exact-endpoint-qualified -> combined-token-"\n',
    '            "openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n'
    '            "luna-and-search-specialists-excluded -> stable-paid-general-purpose-models -> "\n'
    '            "artificial-analysis-complete-benchmarks-required -> global-natural-high-layer -> "\n'
    '            "strict-product-tier-or-company-natural-top-layer -> "\n'
    '            "highest-intelligence-verified-flagship-per-company -> "\n'
    '            "live-exact-endpoint-qualified -> combined-token-"\n',
    "expert selection policy",
)
text = replace_once(
    text,
    '        "company_model_policy": (\n            "one-highest-intelligence-strict-tier-reasoning-flagship-per-company-then-price-rank"\n        ),',
    '        "company_model_policy": (\n            "one-highest-intelligence-verified-reasoning-flagship-per-company-then-price-rank"\n        ),\n'
    '        "flagship_definition": (\n            "strict-product-tier-or-benchmarked-company-natural-top-layer"\n        ),\n'
    '        "reasoning_model_required": True,\n'
    '        "benchmark_source": "artificial-analysis-via-openrouter",',
    "expert plan flagship metadata",
)
path.write_text(text, encoding="utf-8")


# 3. Frozen ZDR wrapper and validation contracts.
path = Path("governance-copilot/expert_task_envelope.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'SCHEMA_VERSION = "governance-expert-task-envelope-v9"',
    'SCHEMA_VERSION = "governance-expert-task-envelope-v10"',
    "envelope schema",
)
text = replace_once(
    text,
    '    "governance-openrouter-live-unique-company-general-reasoning-flagship-price-v10"',
    '    "governance-openrouter-live-benchmarked-company-reasoning-flagship-price-v11"',
    "envelope selector schema",
)
text = replace_once(
    text,
    '                record["selection_evidence"] = (\n                    "non-search+strict-tier+company-highest-intelligence-reasoning-flagship+price-order+"\n                    "live-exact-endpoint-qualified+authenticated-zdr-endpoint-qualified+"\n                    "minimum-one-zdr-provider-route"\n                )',
    '                basis = str(record.get("flagship_basis") or "")\n'
    '                if basis not in {"strict-product-tier", "company-local-natural-top-layer"}:\n'
    '                    raise ExpertTaskEnvelopeError(\n'
    '                        "ranked model lacks verified company flagship basis"\n'
    '                    )\n'
    '                record["selection_evidence"] = (\n'
    '                    "non-search+verified-company-flagship-reasoning+"\n'
    '                    f"{basis}+price-order+live-exact-endpoint-qualified+"\n'
    '                    "authenticated-zdr-endpoint-qualified+"\n'
    '                    "minimum-one-zdr-provider-route"\n'
    '                )',
    "envelope dynamic flagship evidence",
)
text = replace_once(
    text,
    '                "openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n                "strict-flagship-tier-required -> search-specialists-excluded -> "\n                "stable-paid-general-purpose-models -> "\n                "highest-intelligence-model-per-"\n                "company-as-flagship -> live-exact-endpoint-qualified -> authenticated-"\n',
    '                "openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n'
    '                "luna-and-search-specialists-excluded -> stable-paid-general-purpose-models -> "\n'
    '                "artificial-analysis-complete-benchmarks-required -> global-natural-high-layer -> "\n'
    '                "strict-product-tier-or-company-natural-top-layer -> "\n'
    '                "highest-intelligence-verified-flagship-per-company -> "\n'
    '                "live-exact-endpoint-qualified -> authenticated-"\n',
    "envelope selection policy",
)
path.write_text(text, encoding="utf-8")


for filename, error_type in (
    ("tools/sign_expert_plan.py", "ExpertPlanSigningError"),
    ("tools/repair_expert_child_plan.py", "ExpertChildRepairError"),
):
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    old = (
        '            if "strict-tier+company-highest-intelligence-reasoning-flagship" not in evidence:\n'
        f'                raise {error_type}(\n'
        '                    "model lacks strict-tier reasoning flagship evidence"\n'
        '                )\n'
        if filename.startswith("tools/sign")
        else
        '            if "strict-tier+company-highest-intelligence-reasoning-flagship" not in evidence:\n'
        f'                raise {error_type}(\n'
        '                    "regenerated model lacks strict-tier reasoning flagship evidence"\n'
        '                )\n'
    )
    label = "signer" if filename.startswith("tools/sign") else "repair"
    new_message = (
        "model lacks verified company reasoning flagship evidence"
        if label == "signer"
        else "regenerated model lacks verified company reasoning flagship evidence"
    )
    new = (
        '            basis = str(row.get("flagship_basis") or "")\n'
        '            if basis not in {"strict-product-tier", "company-local-natural-top-layer"}:\n'
        f'                raise {error_type}("{label} model flagship basis is invalid")\n'
        '            if "verified-company-flagship-reasoning" not in evidence or basis not in evidence:\n'
        f'                raise {error_type}(\n'
        f'                    "{new_message}"\n'
        '                )\n'
        '            benchmark_hash = str(row.get("benchmark_evidence_sha256") or "")\n'
        '            if len(benchmark_hash) != 64 or any(\n'
        '                character not in "0123456789abcdef"\n'
        '                for character in benchmark_hash\n'
        '            ):\n'
        f'                raise {error_type}("{label} model benchmark evidence hash is invalid")\n'
    )
    text = replace_once(text, old, new, f"{label} flagship validation")
    path.write_text(text, encoding="utf-8")


# 4. Rewrite focused expert selector test for the new benchmark contract.
Path("tests/test_expert_plan_strict_flagship_policy.py").write_text(
'''from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
SPEC = importlib.util.spec_from_file_location(
    "reasoning_expert_plan_test",
    COPILOT / "select_expert_team_plan.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load expert plan selector")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def per_token(usd_per_million: float) -> str:
    return f"{usd_per_million / 1_000_000:.12f}"


def model(
    model_id: str,
    prompt: float,
    completion: float,
    *,
    reasoning: bool = True,
    context_length: int = 131_072,
    max_completion_tokens: int = 8_192,
) -> dict[str, object]:
    parameters = ["max_tokens"]
    if reasoning:
        parameters.append("reasoning")
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "name": model_id,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
        "supported_parameters": parameters,
        "pricing": {
            "prompt": per_token(prompt),
            "completion": per_token(completion),
        },
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    }


def benchmark_payload(scores: dict[str, float]) -> dict[str, object]:
    return {
        "data": [
            {
                "model_permaslug": model_id,
                "intelligence_index": score,
                "coding_index": score,
                "agentic_index": score,
            }
            for model_id, score in scores.items()
        ],
        "meta": {"source": "artificial-analysis", "version": "fixture"},
    }


def candidate(
    model_id: str,
    prompt: float,
    completion: float,
    *,
    rank: int,
    basis: str = "strict-product-tier",
) -> dict[str, object]:
    benchmark_hash = hashlib.sha256(model_id.encode("utf-8")).hexdigest()
    return {
        "model_id": model_id,
        "company": model_id.split("/", 1)[0],
        "official_intelligence_rank": rank,
        "context_length": 131_072,
        "max_completion_tokens": 8_192,
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": 0.0,
        "price_rank_usd_per_million": prompt + completion,
        "estimated_task_cost_usd": prompt + completion,
        "flagship_verified": True,
        "flagship_basis": basis,
        "company_flagship_method": "fixture-natural-top",
        "benchmark_source": "artificial-analysis-via-openrouter",
        "intelligence_index": 50.0,
        "coding_index": 50.0,
        "agentic_index": 50.0,
        "balanced_score": 50.0,
        "benchmark_evidence_sha256": benchmark_hash,
        "reasoning_parameter_required": True,
        "exact_endpoint_qualified": True,
        "qualified_provider_count": 1,
        "endpoint_inventory_sha256": f"{'a' * 63}{rank % 10}",
        "required_context_tokens": 9_000,
        "minimum_completion_tokens": 1_024,
    }


def ticket() -> dict[str, object]:
    return {
        "route": "expert-team",
        "task": {
            "question": "Select reasoning flagships in price order.",
            "requirements": [],
            "language": "zh-CN",
        },
        "approved_budget": {
            "calls": 4,
            "maximum_recovery_calls": 1,
            "cost_policy": "prompt_led_soft_governance",
        },
        "private_output": False,
    }


def endpoint(
    provider: str,
    *,
    context_length: int = 131_072,
    max_completion_tokens: int = 8_192,
) -> dict[str, object]:
    return {
        "tag": provider,
        "context_length": context_length,
        "max_completion_tokens": max_completion_tokens,
        "pricing": {
            "prompt": per_token(0.2),
            "completion": per_token(0.4),
        },
    }


class ReasoningFlagshipPriceSelectionTests(unittest.TestCase):
    def test_company_natural_top_selects_sol_and_rejects_luna(self) -> None:
        rows = [
            model("openai/gpt-5.6-sol", 5.0, 30.0),
            model("openai/gpt-5.6-terra", 1.0, 6.0),
            model("anthropic/claude-opus-5", 5.0, 25.0),
            model("deepseek/deepseek-v4-pro", 0.435, 0.87),
            model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
        ]
        scores = {
            "openai/gpt-5.6-sol": 95,
            "openai/gpt-5.6-terra": 89,
            "anthropic/claude-opus-5": 92,
            "deepseek/deepseek-v4-pro": 86,
            "openai/gpt-5.6-luna-pro": 60,
        }
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        ids = [row["model_id"] for row in filtered]
        self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
        self.assertNotIn("openai/gpt-5.6-terra", ids)
        self.assertIn("openai/gpt-5.6-sol", ids)
        self.assertEqual(
            ids,
            [
                "deepseek/deepseek-v4-pro",
                "anthropic/claude-opus-5",
                "openai/gpt-5.6-sol",
            ],
        )
        sol = next(row for row in filtered if row["company"] == "openai")
        self.assertEqual(sol["flagship_basis"], "company-local-natural-top-layer")

    def test_singleton_company_requires_strict_product_tier(self) -> None:
        rows = [
            model("singleton/frontier-reasoner", 0.1, 0.2),
            model("strict/reasoning-max", 0.2, 0.4),
        ]
        scores = {
            "singleton/frontier-reasoner": 90,
            "strict/reasoning-max": 90,
        }
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["strict/reasoning-max"],
        )

    def test_luna_pro_is_rejected_even_without_another_openai_model(self) -> None:
        rows = [
            model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
            model("other/reasoning-max", 0.2, 0.4),
        ]
        scores = {
            "openai/gpt-5.6-luna-pro": 90,
            "other/reasoning-max": 90,
        }
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["other/reasoning-max"],
        )

    def test_non_reasoning_pro_model_is_rejected(self) -> None:
        rows = [
            model("vendor/cheap-pro", 0.01, 0.02, reasoning=False),
            model("other/reasoning-max", 0.2, 0.4),
        ]
        scores = {row["id"]: 90 for row in rows}
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["other/reasoning-max"],
        )

    def test_economy_and_specialized_models_are_rejected(self) -> None:
        rows = [
            model("vendor/mini-pro", 0.01, 0.01),
            model("other/coder-max", 0.01, 0.01),
            model("perplexity/sonar-pro-search", 3.0, 15.0),
            model("google/gemini-2.5-pro", 1.25, 10.0),
            model("third/general-max", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}
        filtered = planner._catalog_candidates(
            {"data": rows}, benchmark_payload(scores)
        )
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["third/general-max", "google/gemini-2.5-pro"],
        )

    def test_live_catalog_fetches_reasoning_models_and_benchmarks(self) -> None:
        observed: list[str] = []
        rows = [
            model("vendor/reasoning-pro", 0.2, 0.4),
            model("other/reasoning-max", 0.3, 0.5),
        ]
        scores = {row["id"]: 90 for row in rows}

        def fake_fetch(url: str, token: str):
            del token
            observed.append(url)
            if "/benchmarks?" in url:
                return benchmark_payload(scores)
            return {"data": rows}

        with mock.patch.object(planner, "_fetch_json", side_effect=fake_fetch):
            planner._live_flagship_rows("fixture")
        model_query = parse_qs(urlparse(observed[0]).query)
        benchmark_query = parse_qs(urlparse(observed[1]).query)
        self.assertEqual(model_query["sort"], ["intelligence-high-to-low"])
        self.assertEqual(model_query["supported_parameters"], ["reasoning"])
        self.assertEqual(benchmark_query["source"], ["artificial-analysis"])

    def test_endpoint_inventory_requires_real_native_capacity(self) -> None:
        row = candidate("vendor/reasoning-pro", 0.2, 0.4, rank=7)
        payload = {
            "data": {
                "endpoints": [
                    endpoint("too-small", max_completion_tokens=512),
                    endpoint("short-context", context_length=4_096),
                    endpoint("usable", context_length=32_768, max_completion_tokens=4_096),
                ]
            }
        }
        compatible = planner._compatible_endpoint_inventory(row, payload, 10_000)
        self.assertEqual([item["provider"] for item in compatible], ["usable"])

    def test_plan_keeps_price_order_and_company_uniqueness(self) -> None:
        rows = [
            candidate("deepseek/deepseek-v4-pro", 0.2, 0.3, rank=5),
            candidate("nex-agi/nex-n2-pro", 0.3, 0.4, rank=9),
            candidate("minimax/minimax-m3", 0.4, 0.5, rank=15, basis="company-local-natural-top-layer"),
            candidate("xiaomi/mimo-v2.5-pro", 0.5, 0.6, rank=20),
        ]
        with mock.patch.object(
            planner,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            plan = planner.build_plan(ticket(), token="fixture")
        all_rows = [*plan["selected_models"], *plan["recovery_models"]]
        self.assertEqual(len({row["company"] for row in all_rows}), len(all_rows))
        self.assertIn("reasoning-parameter-required", plan["selection_policy"])
        self.assertIn("artificial-analysis-complete-benchmarks-required", plan["selection_policy"])
        self.assertIn("strict-product-tier-or-company-natural-top-layer", plan["selection_policy"])
        self.assertEqual(
            plan["company_model_policy"],
            "one-highest-intelligence-verified-reasoning-flagship-per-company-then-price-rank",
        )
        self.assertEqual(
            plan["flagship_definition"],
            "strict-product-tier-or-benchmarked-company-natural-top-layer",
        )
        self.assertTrue(plan["reasoning_model_required"])
        self.assertEqual(plan["model_calls"], 0)

    def test_missing_distinct_companies_fails_closed(self) -> None:
        rows = [
            candidate("vendor/a-pro", 0.1, 0.2, rank=1),
            candidate("vendor/b-max", 0.2, 0.3, rank=2),
            candidate("vendor/c-opus", 0.3, 0.4, rank=3),
        ]
        with mock.patch.object(
            planner,
            "_live_executable_flagship_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(
                planner.ExpertPlanError,
                "not enough distinct-company executable flagship models",
            ):
                planner.build_plan(ticket(), token="fixture")

    def test_selector_uses_live_benchmarks_without_task_specific_reranking(self) -> None:
        source = (COPILOT / "select_expert_team_plan.py").read_text(encoding="utf-8")
        self.assertIn("BENCHMARKS_API", source)
        self.assertIn("select_from_catalog", source)
        self.assertIn("balanced_score", source)
        self.assertNotIn("rank_flagships_by_task_cost", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
''',
encoding="utf-8",
)


# 5. Update governance selector fixtures to include reasoning metadata and regressions.
path = Path("tests/test_openrouter_governance_selector.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    request: float | None = None,\n) -> dict[str, Any]:',
    '    request: float | None = None,\n    reasoning: bool = True,\n) -> dict[str, Any]:',
    "governance model helper reasoning argument",
)
text = replace_once(
    text,
    '        "description": description,\n        "pricing": pricing,',
    '        "description": description,\n        "supported_parameters": (["max_tokens", "reasoning"] if reasoning else ["max_tokens"]),\n        "pricing": pricing,',
    "governance model helper reasoning field",
)
text = replace_once(
    text,
    '            "vendor/moderation-pro",\n        ):',
    '            "vendor/moderation-pro",\n            "perplexity/sonar-pro-search",\n        ):',
    "governance specialized search test",
)
insert_marker = '    def test_duplicate_model_ids_are_deduplicated_in_first_seen_order(self):\n'
insert_test = '''    def test_luna_and_non_reasoning_models_are_excluded(self):
        models, benchmarks = self.standard_fixture()
        models.insert(5, model("openai/gpt-5.6-luna-pro", prompt=0.01, completion=0.02))
        models.insert(6, model("vendor/nonreasoning-pro", prompt=0.01, completion=0.02, reasoning=False))
        benchmarks.extend(
            [
                benchmark("openai/gpt-5.6-luna-pro", 99),
                benchmark("vendor/nonreasoning-pro", 99),
            ]
        )
        result = run_pipeline(models, benchmarks)
        ids = {row["model_id"] for row in result["cheapest_paid_flagship_candidates"]}
        self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
        self.assertNotIn("vendor/nonreasoning-pro", ids)
        self.assertTrue(
            result["flagship_false_positive_controls"]["native_reasoning_required"]
        )

'''
if insert_marker not in text:
    raise SystemExit("governance selector test insertion marker missing")
text = text.replace(insert_marker, insert_test + insert_marker, 1)
path.write_text(text, encoding="utf-8")


# 6. Update deterministic plan fixtures and validation-test strings.
for filename in (
    "tests/test_eight_model_ordered_recovery.py",
    "tests/test_expert_zdr_endpoint_parity.py",
):
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '"flagship_basis": "company-highest-intelligence-strict-tier-stable-paid-general-non-search-reasoning-model",',
        '"flagship_basis": "strict-product-tier",\n'
        '        "flagship_verified": True,\n'
        '        "company_flagship_method": "fixture-strict-tier",\n'
        '        "benchmark_source": "artificial-analysis-via-openrouter",\n'
        '        "intelligence_index": 50.0,\n'
        '        "coding_index": 50.0,\n'
        '        "agentic_index": 50.0,\n'
        '        "balanced_score": 50.0,\n'
        '        "benchmark_evidence_sha256": "' + 'b' * 64 + '",',
    )
    text = text.replace(
        'non-search+strict-tier+company-highest-intelligence-reasoning-flagship+price-order+',
        'non-search+verified-company-flagship-reasoning+strict-product-tier+price-order+',
    )
    path.write_text(text, encoding="utf-8")

path = Path("tests/test_expert_child_plan_repair.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '                    "strict-tier+company-highest-intelligence-reasoning-flagship+"\n',
    '                    "verified-company-flagship-reasoning+strict-product-tier+"\n',
)
needle = '                "selection_evidence": (\n'
if needle in text and '"flagship_basis": "strict-product-tier"' not in text:
    text = text.replace(
        needle,
        '                "flagship_basis": "strict-product-tier",\n'
        '                "benchmark_evidence_sha256": hashlib.sha256(\n'
        '                    (company + "-benchmark").encode("utf-8")\n'
        '                ).hexdigest(),\n'
        + needle,
        1,
    )
path.write_text(text, encoding="utf-8")

path = Path("tests/test_expert_plan_preview_workflow.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '            "model lacks strict-tier reasoning flagship evidence",\n',
    '            "model lacks verified company reasoning flagship evidence",\n',
)
path.write_text(text, encoding="utf-8")

print("benchmarked reasoning flagship patch applied")
