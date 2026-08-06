from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "governance-copilot" / "expert_task_envelope.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "expert_intelligence_ranked_roles_test",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ENVELOPE = _load()


def roles(expert_count: int) -> list[dict[str, str]]:
    lenses = (
        ("evidence", "independent-evidence"),
        ("options", "independent-options"),
        ("risk", "independent-risk"),
        ("stakeholders", "independent-stakeholders"),
    )
    result = [
        {"role_id": role_id, "role_kind": "independent", "role": label}
        for role_id, label in lenses[: expert_count - 2]
    ]
    result.extend(
        [
            {"role_id": "review", "role_kind": "review", "role": "review"},
            {
                "role_id": "synthesis",
                "role_kind": "synthesis",
                "role": "synthesis",
            },
        ]
    )
    return result


def selected_rows() -> list[dict]:
    return [
        {
            "slot": 1,
            "model": "deepseek/deepseek-v4-pro",
            "company": "deepseek",
            "estimated_task_cost_usd": 1.305,
            "official_intelligence_rank": 23,
            "role_id": "evidence",
            "role_kind": "independent",
            "role": "old-evidence",
        },
        {
            "slot": 2,
            "model": "xiaomi/mimo-v2.5-pro",
            "company": "xiaomi",
            "estimated_task_cost_usd": 1.305,
            "official_intelligence_rank": 25,
            "role_id": "options",
            "role_kind": "independent",
            "role": "old-options",
        },
        {
            "slot": 3,
            "model": "amazon/nova-pro-v1",
            "company": "amazon",
            "estimated_task_cost_usd": 4.0,
            "official_intelligence_rank": 129,
            "role_id": "review",
            "role_kind": "review",
            "role": "old-review",
        },
        {
            "slot": 4,
            "model": "nvidia/nemotron-3-ultra-550b-a55b",
            "company": "nvidia",
            "estimated_task_cost_usd": 4.2,
            "official_intelligence_rank": 38,
            "role_id": "synthesis",
            "role_kind": "synthesis",
            "role": "old-synthesis",
        },
    ]


class ExpertIntelligenceRankedRoleTests(unittest.TestCase):
    def test_price_minimal_set_is_preserved_and_roles_are_reassigned(self) -> None:
        original = selected_rows()
        plan = {"selected_models": original}
        ENVELOPE._assign_intelligence_ranked_roles(
            SimpleNamespace(_roles=roles),
            plan,
        )
        assigned = plan["selected_models"]
        self.assertEqual(
            {row["model"] for row in assigned},
            {row["model"] for row in original},
        )
        self.assertEqual([row["slot"] for row in assigned], [1, 2, 3, 4])
        self.assertEqual(
            [row["model"] for row in assigned],
            [
                "amazon/nova-pro-v1",
                "nvidia/nemotron-3-ultra-550b-a55b",
                "xiaomi/mimo-v2.5-pro",
                "deepseek/deepseek-v4-pro",
            ],
        )
        self.assertEqual(
            [row["role_kind"] for row in assigned],
            ["independent", "independent", "review", "synthesis"],
        )
        self.assertEqual(plan["final_synthesis_official_intelligence_rank"], 23)
        self.assertEqual(plan["cross_review_official_intelligence_rank"], 25)
        self.assertEqual(
            plan["role_assignment_policy"],
            ENVELOPE.ROLE_ASSIGNMENT_POLICY,
        )

    def test_best_and_second_best_are_bound_to_fixed_review_roles(self) -> None:
        plan = {"selected_models": selected_rows()}
        ENVELOPE._assign_intelligence_ranked_roles(
            SimpleNamespace(_roles=roles),
            plan,
        )
        by_kind = {row["role_kind"]: row for row in plan["selected_models"]}
        self.assertEqual(
            by_kind["synthesis"]["model"],
            "deepseek/deepseek-v4-pro",
        )
        self.assertEqual(
            by_kind["review"]["model"],
            "xiaomi/mimo-v2.5-pro",
        )

    def test_missing_official_rank_keeps_synthetic_fixture_unchanged(self) -> None:
        rows = selected_rows()
        rows[0].pop("official_intelligence_rank")
        plan = {"selected_models": rows}
        ENVELOPE._assign_intelligence_ranked_roles(
            SimpleNamespace(_roles=roles),
            plan,
        )
        self.assertEqual(plan["selected_models"], rows)
        self.assertNotIn("role_assignment_policy", plan)

    def test_duplicate_selected_model_fails_closed(self) -> None:
        rows = selected_rows()
        rows[-1]["model"] = rows[0]["model"]
        plan = {"selected_models": rows}
        with self.assertRaisesRegex(
            ENVELOPE.ExpertTaskEnvelopeError,
            "model identities are not unique",
        ):
            ENVELOPE._assign_intelligence_ranked_roles(
                SimpleNamespace(_roles=roles),
                plan,
            )


if __name__ == "__main__":
    unittest.main()
