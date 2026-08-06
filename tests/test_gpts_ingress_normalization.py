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
    "test_generic_ingress_control",
    ROOT / "control-plane" / "control_plane.py",
)
RELIABILITY = _load(
    "test_generic_ingress_reliability",
    ROOT / "control-plane" / "gpts_reliability.py",
)
INGRESS = _load(
    "test_generic_ingress_adapter",
    ROOT / "control-plane" / "gpts_ingress_normalization.py",
)
RELIABILITY.patch(CONTROL)
INGRESS.patch(CONTROL)


class GenericIngressNormalizationTests(unittest.TestCase):
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

    def _issue_162_packet(self) -> dict:
        return {
            "schema_version": "4.0",
            "client_request_id": "3f0da28a-4bb5-48ee-a229-9fd262595d34",
            "route": "analysis",
            "wait_seconds": 45,
            "ticket": {
                "language": "zh-CN",
                "title": "俄罗斯当前对主要外部方向的战略研判",
                "user_request": (
                    "调查并分析俄罗斯当前分别对乌克兰、欧洲、中国和美国采取的策略"
                ),
                "requirements": [
                    "核验最新公开资料",
                    "区分事实、公开立场、推断和未知",
                ],
            },
        }

    def _canonical_issue_162_packet(self) -> dict:
        return {
            "schema_version": INGRESS.V4,
            "client_request_id": "3f0da28a-4bb5-48ee-a229-9fd262595d34",
            "route": "expert",
            "wait_seconds": 60,
            "ticket": {
                "objective": "俄罗斯当前对主要外部方向的战略研判",
                "pipeline": "expert-team",
                "task": {
                    "question": (
                        "调查并分析俄罗斯当前分别对乌克兰、欧洲、中国和美国采取的策略"
                    ),
                    "requirements": [
                        "核验最新公开资料",
                        "区分事实、公开立场、推断和未知",
                    ],
                    "language": "zh-CN",
                },
                "execution_acceptance": [
                    "发布完整最终综合报告",
                    "区分事实、公开立场、推断和未知",
                ],
                "evidence": [],
                "approved_budget": {
                    "calls": 8,
                    "maximum_recovery_calls": 1,
                },
                "private_output": False,
            },
        }

    def test_issue_162_shape_is_repaired_generically(self) -> None:
        result, status, child = self._prepare_packet(self._issue_162_packet(), 162)
        self.assertEqual(result, 0)
        self.assertTrue(status["accepted"])
        self.assertEqual(status["route"], "expert")
        self.assertEqual(status["wait_seconds"], 60)
        self.assertEqual(status["request_schema_version_original"], "4.0")
        self.assertEqual(status["request_schema_version"], INGRESS.V4)
        self.assertEqual(
            status["compatibility_normalizations"],
            [
                "schema_version:4.0->governance-control-ticket-v4",
                "route:analysis->expert",
                "ticket:narrative->governed-expert",
                "wait_seconds:45->60",
            ],
        )
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child["task_id"], "gov-162-expert")
        self.assertEqual(child["pipeline"], "expert-team")
        self.assertEqual(child["task"]["language"], "zh-CN")
        self.assertNotIn("client_request_id", child)
        self.assertNotIn("user_request", child)

    def test_issue_162_alias_and_canonical_packet_share_fingerprint(self) -> None:
        alias = json.dumps(
            self._issue_162_packet(), ensure_ascii=False, sort_keys=True
        )
        canonical = json.dumps(
            self._canonical_issue_162_packet(), ensure_ascii=False, sort_keys=True
        )
        self.assertEqual(
            CONTROL._request_fingerprint(alias),
            CONTROL._request_fingerprint(canonical),
        )

    def test_simulation_alias_with_compute_shape_is_repaired(self) -> None:
        packet = {
            "schema_version": 4.0,
            "client_request_id": "8beae650-3676-4a76-b8a4-e45f76ccf822",
            "route": "simulation",
            "wait_seconds": "30",
            "ticket": {
                "operation": "descriptive_statistics",
                "inputs": {"data": [1, 2, 3]},
            },
        }
        result, status, child = self._prepare_packet(packet, 163)
        self.assertEqual(result, 0)
        self.assertEqual(status["route"], "compute")
        self.assertEqual(status["wait_seconds"], 60)
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child["task_id"], "gov-163-compute")

    def test_api_alias_requires_actual_intelligence_ticket_shape(self) -> None:
        packet = {
            "schema_version": "v4",
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "api",
            "ticket": {
                "objective": "Fetch one public dataset",
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
        result, status, child = self._prepare_packet(packet, 164)
        self.assertEqual(result, 0)
        self.assertEqual(status["route"], "intelligence")
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child["task_id"], "gov-164-intelligence")

    def test_ambiguous_analysis_query_remains_rejected(self) -> None:
        packet = {
            "schema_version": "4.0",
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "analysis",
            "ticket": {
                "query": "Find and analyze current public evidence",
                "requirements": ["Use authoritative sources"],
                "language": "zh-CN",
            },
            "wait_seconds": 120,
        }
        result, status, child = self._prepare_packet(packet, 165)
        self.assertEqual(result, 2)
        self.assertFalse(status["accepted"])
        self.assertIn("explicit connector request plan", status["reason"])
        self.assertIsNone(child)

    def test_non_numeric_wait_value_remains_rejected(self) -> None:
        packet = {
            "schema_version": INGRESS.V4,
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "compute",
            "ticket": {
                "operation": "descriptive_statistics",
                "inputs": {"data": [1, 2, 3]},
            },
            "wait_seconds": "soon",
        }
        result, status, child = self._prepare_packet(packet, 166)
        self.assertEqual(result, 2)
        self.assertFalse(status["accepted"])
        self.assertIn("wait_seconds", status["reason"])
        self.assertIsNone(child)


if __name__ == "__main__":
    unittest.main()
