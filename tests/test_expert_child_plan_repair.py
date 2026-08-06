from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "repair_expert_child_plan.py"
WORKFLOW = ROOT / ".github" / "workflows" / "expert-child-plan-repair.yml"


def _load():
    spec = importlib.util.spec_from_file_location("expert_child_plan_repair_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


repair = _load()


def source_ticket() -> dict:
    return {
        "task_id": "gov-172-expert",
        "route": "expert-team",
        "pipeline": {
            "pipeline_id": "gov-172-expert",
            "stage_id": "expert",
        },
        "task": {
            "question": "Analyze the existing task",
            "requirements": ["Separate facts and inference"],
            "language": "zh-CN",
        },
        "approved_budget": {
            "calls": 8,
            "maximum_recovery_calls": 1,
            "cost_policy": "prompt_led_soft_governance",
        },
        "private_output": False,
        "governance_model_plan": {"plan_sha256": "old"},
    }


def plan(ticket: dict, provider_count: int = 2) -> dict:
    rows = []
    for index, company in enumerate(("deepseek", "nex-agi", "upstage", "xiaomi"), 1):
        rows.append(
            {
                "slot": index,
                "model": f"{company}/model-{index}-pro",
                "company": company,
                "estimated_task_cost_usd": float(index),
                "qualified_provider_count": provider_count,
                "endpoint_inventory_sha256": hashlib.sha256(
                    company.encode("utf-8")
                ).hexdigest(),
                "flagship_basis": "strict-product-tier",
                "benchmark_evidence_sha256": hashlib.sha256(
                    (company + "-benchmark").encode("utf-8")
                ).hexdigest(),
                "selection_evidence": (
                    "verified-company-flagship-reasoning+strict-product-tier+"
                    "price-order+live-exact-endpoint-qualified+"
                    "authenticated-zdr-endpoint-qualified+minimum-one-zdr-provider-route"
                ),
            }
        )
    value = {
        "schema_version": "governance-expert-model-plan-v1",
        "selection_authority": "decision-system-governance",
        "task_sha256": repair.SELECTOR.task_sha256(ticket),
        "required_context_tokens": repair.TASK_ENVELOPE.required_context_tokens(ticket),
        "minimum_native_completion_tokens": 1024,
        "endpoint_qualification_performed_by_governance": True,
        "expert_count": 3,
        "recovery_count": 1,
        "selected_models": rows[:3],
        "recovery_models": rows[3:],
        "model_substitution_allowed": False,
        "expert_center_reranking_allowed": False,
    }
    value["plan_sha256"] = repair._plan_digest(value)
    return value


class ExpertChildPlanRepairTests(unittest.TestCase):
    def test_prepare_base_ticket_only_removes_old_plan(self) -> None:
        source = source_ticket()
        base = repair.prepare_base_ticket(source, "gov-172-expert")
        self.assertNotIn("governance_model_plan", base)
        expected = dict(source)
        expected.pop("governance_model_plan")
        self.assertEqual(base, expected)

    def test_verify_repair_rejects_any_non_plan_ticket_change(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        repaired["task"] = dict(repaired["task"])
        repaired["task"]["question"] = "Changed"
        new_plan = plan(repaired)
        repaired["governance_model_plan"] = new_plan
        with self.assertRaisesRegex(
            repair.ExpertChildRepairError,
            "outside governance_model_plan",
        ):
            repair.verify_repair(source, repaired, new_plan)

    def test_verify_repair_accepts_redundant_endpoints_and_distinct_companies(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        new_plan = plan(repaired, provider_count=2)
        repaired["governance_model_plan"] = new_plan
        repair.verify_repair(source, repaired, new_plan)

    def test_verify_repair_accepts_single_zdr_provider_models(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        new_plan = plan(repaired, provider_count=1)
        repaired["governance_model_plan"] = new_plan
        repair.verify_repair(source, repaired, new_plan)


    def test_verify_repair_allows_openai_as_unique_company(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        new_plan = plan(repaired, provider_count=1)
        new_plan["selected_models"][0]["model"] = "openai/gpt-5-pro"
        new_plan["selected_models"][0]["company"] = "openai"
        new_plan["plan_sha256"] = repair._plan_digest(new_plan)
        repaired["governance_model_plan"] = new_plan
        repair.verify_repair(source, repaired, new_plan)

    def test_verify_repair_rejects_company_reuse_across_recovery(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        new_plan = plan(repaired, provider_count=1)
        new_plan["recovery_models"][0]["company"] = new_plan["selected_models"][0]["company"]
        new_plan["plan_sha256"] = repair._plan_digest(new_plan)
        repaired["governance_model_plan"] = new_plan
        with self.assertRaisesRegex(
            repair.ExpertChildRepairError,
            "regenerated plan reuses a model company",
        ):
            repair.verify_repair(source, repaired, new_plan)

    def test_verify_repair_rejects_preproduction_context_floor(self) -> None:
        source = source_ticket()
        repaired = dict(source)
        new_plan = plan(repaired)
        new_plan["required_context_tokens"] = 8969
        new_plan["plan_sha256"] = repair._plan_digest(new_plan)
        repaired["governance_model_plan"] = new_plan
        with self.assertRaisesRegex(
            repair.ExpertChildRepairError,
            "frozen expert task envelope",
        ):
            repair.verify_repair(source, repaired, new_plan)

    def test_workflow_supports_owner_only_parent_issue_comment(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("issue_comment:", text)
        self.assertIn("types: [created]", text)
        self.assertIn("github.event.issue.title == '[control]'", text)
        self.assertIn(
            "github.event.comment.user.login == github.repository_owner",
            text,
        )
        self.assertIn(
            "startsWith(github.event.comment.body, '/repair-expert-child-plan ')",
            text,
        )
        self.assertIn("shlex.split", text)
        self.assertIn("len(parts) != 4", text)

    def test_workflow_uses_exact_governance_child_title_contract(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            'expected_title="[execution] ${EXPECTED_TASK_ID} via governance"',
            text,
        )
        self.assertIn('test "$title" = "$expected_title"', text)

    def test_workflow_updates_same_issue_and_uses_cross_repo_control_token(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("a15280020511/expert-assessment-center", text)
        self.assertIn("secrets.CONTROL_PLANE_TOKEN", text)
        self.assertIn("secrets.OPENROUTER_API_KEY", text)
        self.assertIn("-F body=@repaired-ticket.json", text)
        self.assertIn("/retry-expert-team ${RETRY_ID}", text)
        self.assertNotIn("gh issue create", text)
        self.assertNotIn("issues: write", text)


if __name__ == "__main__":
    unittest.main()
