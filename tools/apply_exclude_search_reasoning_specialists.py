#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "governance-copilot" / "select_expert_team_plan.py"
ENVELOPE = ROOT / "governance-copilot" / "expert_task_envelope.py"
TEST = ROOT / "tests" / "test_expert_plan_strict_flagship_policy.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing marker: {label}")
    return text.replace(old, new, 1)


def main() -> int:
    text = SELECTOR.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-strict-reasoning-flagship-price-v6"',
        'SELECTOR_SCHEMA_VERSION = "governance-openrouter-general-reasoning-flagship-price-v7"',
        "selector schema",
    )
    text = replace_once(
        text,
        '    "moderation",\n)',
        '    "moderation",\n    "search",\n)',
        "search specialist marker",
    )
    text = text.replace(
        "strict-tier stable paid general-purpose reasoning model",
        "strict-tier stable paid general-purpose non-search reasoning model",
    )
    text = text.replace(
        '"company-highest-intelligence-strict-tier-stable-paid-general-reasoning-model"',
        '"company-highest-intelligence-strict-tier-stable-paid-general-non-search-reasoning-model"',
    )
    text = text.replace(
        '"strict-tier+company-highest-intelligence-reasoning-flagship+price-order+',
        '"non-search+strict-tier+company-highest-intelligence-reasoning-flagship+price-order+',
    )
    text = text.replace(
        '"strict-flagship-tier-required -> stable-paid-general-purpose-models -> "',
        '"strict-flagship-tier-required -> search-specialists-excluded -> "\n'
        '            "stable-paid-general-purpose-models -> "',
    )
    SELECTOR.write_text(text, encoding="utf-8")

    text = ENVELOPE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'SCHEMA_VERSION = "governance-expert-task-envelope-v8"',
        'SCHEMA_VERSION = "governance-expert-task-envelope-v9"',
        "envelope schema",
    )
    text = replace_once(
        text,
        '"governance-openrouter-live-unique-company-strict-reasoning-flagship-price-v9"',
        '"governance-openrouter-live-unique-company-general-reasoning-flagship-price-v10"',
        "envelope selector schema",
    )
    text = text.replace(
        '"strict-tier+company-highest-intelligence-reasoning-flagship+price-order+',
        '"non-search+strict-tier+company-highest-intelligence-reasoning-flagship+price-order+',
    )
    text = text.replace(
        '"strict-flagship-tier-required -> stable-paid-general-purpose-models -> "',
        '"strict-flagship-tier-required -> search-specialists-excluded -> "\n'
        '                "stable-paid-general-purpose-models -> "',
    )
    ENVELOPE.write_text(text, encoding="utf-8")

    text = TEST.read_text(encoding="utf-8")
    text = text.replace(
        '"company-highest-intelligence-strict-tier-stable-paid-general-reasoning-model"',
        '"company-highest-intelligence-strict-tier-stable-paid-general-non-search-reasoning-model"',
    )
    needle = '''            model("google/gemini-2.5-pro", 1.25, 10.0),
            model("third/general-max", 0.3, 0.5),
'''
    replacement = '''            model("google/gemini-2.5-pro", 1.25, 10.0),
            model("perplexity/sonar-pro-search", 3.0, 15.0),
            model("third/general-max", 0.3, 0.5),
'''
    text = replace_once(text, needle, replacement, "search regression fixture")
    needle = '''        self.assertNotIn(
            "tencent/hunyuan-a13b-instruct",
            [row["model_id"] for row in filtered],
        )
'''
    replacement = needle + '''        self.assertNotIn(
            "perplexity/sonar-pro-search",
            [row["model_id"] for row in filtered],
        )
'''
    text = replace_once(text, needle, replacement, "search regression assertion")
    needle = '''        self.assertIn(
            "strict-flagship-tier-required",
            plan["selection_policy"],
        )
'''
    replacement = needle + '''        self.assertIn(
            "search-specialists-excluded",
            plan["selection_policy"],
        )
'''
    text = replace_once(text, needle, replacement, "search policy assertion")
    TEST.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
