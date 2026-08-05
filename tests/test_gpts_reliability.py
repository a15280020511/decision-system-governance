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

    def test_v3_and_v4_business_fingerprint_is_stable(self) -> None:
        request_id = "8beae650-3676-4a76-b8a4-e45f76ccf822"
        v3 = json.dumps(self._packet(RELIABILITY.V3), sort_keys=True)
        v4 = json.dumps(self._packet(RELIABILITY.V4, request_id), sort_keys=True)
        self.assertEqual(CONTROL._request_fingerprint(v3), CONTROL._request_fingerprint(v4))

    def test_v4_prepare_strips_client_metadata_from_child_ticket(self) -> None:
        request_id = "8beae650-3676-4a76-b8a4-e45f76ccf822"
        packet = self._packet(RELIABILITY.V4, request_id)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "event.json"
            output_dir = root / "out"
            event_path.write_text(
                json.dumps(
                    {
                        "issue": {
                            "number": 7,
                            "title": "[control]",
                            "body": json.dumps(packet),
                        },
                        "sender": {"login": CONTROL.OWNER},
                        "repository": {
                            "full_name": "a15280020511/decision-system-governance",
                            "owner": {"login": CONTROL.OWNER},
                        },
                    }
                ),
                encoding="utf-8",
            )
            output_dir.mkdir()
            (output_dir / "selected-request.md").write_text(
                json.dumps(packet), encoding="utf-8"
            )
            result = CONTROL.prepare(
                argparse.Namespace(
                    event_path=str(event_path), output_dir=str(output_dir)
                )
            )
            self.assertEqual(result, 0)
            status = json.loads(
                (output_dir / "prepare-status.json").read_text(encoding="utf-8")
            )
            child = json.loads(
                (output_dir / "child-ticket.json").read_text(encoding="utf-8")
            )
            self.assertTrue(status["accepted"])
            self.assertEqual(status["client_request_id"], request_id)
            self.assertEqual(status["request_schema_version"], RELIABILITY.V4)
            self.assertEqual(child["task_id"], "gov-7-compute")
            self.assertNotIn("client_request_id", child)

    def test_v4_rejects_missing_or_invalid_client_request_id(self) -> None:
        for request_id in (None, "not-a-uuid"):
            with self.subTest(request_id=request_id):
                packet = self._packet(RELIABILITY.V4, request_id)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    event_path = root / "event.json"
                    output_dir = root / "out"
                    event_path.write_text(
                        json.dumps(
                            {
                                "issue": {
                                    "number": 8,
                                    "title": "[control]",
                                    "body": json.dumps(packet),
                                },
                                "sender": {"login": CONTROL.OWNER},
                                "repository": {
                                    "full_name": "a15280020511/decision-system-governance",
                                    "owner": {"login": CONTROL.OWNER},
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                    output_dir.mkdir()
                    (output_dir / "selected-request.md").write_text(
                        json.dumps(packet), encoding="utf-8"
                    )
                    result = CONTROL.prepare(
                        argparse.Namespace(
                            event_path=str(event_path), output_dir=str(output_dir)
                        )
                    )
                    status = json.loads(
                        (output_dir / "prepare-status.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(result, 2)
                    self.assertFalse(status["accepted"])
                    self.assertIn("client_request_id", status["reason"])
                    self.assertFalse((output_dir / "child-ticket.json").exists())


if __name__ == "__main__":
    unittest.main()
