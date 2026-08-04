from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

MODULE_PATH = Path(__file__).resolve().parents[1] / "gateway.py"
SPEC = importlib.util.spec_from_file_location("governance_baseline_gateway", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ComputeBaselineGatewayTests(unittest.TestCase):
    def test_contract_assigns_storage_to_governance(self) -> None:
        result = MODULE.validate_contracts()
        baseline = result["topology"]["compute_baseline"]
        self.assertEqual(
            baseline["storage_gateway_owner"],
            "a15280020511/decision-system-governance",
        )
        self.assertEqual(
            baseline["data_producer"],
            "a15280020511/evidence-data-center",
        )
        self.assertEqual(
            baseline["beneficiary_center"],
            "a15280020511/compute-simulation-center",
        )
        self.assertFalse(baseline["compute_direct_network_access_allowed"])
        self.assertFalse(baseline["knowledge_graph_allowed"])
        self.assertFalse(baseline["knowledge_base_allowed"])

    def test_health_ticket_is_accepted_without_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {
                "issue": {
                    "number": 9,
                    "title": "[baseline]",
                    "body": json.dumps(
                        {
                            "schema_version": "governance-baseline-ticket-v1",
                            "operation": "health",
                        }
                    ),
                },
                "sender": {"login": "a15280020511"},
            }
            event_path = root / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            result = MODULE.prepare(event_path, root / "out")
            self.assertEqual(result["operation"], "health")
            self.assertEqual(result["source_run_id"], 0)
            self.assertEqual(result["artifact_name"], "")

    def test_non_owner_ticket_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {
                "issue": {
                    "number": 9,
                    "title": "[baseline]",
                    "body": json.dumps(
                        {
                            "schema_version": "governance-baseline-ticket-v1",
                            "operation": "health",
                        }
                    ),
                },
                "sender": {"login": "someone-else"},
            }
            path = root / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.GatewayError, "repository owner"):
                MODULE.prepare(path, root / "out")

    def test_numeric_manifest_and_parquet_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table_path = root / "observations.parquet"
            schema = pa.schema(
                [
                    pa.field("provenance_id", pa.uint64(), nullable=False),
                    pa.field("value", pa.float64(), nullable=False),
                ]
            )
            table = pa.Table.from_arrays(
                [
                    pa.array([1, 2], type=pa.uint64()),
                    pa.array([2.5, 3.5], type=pa.float64()),
                ],
                schema=schema,
            )
            pq.write_table(table, table_path, compression="zstd", use_dictionary=False)
            file_sha = hashlib.sha256(table_path.read_bytes()).hexdigest()
            manifest = {
                "schema_version": "governance-baseline-export-v1",
                "producer_repository": "a15280020511/evidence-data-center",
                "source_run_id": 123,
                "batch_id": "batch-123",
                "mode": "append_batch",
                "numeric_only": True,
                "raw_text_included": False,
                "control_json_for_hf": False,
                "files": [
                    {
                        "table_id": "observations",
                        "path": "observations.parquet",
                        "sha256": file_sha,
                        "rows": 2,
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            expected_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            control = MODULE.validate_contracts()
            parsed, rows = MODULE._validate_manifest(root, expected_sha, control["contract"])
            self.assertEqual(parsed["batch_id"], "batch-123")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][2].num_rows, 2)

    def test_text_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table_path = root / "observations.parquet"
            schema = pa.schema([pa.field("text", pa.string(), nullable=False)])
            table = pa.Table.from_arrays([pa.array(["bad"], type=pa.string())], schema=schema)
            pq.write_table(table, table_path)
            manifest = {
                "schema_version": "governance-baseline-export-v1",
                "producer_repository": "a15280020511/evidence-data-center",
                "source_run_id": 123,
                "batch_id": "batch-123",
                "mode": "append_batch",
                "numeric_only": True,
                "raw_text_included": False,
                "control_json_for_hf": False,
                "files": [
                    {
                        "table_id": "observations",
                        "path": "observations.parquet",
                        "sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
                        "rows": 1,
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            expected_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            control = MODULE.validate_contracts()
            with self.assertRaisesRegex(MODULE.GatewayError, "non-numeric column"):
                MODULE._validate_manifest(root, expected_sha, control["contract"])


if __name__ == "__main__":
    unittest.main()
