from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
COPILOT = ROOT / "governance-copilot"
CONTROL = ROOT / "control-plane"
TOOLS = ROOT / "tools"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ENVELOPE = _load(
    "expert_task_envelope_contract_test",
    COPILOT / "expert_task_envelope.py",
)
RUNTIME = _load(
    "expert_task_envelope_control_runtime_test",
    CONTROL / "resilient_control.py",
)
REPAIR = _load(
    "expert_task_envelope_repair_runtime_test",
    TOOLS / "repair_expert_child_plan.py",
)


def issue_172_ticket() -> dict:
    return {
        "task": {
            "question": (
                "调查并分析截至2026年8月6日俄罗斯分别对乌克兰、欧洲、中国和"
                "美国采取的总体策略。"
            ),
            "requirements": [
                "不得把推断包装成事实",
                "优先使用官方文件和原始讲话",
                "区分已确认事实、公开立场、推断和未知",
            ],
            "language": "zh-CN",
        }
    }


class ExpertTaskEnvelopeCompatibilityTests(unittest.TestCase):
    def test_issue_172_uses_frozen_16384_context_floor(self) -> None:
        ticket = issue_172_ticket()
        self.assertEqual(ENVELOPE.required_context_tokens(ticket), 16_384)
        self.assertGreater(ENVELOPE.required_context_tokens(ticket), 8_969)

    def test_new_task_and_repair_paths_use_same_envelope_function(self) -> None:
        ticket = issue_172_ticket()
        expected = ENVELOPE.required_context_tokens(ticket)
        self.assertEqual(RUNTIME.EXPERT_SELECTOR._required_context_tokens(ticket), expected)
        self.assertEqual(REPAIR.SELECTOR._required_context_tokens(ticket), expected)
        self.assertEqual(
            RUNTIME.TASK_ENVELOPE.EXPERT_RUNTIME_SCHEMA_VERSION,
            "v5-minimal-task-envelope-1",
        )
        self.assertEqual(
            REPAIR.TASK_ENVELOPE.MINIMUM_CONTEXT_LENGTH,
            16_384,
        )
        self.assertEqual(
            RUNTIME.EXPERT_SELECTOR.MINIMUM_QUALIFIED_PROVIDER_COUNT,
            1,
        )
        self.assertEqual(
            REPAIR.SELECTOR.MINIMUM_QUALIFIED_PROVIDER_COUNT,
            1,
        )

    def test_single_zdr_provider_candidate_is_accepted(self) -> None:
        selector = SimpleNamespace(
            _qualify_candidate=lambda candidate, token, context: {
                **candidate,
                "qualified_provider_count": 1,
            }
        )
        ENVELOPE.patch_selector(selector)
        qualified = selector._qualify_candidate({"model_id": "a/pro"}, "", 16_384)
        self.assertIsNotNone(qualified)
        assert qualified is not None
        self.assertEqual(qualified["qualified_provider_count"], 1)

    def test_zero_provider_candidate_is_rejected(self) -> None:
        selector = SimpleNamespace(
            _qualify_candidate=lambda candidate, token, context: {
                **candidate,
                "qualified_provider_count": 0,
            }
        )
        ENVELOPE.patch_selector(selector)
        self.assertIsNone(
            selector._qualify_candidate({"model_id": "a/pro"}, "", 16_384)
        )

    def test_two_provider_candidate_is_accepted(self) -> None:
        selector = SimpleNamespace(
            _qualify_candidate=lambda candidate, token, context: {
                **candidate,
                "qualified_provider_count": 2,
            }
        )
        ENVELOPE.patch_selector(selector)
        qualified = selector._qualify_candidate({"model_id": "a/pro"}, "", 16_384)
        self.assertIsNotNone(qualified)
        assert qualified is not None
        self.assertEqual(qualified["qualified_provider_count"], 2)

    def test_provider_redundancy_patch_is_idempotent(self) -> None:
        calls = {"count": 0}

        def qualify(candidate, token, context):
            del token, context
            calls["count"] += 1
            return {**candidate, "qualified_provider_count": 2}

        selector = SimpleNamespace(_qualify_candidate=qualify)
        ENVELOPE.patch_selector(selector)
        ENVELOPE.patch_selector(selector)
        selector._qualify_candidate({"model_id": "a/pro"}, "", 16_384)
        self.assertEqual(calls["count"], 1)

    def test_large_task_keeps_conservative_character_bound(self) -> None:
        ticket = {
            "task": {
                "question": "x" * 20_000,
                "requirements": [],
                "language": "zh-CN",
            }
        }
        self.assertGreater(
            ENVELOPE.required_context_tokens(ticket),
            ENVELOPE.MINIMUM_CONTEXT_LENGTH,
        )


if __name__ == "__main__":
    unittest.main()
