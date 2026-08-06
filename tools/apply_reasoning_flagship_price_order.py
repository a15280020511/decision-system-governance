#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "governance-copilot" / "select_expert_team_plan.py"
ENVELOPE = ROOT / "governance-copilot" / "expert_task_envelope.py"
TEST = ROOT / "tests" / "test_expert_plan_strict_flagship_policy.py"


def patch_selector() -> None:
    text = SELECTOR.read_text(encoding="utf-8")
    text = text.replace(
        "Selection remains deliberately simple: use OpenRouter's official intelligence\n"
        "order as the eligibility ceiling, retain explicit paid flagship tiers, verify a\n"
        "real exact provider endpoint for the current task, sort by combined token price,\n"
        "keep only the cheapest qualified flagship from each company, and use the first\n"
        "four companies as active experts plus the next four companies as ordered standbys.\n",
        "Selection remains deliberately simple: use OpenRouter's official intelligence\n"
        "order, require native reasoning support, retain only each company's highest-ranked\n"
        "stable paid general-purpose reasoning model as that company's flagship, verify a\n"
        "real exact provider endpoint, then sort company flagships by combined token price.\n"
        "The first four companies are active experts and the next four are ordered standbys.\n",
        1,
    )
    text = text.replace(
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-executable-flagship-price-v4"',
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-reasoning-flagship-price-v5"',
        1,
    )
    if 'REASONING_PARAMETER = "reasoning"' not in text:
        marker = "FIXED_PROTOCOL_RESERVE = 8_192\n"
        if marker not in text:
            raise RuntimeError("selector constant insertion marker is missing")
        text = text.replace(
            marker,
            marker + 'REASONING_PARAMETER = "reasoning"\n',
            1,
        )

    start = text.index("def _is_general_flagship(")
    end = text.index("\ndef _catalog_candidates(", start)
    helper = textwrap.dedent('''\
    def _supports_reasoning(row: Mapping[str, Any]) -> bool:
        parameters = row.get("supported_parameters")
        if not isinstance(parameters, list):
            return False
        return REASONING_PARAMETER in {
            str(value or "").strip().casefold() for value in parameters
        }


    def _is_general_reasoning_candidate(identity: str) -> bool:
        lowered = identity.lower()
        return (
            not EXCLUDED_TIER.search(identity)
            and not any(marker in lowered for marker in SPECIALIZED_MARKERS)
        )

    ''')
    text = text[:start] + helper + text[end + 1 :]

    start = text.index("def _catalog_candidates(")
    end = text.index("\ndef _endpoint_url(", start)
    catalog_function = textwrap.dedent('''\
    def _catalog_candidates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise ExpertPlanError("OpenRouter model catalog is empty")

        # The API rows are requested in official intelligence-high-to-low order.
        # The first eligible reasoning model encountered for a company is therefore
        # that company's strongest current stable paid general-purpose reasoning model.
        company_flagships: dict[str, dict[str, Any]] = {}
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
            company = model_id.split("/", 1)[0].casefold()
            if company in company_flagships:
                continue
            if (
                not _is_general_text(row)
                or not _not_expired(row)
                or not _supports_reasoning(row)
                or not _is_general_reasoning_candidate(_identity(row, model_id))
            ):
                continue

            pricing = _mapping(row.get("pricing"))
            prompt = _price_per_million(pricing, "prompt")
            completion = _price_per_million(pricing, "completion")
            if prompt is None or completion is None or prompt + completion <= 0:
                continue

            combined = prompt + completion
            company_flagships[company] = {
                "model_id": model_id,
                "company": company,
                "official_intelligence_rank": official_rank,
                "context_length": _positive_int(row.get("context_length")),
                "max_completion_tokens": _positive_int(
                    row.get("max_completion_tokens")
                ),
                "prompt_usd_per_million": prompt,
                "completion_usd_per_million": completion,
                "request_usd": _request_price(pricing),
                "price_rank_usd_per_million": combined,
                "estimated_task_cost_usd": combined,
                "flagship_basis": (
                    "company-highest-intelligence-stable-paid-general-reasoning-model"
                ),
                "reasoning_parameter_required": True,
            }

        candidates = list(company_flagships.values())
        candidates.sort(
            key=lambda row: (
                float(row["price_rank_usd_per_million"]),
                float(row["request_usd"]),
                float(row["prompt_usd_per_million"]),
                float(row["completion_usd_per_million"]),
                int(row["official_intelligence_rank"]),
                str(row["model_id"]),
            )
        )
        if not candidates:
            raise ExpertPlanError(
                "no paid stable general-purpose reasoning flagship is available "
                "within the official intelligence top 1000"
            )
        return candidates

    ''')
    text = text[:start] + catalog_function + text[end + 1 :]

    start = text.index("def _live_flagship_rows(")
    end = text.index("\ndef _live_executable_flagship_rows(", start)
    live_function = textwrap.dedent('''\
    def _live_flagship_rows(token: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "sort": "intelligence-high-to-low",
                "output_modalities": "text",
                "supported_parameters": REASONING_PARAMETER,
            }
        )
        payload = _fetch_json(f"{MODELS_API}?{query}", token)
        return _catalog_candidates(payload)

    ''')
    text = text[:start] + live_function + text[end + 1 :]

    text = text.replace(
        '"explicit-product-tier-price-order+live-exact-endpoint-qualified"',
        '"company-highest-intelligence-reasoning-flagship+price-order+live-exact-endpoint-qualified"',
        1,
    )
    text = text.replace(
        '"openrouter-official-intelligence-top-1000 -> paid-general-purpose-"\n'
        '            "flagships -> live-exact-endpoint-qualified -> combined-token-price-"\n'
        '            "ascending -> cheapest-qualified-model-per-company -> "',
        '"openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n'
        '            "stable-paid-general-purpose-models -> highest-intelligence-model-per-"\n'
        '            "company-as-flagship -> live-exact-endpoint-qualified -> combined-token-"\n'
        '            "price-ascending -> one-flagship-per-company -> "',
        1,
    )
    text = text.replace(
        '"company_model_policy": "one-cheapest-qualified-flagship-per-company",',
        '"company_model_policy": (\n'
        '            "one-highest-intelligence-reasoning-flagship-per-company-then-price-rank"\n'
        '        ),',
        1,
    )
    SELECTOR.write_text(text, encoding="utf-8")


def patch_envelope() -> None:
    text = ENVELOPE.read_text(encoding="utf-8")
    text = text.replace(
        "cheapest qualified flagship per company; within that frozen set, the strongest official\n",
        "highest-intelligence reasoning flagship per company, then sorts those company flagships\n"
        "by price; within that frozen set, the strongest official\n",
        1,
    )
    text = text.replace(
        'SCHEMA_VERSION = "governance-expert-task-envelope-v6"',
        'SCHEMA_VERSION = "governance-expert-task-envelope-v7"',
        1,
    )
    text = text.replace(
        '"governance-openrouter-live-unique-company-flagship-price-v7"',
        '"governance-openrouter-live-unique-company-reasoning-flagship-price-v8"',
        1,
    )
    text = text.replace(
        '"explicit-product-tier-price-order+live-exact-endpoint-qualified+"\n'
        '                    "authenticated-zdr-endpoint-qualified+minimum-one-zdr-provider-route"',
        '"company-highest-intelligence-reasoning-flagship+price-order+"\n'
        '                    "live-exact-endpoint-qualified+authenticated-zdr-endpoint-qualified+"\n'
        '                    "minimum-one-zdr-provider-route"',
        1,
    )
    text = text.replace(
        '"openrouter-official-intelligence-top-1000 -> paid-general-purpose-"\n'
        '                "flagships -> live-exact-endpoint-qualified -> authenticated-zdr-"\n'
        '                "endpoint-qualified -> minimum-one-zdr-provider-route -> combined-token-"\n'
        '                "price-ascending -> cheapest-qualified-model-per-company -> "',
        '"openrouter-official-intelligence-top-1000 -> reasoning-parameter-required -> "\n'
        '                "stable-paid-general-purpose-models -> highest-intelligence-model-per-"\n'
        '                "company-as-flagship -> live-exact-endpoint-qualified -> authenticated-"\n'
        '                "zdr-endpoint-qualified -> minimum-one-zdr-provider-route -> combined-"\n'
        '                "token-price-ascending -> one-flagship-per-company -> "',
        1,
    )
    ENVELOPE.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        textwrap.dedent('''\
        from __future__ import annotations

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


        def candidate(
            model_id: str,
            prompt: float,
            completion: float,
            *,
            rank: int,
        ) -> dict[str, object]:
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
                "flagship_basis": (
                    "company-highest-intelligence-stable-paid-general-reasoning-model"
                ),
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
            def test_company_strongest_reasoning_model_wins_before_price_sort(self) -> None:
                rows = [
                    model("openai/gpt-5", 1.0, 4.0),
                    model("anthropic/claude-opus", 2.0, 5.0),
                    model("openai/gpt-5.6-luna-pro", 0.1, 0.6),
                    model("deepseek/deepseek-v4-pro", 0.4, 0.9),
                ]
                filtered = planner._catalog_candidates({"data": rows})
                ids = [row["model_id"] for row in filtered]
                self.assertNotIn("openai/gpt-5.6-luna-pro", ids)
                self.assertIn("openai/gpt-5", ids)
                self.assertEqual(
                    ids,
                    [
                        "deepseek/deepseek-v4-pro",
                        "openai/gpt-5",
                        "anthropic/claude-opus",
                    ],
                )
                self.assertEqual(
                    [row["price_rank_usd_per_million"] for row in filtered],
                    sorted(row["price_rank_usd_per_million"] for row in filtered),
                )

            def test_non_reasoning_pro_model_is_rejected(self) -> None:
                rows = [
                    model("vendor/cheap-pro", 0.01, 0.02, reasoning=False),
                    model("other/reasoning-max", 0.2, 0.4),
                ]
                filtered = planner._catalog_candidates({"data": rows})
                self.assertEqual(
                    [row["model_id"] for row in filtered],
                    ["other/reasoning-max"],
                )

            def test_economy_and_specialized_reasoning_models_are_rejected(self) -> None:
                rows = [
                    model("vendor/mini-pro", 0.01, 0.01),
                    model("other/coder-max", 0.01, 0.01),
                    model("third/general-reasoner", 0.3, 0.5),
                ]
                filtered = planner._catalog_candidates({"data": rows})
                self.assertEqual(
                    [row["model_id"] for row in filtered],
                    ["third/general-reasoner"],
                )

            def test_live_catalog_request_requires_reasoning_parameter(self) -> None:
                observed: list[str] = []

                def fake_fetch(url: str, token: str):
                    del token
                    observed.append(url)
                    return {
                        "data": [model("vendor/reasoning-pro", 0.2, 0.4)]
                    }

                with mock.patch.object(planner, "_fetch_json", side_effect=fake_fetch):
                    planner._live_flagship_rows("fixture")
                query = parse_qs(urlparse(observed[0]).query)
                self.assertEqual(query["sort"], ["intelligence-high-to-low"])
                self.assertEqual(query["output_modalities"], ["text"])
                self.assertEqual(query["supported_parameters"], ["reasoning"])

            def test_endpoint_inventory_requires_real_native_capacity(self) -> None:
                row = candidate("vendor/reasoning-pro", 0.2, 0.4, rank=7)
                payload = {
                    "data": {
                        "endpoints": [
                            endpoint("too-small", max_completion_tokens=512),
                            endpoint("short-context", context_length=4_096),
                            endpoint(
                                "usable",
                                context_length=32_768,
                                max_completion_tokens=4_096,
                            ),
                        ]
                    }
                }
                compatible = planner._compatible_endpoint_inventory(
                    row,
                    payload,
                    10_000,
                )
                self.assertEqual(
                    [item["provider"] for item in compatible],
                    ["usable"],
                )

            def test_plan_keeps_price_order_and_company_uniqueness(self) -> None:
                rows = [
                    candidate("deepseek/deepseek-v4-pro", 0.2, 0.3, rank=5),
                    candidate("nex-agi/nex-n2-pro", 0.3, 0.4, rank=9),
                    candidate("upstage/solar-pro-3", 0.4, 0.5, rank=15),
                    candidate("xiaomi/mimo-v2.5-pro", 0.5, 0.6, rank=20),
                ]
                with mock.patch.object(
                    planner,
                    "_live_executable_flagship_rows",
                    return_value=rows,
                ):
                    plan = planner.build_plan(ticket(), token="fixture")
                all_rows = [
                    *plan["selected_models"],
                    *plan["recovery_models"],
                ]
                self.assertEqual(
                    len({row["company"] for row in all_rows}),
                    len(all_rows),
                )
                self.assertIn(
                    "reasoning-parameter-required",
                    plan["selection_policy"],
                )
                self.assertIn(
                    "highest-intelligence-model-per-company-as-flagship",
                    plan["selection_policy"],
                )
                self.assertEqual(
                    plan["company_model_policy"],
                    "one-highest-intelligence-reasoning-flagship-per-company-then-price-rank",
                )
                self.assertEqual(
                    plan["price_rank_basis"],
                    "prompt_usd_per_million + completion_usd_per_million",
                )
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

            def test_selector_has_no_benchmark_or_local_task_ranking_dependency(self) -> None:
                source = (
                    COPILOT / "select_expert_team_plan.py"
                ).read_text(encoding="utf-8")
                self.assertNotIn("BENCHMARKS_API", source)
                self.assertNotIn("rank_flagships_by_task_cost", source)
                self.assertNotIn("balanced_score", source)
                self.assertNotIn("natural_high", source)


        if __name__ == "__main__":
            unittest.main(verbosity=2)
        '''),
        encoding="utf-8",
    )


def main() -> int:
    patch_selector()
    patch_envelope()
    write_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
