#!/usr/bin/env python3
from pathlib import Path

PLAN = Path("governance-copilot/select_expert_team_plan.py")
TEST = Path("tests/test_expert_plan_strict_flagship_policy.py")

text = PLAN.read_text(encoding="utf-8")
old_block = '''    selected_rows = _distinct_company_rows(rows, expert_count)
    selected_companies = {str(row["company"]) for row in selected_rows}
    recovery_rows = _distinct_company_rows(
        rows,
        recovery_count,
        excluded=selected_companies,
    ) if recovery_count else []
'''
new_block = '''    strict_rows = [
        row
        for row in rows
        if row.get("strict_product_tier") is True
        and str(row.get("flagship_basis") or "") == "strict-product-tier"
    ]
    if not strict_rows:
        raise ExpertPlanError(
            "governance cost ranking produced no strict flagship candidates"
        )

    selected_rows = _distinct_company_rows(strict_rows, expert_count)
    selected_companies = {str(row["company"]) for row in selected_rows}
    recovery_rows = _distinct_company_rows(
        strict_rows,
        recovery_count,
        excluded=selected_companies,
    ) if recovery_count else []
'''
if text.count(old_block) != 1:
    raise SystemExit("expected expert selection block not found exactly once")
text = text.replace(old_block, new_block, 1)

old_policy = '''            "qualified-paid-general-purpose-flagships -> estimated-task-cost-ascending "
            "-> distinct-model-companies"
'''
new_policy = '''            "strict-product-tier-paid-general-purpose-flagships "
            "-> estimated-task-cost-ascending -> distinct-model-companies"
'''
if text.count(old_policy) != 1:
    raise SystemExit("expected selection policy not found exactly once")
text = text.replace(old_policy, new_policy, 1)
text = text.replace(
    "not enough distinct-company flagship models:",
    "not enough distinct-company strict flagship models:",
    1,
)
PLAN.write_text(text, encoding="utf-8")

TEST.write_text('''from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
sys.path.insert(0, str(COPILOT))
SPEC = importlib.util.spec_from_file_location(
    "strict_expert_plan_test", COPILOT / "select_expert_team_plan.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load expert plan selector")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def candidate(model_id, company, prompt, completion, *, strict):
    return {
        "model_id": model_id,
        "company": company,
        "prompt_usd_per_million": prompt,
        "completion_usd_per_million": completion,
        "request_usd": None,
        "balanced_score": 50.0,
        "strict_product_tier": strict,
        "flagship_basis": (
            "strict-product-tier" if strict else "company-local-natural-top-layer"
        ),
    }


def ticket():
    return {
        "route": "expert-team",
        "task": {
            "question": "Validate strict flagship price ordering.",
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


class StrictFlagshipExpertPlanTests(unittest.TestCase):
    def receipt(self):
        return {
            "schema_version": "governance-openrouter-paid-governance-flagship-v1",
            "cheapest_paid_flagship_candidates": [
                candidate(
                    "openai/gpt-5.6-luna", "openai", 0.01, 0.02, strict=False
                ),
                candidate("nex-agi/nex-n2-pro", "nex-agi", 0.25, 1.0, strict=True),
                candidate(
                    "deepseek/deepseek-v4-pro", "deepseek", 0.435, 0.87, strict=True
                ),
                candidate("xiaomi/mimo-v2.5-pro", "xiaomi", 0.50, 1.0, strict=True),
                candidate("anthropic/claude-opus", "anthropic", 1.0, 3.0, strict=True),
            ],
        }

    def test_non_strict_natural_top_model_is_never_selected(self):
        with mock.patch.object(
            planner, "_live_flagship_receipt", return_value=self.receipt()
        ):
            plan = planner.build_plan(ticket(), token="fixture")
        all_models = plan["selected_models"] + plan["recovery_models"]
        ids = [row["model"] for row in all_models]
        self.assertNotIn("openai/gpt-5.6-luna", ids)
        self.assertEqual(
            ids,
            [
                "nex-agi/nex-n2-pro",
                "deepseek/deepseek-v4-pro",
                "xiaomi/mimo-v2.5-pro",
                "anthropic/claude-opus",
            ],
        )
        self.assertTrue(
            all(row["selection_evidence"] == "strict-product-tier" for row in all_models)
        )
        costs = [row["estimated_task_cost_usd"] for row in all_models]
        self.assertEqual(costs, sorted(costs))
        self.assertEqual(
            plan["selection_policy"],
            "strict-product-tier-paid-general-purpose-flagships "
            "-> estimated-task-cost-ascending -> distinct-model-companies",
        )

    def test_non_strict_models_cannot_fill_missing_company_slots(self):
        receipt = self.receipt()
        receipt["cheapest_paid_flagship_candidates"] = [
            candidate("vendor/a-pro", "vendor-a", 0.1, 0.2, strict=True),
            candidate("vendor/b-max", "vendor-b", 0.2, 0.3, strict=True),
            candidate("cheap/not-flagship", "cheap", 0.001, 0.001, strict=False),
            candidate("cheap/also-not-flagship", "cheap-2", 0.002, 0.002, strict=False),
        ]
        with mock.patch.object(
            planner, "_live_flagship_receipt", return_value=receipt
        ):
            with self.assertRaisesRegex(
                planner.ExpertPlanError,
                "not enough distinct-company strict flagship models",
            ):
                planner.build_plan(ticket(), token="fixture")


if __name__ == "__main__":
    unittest.main(verbosity=2)
''', encoding="utf-8")
