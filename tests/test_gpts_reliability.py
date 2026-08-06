from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELIABILITY_SOURCE = (
    ROOT / "control-plane" / "gpts_reliability.py"
).read_text(encoding="utf-8")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("test_gpts_reliability_control", ROOT / "control-plane" / "control_plane.py")
RELIABILITY = _load(
    "test_gpts_reliability_adapter", ROOT / "control-plane" / "gpts_reliability.py"
)
RELIABILITY.patch(CONTROL)


class GPTsReliabilityTests(unittest.TestCase):
    def _packet(self, schema: str, request_id: str | None = None) -> dict:
        packet = {
            "schema_version": schema,
            "route": "compute",
            "ticket": {
                "operation": "descriptive_statistics",
                "inputs": {"data": [1, 2, 3]},
            },
        }
        if request_id is not None:
            packet["client_request_id"] = request_id
        return packet

    def _prepare_packet(self, packet: dict, issue_number: int) -> tuple[int, dict, dict | None]:
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
                json.dumps(packet, ensure_ascii=False), encoding="utf-8"
            )
            result = CONTROL.prepare(
                argparse.Namespace(
                    event_path=str(event_path), output_dir=str(output_dir)
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

    def _legacy_issue_153_packet(self) -> dict:
        return {
            "schema_version": "4",
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "research",
            "ticket": {
                "title": "俄罗斯对主要外部方向的战略研判",
                "user_request": (
                    "调查分析俄罗斯对乌克兰、欧洲、中国和美国的当前策略"
                ),
                "requirements": [
                    "区分事实、推断和未知",
                    "提出竞争性假设和反向解释",
                ],
                "output_language": "zh-CN",
            },
            "wait_seconds": 2700,
        }

    def _canonical_issue_153_packet(self) -> dict:
        return {
            "schema_version": RELIABILITY.V4,
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "expert",
            "ticket": {
                "objective": "俄罗斯对主要外部方向的战略研判",
                "pipeline": "expert-team",
                "task": {
                    "question": (
                        "调查分析俄罗斯对乌克兰、欧洲、中国和美国的当前策略"
                    ),
                    "requirements": [
                        "区分事实、推断和未知",
                        "提出竞争性假设和反向解释",
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
            "wait_seconds": 2700,
        }

    def test_v3_and_v4_business_fingerprint_is_stable(self) -> None:
        request_id = "8beae650-3676-4a76-b8a4-e45f76ccf822"
        v3 = json.dumps(self._packet(RELIABILITY.V3), sort_keys=True)
        v4 = json.dumps(self._packet(RELIABILITY.V4, request_id), sort_keys=True)
        self.assertEqual(CONTROL._request_fingerprint(v3), CONTROL._request_fingerprint(v4))

    def test_downstream_status_requires_control_received_evidence(self) -> None:
        self.assertIn('"read_after_write_verified": None', RELIABILITY_SOURCE)
        self.assertIn('"CONTROL_RECEIVED" if client_request_id else None', RELIABILITY_SOURCE)
        self.assertNotIn('"read_after_write_verified": bool(client_request_id)', RELIABILITY_SOURCE)

    def test_v4_prepare_strips_client_metadata_from_child_ticket(self) -> None:
        request_id = "8beae650-3676-4a76-b8a4-e45f76ccf822"
        packet = self._packet(RELIABILITY.V4, request_id)
        result, status, child = self._prepare_packet(packet, 7)
        self.assertEqual(result, 0)
        self.assertIsNotNone(child)
        assert child is not None
        self.assertTrue(status["accepted"])
        self.assertEqual(status["client_request_id"], request_id)
        self.assertEqual(status["request_schema_version"], RELIABILITY.V4)
        self.assertEqual(child["task_id"], "gov-7-compute")
        self.assertNotIn("client_request_id", child)

    def test_v4_rejects_missing_or_invalid_client_request_id(self) -> None:
        for request_id in (None, "not-a-uuid"):
            with self.subTest(request_id=request_id):
                packet = self._packet(RELIABILITY.V4, request_id)
                result, status, child = self._prepare_packet(packet, 8)
                self.assertEqual(result, 2)
                self.assertFalse(status["accepted"])
                self.assertIn("client_request_id", status["reason"])
                self.assertIsNone(child)

    def test_issue_153_exact_legacy_shape_is_repaired_and_audited(self) -> None:
        result, status, child = self._prepare_packet(
            self._legacy_issue_153_packet(), 153
        )
        self.assertEqual(result, 0)
        self.assertTrue(status["accepted"])
        self.assertEqual(status["request_schema_version_original"], "4")
        self.assertEqual(status["request_schema_version"], RELIABILITY.V4)
        self.assertTrue(status["compatibility_normalized"])
        self.assertEqual(
            status["compatibility_normalizations"],
            [
                "schema_version:4->governance-control-ticket-v4",
                "route:research->expert",
                "ticket:legacy-expert->governed-expert",
            ],
        )
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child["task_id"], "gov-153-expert")
        self.assertEqual(child["pipeline"], "expert-team")
        self.assertEqual(child["task"]["language"], "zh-CN")
        self.assertEqual(
            child["task"]["question"],
            "调查分析俄罗斯对乌克兰、欧洲、中国和美国的当前策略",
        )
        self.assertNotIn("title", child)
        self.assertNotIn("user_request", child)
        self.assertNotIn("output_language", child)
        self.assertNotIn("client_request_id", child)

    def test_issue_153_alias_and_canonical_ticket_share_fingerprint(self) -> None:
        legacy = json.dumps(
            self._legacy_issue_153_packet(), ensure_ascii=False, sort_keys=True
        )
        canonical = json.dumps(
            self._canonical_issue_153_packet(), ensure_ascii=False, sort_keys=True
        )
        self.assertEqual(
            CONTROL._request_fingerprint(legacy),
            CONTROL._request_fingerprint(canonical),
        )

    def test_unknown_research_shape_remains_rejected(self) -> None:
        packet = {
            "schema_version": "4",
            "client_request_id": "80c1fa7f-b390-408f-9379-59e14eaf7308",
            "route": "research",
            "ticket": {"query": "ambiguous research request"},
        }
        result, status, child = self._prepare_packet(packet, 154)
        self.assertEqual(result, 2)
        self.assertFalse(status["accepted"])
        self.assertIn("exact legacy expert ticket fields", status["reason"])
        self.assertIsNone(child)

    def test_other_route_aliases_remain_rejected(self) -> None:
        for route in sorted(RELIABILITY.REJECTED_ROUTE_ALIASES):
            with self.subTest(route=route):
                packet = self._packet("4", "80c1fa7f-b390-408f-9379-59e14eaf7308")
                packet["route"] = route
                result, status, child = self._prepare_packet(packet, 155)
                self.assertEqual(result, 2)
                self.assertFalse(status["accepted"])
                self.assertIn("ambiguous", status["reason"])
                self.assertIsNone(child)


if __name__ == "__main__":
    unittest.main()
