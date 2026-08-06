from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load(
    "test_structural_route_control",
    ROOT / "control-plane" / "control_plane.py",
)
RELIABILITY = _load(
    "test_structural_route_reliability",
    ROOT / "control-plane" / "gpts_reliability.py",
)
INGRESS = _load(
    "test_structural_route_adapter",
    ROOT / "control-plane" / "gpts_ingress_normalization.py",
)
RELIABILITY.patch(CONTROL)
INGRESS.patch(CONTROL)


class StructuralRouteResolutionTests(unittest.TestCase):
    def _prepare_packet(
        self, packet: dict, issue_number: int
    ) -> tuple[int, dict, dict | None]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "event.json"
            output_dir = root / "out"
            event_path.write_text(
                json.dumps(
                    {
                        "issue": {
                            "number": issue_number,
                            "title": "[control]",
                            "body": json.dumps(packet, ensure_ascii=False),
                        },
                        "sender": {"login": CONTROL.OWNER},
                        "repository": {
                            "full_name": "a15280020511/decision-system-governance",
                            "owner": {"login": CONTROL.OWNER},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output_dir.mkdir()
            (output_dir / "selected-request.md").write_text(
                json.dumps(packet, ensure_ascii=False),
                encoding="utf-8",
            )
            result = CONTROL.prepare(
                argparse.Namespace(
                    event_path=str(event_path),
                    output_dir=str(output_dir),
                )
            )
            status = json.loads(
                (output_dir / "prepare-status.json").read_text(encoding="utf-8")
            )
            child_path = output_dir / "child-ticket.json"
            child = (
                json.loads(child_path.read_text(encoding="utf-8"))
                if child_path.exists()
                else None
            )
            return result, status, child

    def _issue_172_packet(self) -> dict:
        return {
            "client_request_id": "015e7336-4238-4468-a3f7-dc439f5551b9",
            "route": "strategic_intelligence_analysis",
            "schema_version": INGRESS.V4,
            "ticket": {
                "constraints": [
                    "不得把推断包装成事实",
                    "不得声称掌握秘密意图或未公开决策",
                    "使用中文输出完整报告",
                ],
                "evidence_requirements": [
                    "优先使用官方文件、原始讲话、法规和国际组织文件",
                    "区分已确认事实、公开立场、推断和未知",
                ],
                "language": "zh-CN",
                "output_structure": [
                    "核验结论",
                    "已确认事实",
                    "俄罗斯对乌克兰的策略",
                    "俄罗斯对欧洲的策略",
                    "俄罗斯对中国的策略",
                    "俄罗斯对美国的策略",
                    "来源清单",
                ],
                "scope": {
                    "actors": ["俄罗斯", "乌克兰", "欧洲", "中国", "美国"],
                    "as_of_date": "2026-08-06",
                    "time_horizon": ["短期0-12个月", "中期1-3年", "长期3年以上"],
                },
                "task": (
                    "调查并分析截至2026年8月6日俄罗斯分别对乌克兰、欧洲、"
                    "中国和美国采取的总体策略。"
                ),
            },
            "wait_seconds": 60,
        }

    def test_issue_172_is_resolved_by_structure_not_route_name(self) -> None:
        result, status, child = self._prepare_packet(self._issue_172_packet(), 172)
        self.assertEqual(result, 0)
        self.assertTrue(status["accepted"])
        self.assertEqual(status["route"], "expert")
        self.assertEqual(status["wait_seconds"], 60)
        self.assertEqual(
            status["compatibility_normalizations"],
            [
                "route:strategic_intelligence_analysis->expert",
                "ticket:strategic-analysis->governed-expert",
            ],
        )
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child["task_id"], "gov-172-expert")
        self.assertEqual(child["pipeline"], "expert-team")
        self.assertEqual(child["task"]["language"], "zh-CN")
        self.assertIn("不得把推断包装成事实", child["task"]["requirements"])
        self.assertTrue(
            any(
                item.startswith("输出结构必须依次包含：")
                for item in child["task"]["requirements"]
            )
        )
        self.assertTrue(
            any(
                item.startswith("分析范围（必须遵守）：")
                for item in child["task"]["requirements"]
            )
        )

    def test_future_route_label_with_same_structure_is_also_accepted(self) -> None:
        packet = self._issue_172_packet()
        packet["route"] = "geopolitical_policy_assessment_v27"
        packet["client_request_id"] = "1509a5f2-d2d4-49f0-a6ac-2f91f78cb80e"
        result, status, child = self._prepare_packet(packet, 173)
        self.assertEqual(result, 0)
        self.assertTrue(status["accepted"])
        self.assertEqual(status["route"], "expert")
        self.assertIsNotNone(child)

    def test_unknown_route_with_compute_structure_maps_to_compute(self) -> None:
        packet = {
            "schema_version": INGRESS.V4,
            "client_request_id": "b9fd5ab5-6fe5-4ce7-91ef-e77bc6e3f078",
            "route": "quantitative_policy_simulation_v2",
            "ticket": {
                "operation": "descriptive_statistics",
                "inputs": {"data": [1, 2, 3]},
            },
            "wait_seconds": 120,
        }
        result, status, child = self._prepare_packet(packet, 174)
        self.assertEqual(result, 0)
        self.assertEqual(status["route"], "compute")
        self.assertIsNotNone(child)

    def test_unknown_route_with_explicit_connector_plan_maps_to_intelligence(self) -> None:
        packet = {
            "schema_version": INGRESS.V4,
            "client_request_id": "9ee04a25-82ab-476d-89c2-f047e751ea57",
            "route": "public_source_acquisition_v3",
            "ticket": {
                "objective": "Fetch one public indicator",
                "data_policy": {
                    "classification": "public",
                    "contains_personal_data": False,
                },
                "requests": [
                    {
                        "request_id": "req-001",
                        "connector_id": "world-bank",
                        "parameters": {"indicator": "NY.GDP.MKTP.CD"},
                    }
                ],
                "acceptance": {
                    "require_all": True,
                    "minimum_successful_requests": 1,
                },
            },
            "wait_seconds": 2400,
        }
        result, status, child = self._prepare_packet(packet, 175)
        self.assertEqual(result, 0)
        self.assertEqual(status["route"], "intelligence")
        self.assertIsNotNone(child)

    def test_canonical_expert_route_accepts_strategic_representation(self) -> None:
        packet = self._issue_172_packet()
        packet["route"] = "expert"
        packet["client_request_id"] = "3f1c7dfd-5b35-427a-9ad8-2d9cfc4286d1"
        result, status, child = self._prepare_packet(packet, 176)
        self.assertEqual(result, 0)
        self.assertEqual(status["route"], "expert")
        self.assertEqual(
            status["compatibility_normalizations"],
            ["ticket:strategic-analysis->governed-expert"],
        )
        self.assertIsNotNone(child)

    def test_malformed_strategic_fields_fail_closed(self) -> None:
        packet = self._issue_172_packet()
        packet["client_request_id"] = "68e80d78-7b43-43ce-81d1-1fc39c9ca01b"
        packet["ticket"]["constraints"] = {"unexpected": True}
        result, status, child = self._prepare_packet(packet, 177)
        self.assertEqual(result, 2)
        self.assertFalse(status["accepted"])
        self.assertIn("constraints", status["reason"])
        self.assertIsNone(child)

    def test_ambiguous_unknown_route_still_fails_closed(self) -> None:
        packet = {
            "schema_version": INGRESS.V4,
            "client_request_id": "78acfb40-1a1d-48ba-a2d8-c8dcff8b5f3a",
            "route": "do_everything_v1",
            "ticket": {
                "query": "Find current evidence and analyze it",
                "requirements": ["Use authoritative sources"],
                "language": "zh-CN",
            },
            "wait_seconds": 120,
        }
        result, status, child = self._prepare_packet(packet, 178)
        self.assertEqual(result, 2)
        self.assertFalse(status["accepted"])
        self.assertIn("explicit connector request plan", status["reason"])
        self.assertIsNone(child)

    def test_alias_and_canonical_packet_share_fingerprint(self) -> None:
        alias_packet = self._issue_172_packet()
        normalized, changes, error = INGRESS.normalize_packet(alias_packet)
        self.assertFalse(error)
        self.assertTrue(changes)
        alias = json.dumps(alias_packet, ensure_ascii=False, sort_keys=True)
        canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        self.assertEqual(
            CONTROL._request_fingerprint(alias),
            CONTROL._request_fingerprint(canonical),
        )


if __name__ == "__main__":
    unittest.main()
