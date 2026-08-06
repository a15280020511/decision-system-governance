#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "governance-copilot" / "select_expert_team_plan.py"
ENVELOPE = ROOT / "governance-copilot" / "expert_task_envelope.py"
TEST = ROOT / "tests" / "test_expert_plan_strict_flagship_policy.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing patch marker: {label}")
    return text.replace(old, new, 1)


def patch_selector() -> None:
    text = SELECTOR.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-reasoning-flagship-price-v5"',
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-strict-reasoning-flagship-price-v6"',
        "selector schema",
    )
    text = replace_once(
        text,
        '''    return (
        not EXCLUDED_TIER.search(identity)
        and not any(marker in lowered for marker in SPECIALIZED_MARKERS)
    )
''',
        '''    return (
        bool(FLAGSHIP_TIER.search(identity))
        and not EXCLUDED_TIER.search(identity)
        and not any(marker in lowered for marker in SPECIALIZED_MARKERS)
    )
''',
        "strict flagship tier check",
    )
    text = text.replace(
        "stable paid general-purpose reasoning model as that company's flagship",
        "strict-tier stable paid general-purpose reasoning model as that company's flagship",
    )
    text = text.replace(
        "that company's strongest current stable paid general-purpose reasoning model.",
        "that company's strongest current strict-tier stable paid general-purpose reasoning model.",
    )
    text = text.replace(
        '"company-highest-intelligence-stable-paid-general-reasoning-model"',
        '"company-highest-intelligence-strict-tier-stable-paid-general-reasoning-model"',
    )
    text = text.replace(
        "no paid stable general-purpose reasoning flagship is available",
        "no paid strict-tier stable general-purpose reasoning flagship is available",
    )
    text = text.replace(
        '"company-highest-intelligence-reasoning-flagship+price-order+live-exact-endpoint-qualified"',
        '"strict-tier+company-highest-intelligence-reasoning-flagship+price-order+live-exact-endpoint-qualified"',
    )
    text = text.replace(
        '"stable-paid-general-purpose-models -> highest-intelligence-model-per-"',
        '"strict-flagship-tier-required -> stable-paid-general-purpose-models -> "\n'
        '            "highest-intelligence-model-per-"',
    )
    text = text.replace(
        '"one-highest-intelligence-reasoning-flagship-per-company-then-price-rank"',
        '"one-highest-intelligence-strict-tier-reasoning-flagship-per-company-then-price-rank"',
    )
    SELECTOR.write_text(text, encoding="utf-8")


def patch_envelope() -> None:
    text = ENVELOPE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'SCHEMA_VERSION = "governance-expert-task-envelope-v7"',
        'SCHEMA_VERSION = "governance-expert-task-envelope-v8"',
        "envelope schema",
    )
    text = replace_once(
        text,
        '"governance-openrouter-live-unique-company-reasoning-flagship-price-v8"',
        '"governance-openrouter-live-unique-company-strict-reasoning-flagship-price-v9"',
        "frozen selector schema",
    )
    text = text.replace(
        "highest-intelligence reasoning flagship per company",
        "highest-intelligence strict-tier reasoning flagship per company",
    )
    text = text.replace(
        '"company-highest-intelligence-reasoning-flagship+price-order+"',
        '"strict-tier+company-highest-intelligence-reasoning-flagship+price-order+"',
    )
    text = text.replace(
        '"stable-paid-general-purpose-models -> highest-intelligence-model-per-"',
        '"strict-flagship-tier-required -> stable-paid-general-purpose-models -> "\n'
        '                "highest-intelligence-model-per-"',
    )
    ENVELOPE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = text.replace(
        '"company-highest-intelligence-stable-paid-general-reasoning-model"',
        '"company-highest-intelligence-strict-tier-stable-paid-general-reasoning-model"',
    )
    text = text.replace('model("openai/gpt-5", 1.0, 4.0)', 'model("openai/gpt-5-pro", 1.0, 4.0)')
    text = text.replace('self.assertIn("openai/gpt-5", ids)', 'self.assertIn("openai/gpt-5-pro", ids)')
    text = text.replace('"openai/gpt-5",', '"openai/gpt-5-pro",')
    text = replace_once(
        text,
        '''        rows = [
            model("vendor/mini-pro", 0.01, 0.01),
            model("other/coder-max", 0.01, 0.01),
            model("third/general-reasoner", 0.3, 0.5),
        ]
        filtered = planner._catalog_candidates({"data": rows})
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["third/general-reasoner"],
        )
''',
        '''        rows = [
            model("vendor/mini-pro", 0.01, 0.01),
            model("other/coder-max", 0.01, 0.01),
            model("google/gemma-4-31b-it", 0.1, 0.34),
            model("tencent/hunyuan-a13b-instruct", 0.14, 0.57),
            model("google/gemini-2.5-pro", 1.25, 10.0),
            model("third/general-max", 0.3, 0.5),
        ]
        filtered = planner._catalog_candidates({"data": rows})
        self.assertEqual(
            [row["model_id"] for row in filtered],
            ["third/general-max", "google/gemini-2.5-pro"],
        )
        self.assertNotIn("google/gemma-4-31b-it", [row["model_id"] for row in filtered])
        self.assertNotIn(
            "tencent/hunyuan-a13b-instruct",
            [row["model_id"] for row in filtered],
        )
''',
        "strict tier regression",
    )
    text = text.replace(
        '"one-highest-intelligence-reasoning-flagship-per-company-then-price-rank",',
        '"one-highest-intelligence-strict-tier-reasoning-flagship-per-company-then-price-rank",',
    )
    needle = '''        self.assertIn(
            "reasoning-parameter-required",
            plan["selection_policy"],
        )
'''
    addition = needle + '''        self.assertIn(
            "strict-flagship-tier-required",
            plan["selection_policy"],
        )
'''
    text = replace_once(text, needle, addition, "strict policy assertion")
    TEST.write_text(text, encoding="utf-8")


def main() -> int:
    patch_selector()
    patch_envelope()
    patch_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
