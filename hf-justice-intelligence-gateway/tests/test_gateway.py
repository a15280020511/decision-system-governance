from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hf_justice_gateway", ROOT / "gateway.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def sample_export() -> dict:
    return {
        "schema_version": "governance-prc-justice-derived-export-v1",
        "producer_repository": "a15280020511/evidence-data-center",
        "producer_commit": "a" * 40,
        "source_run_id": "31100000000",
        "as_of_date": "2026-08-07",
        "record_count": 1,
        "records": [{
            "record_id": "jintel:" + "a" * 40,
            "as_of_date": "2026-08-07",
            "event_date": "2026-08-07",
            "institution_type": "procuratorate",
            "institution_name": "公开检察机关",
            "region": "福建",
            "industry_or_case_domain": "cyber_and_data",
            "signal_type": "case_practice",
            "subject_type": "technology",
            "capability_ids": ["electronic-data-forensics"],
            "technology_terms": ["电子数据取证"],
            "legal_domains": ["刑事诉讼"],
            "procedural_stage": "审查起诉",
            "lifecycle_stage": "FIRST_PRACTICE",
            "trend_direction": "INSUFFICIENT_DATA",
            "summary": "公开案件显示电子数据取证能力在该案件中实际出现。",
            "practice_standard_summary": "强调完整性与技术性审查。",
            "doctrine_or_enforcement_summary": None,
            "relationships": [],
            "confidence": "MEDIUM_HIGH",
            "evidence_ref_ids": ["evref:" + "b" * 64],
            "model_transform": {"provider":"cloudflare","method":"browser-rendering-json","schema_version":"prc-justice-derived-intelligence-record-v1"},
            "safety": {
                "public_or_authorized": True,
                "raw_source_text_stored": False,
                "raw_source_url_stored": False,
                "raw_model_response_stored": False,
                "personal_targeting": False,
                "secret_operational_detail": False,
                "evasion_or_anti_forensics": False,
            },
        }],
        "raw_source_text_included": False,
        "raw_source_url_included": False,
        "raw_model_response_included": False,
        "personal_data_included": False,
        "secret_operational_details_included": False,
        "evasion_or_anti_forensics_included": False,
        "evidence_reference_resolution_owner": "a15280020511/evidence-data-center",
        "storage_gateway_owner": "a15280020511/decision-system-governance",
        "direct_huggingface_write": False,
    }


class JusticeGatewayTests(unittest.TestCase):
    def test_contract_is_private_and_derived_only(self) -> None:
        contract = MODULE.validate_contract()
        self.assertEqual(contract["repository"]["visibility"], "private")
        self.assertTrue(contract["boundaries"]["derived_structured_records_only"])
        self.assertFalse(contract["boundaries"]["raw_web_page_text_allowed"])
        self.assertFalse(contract["boundaries"]["raw_source_url_allowed"])
        self.assertFalse(contract["boundaries"]["raw_model_response_allowed"])
        self.assertFalse(contract["boundaries"]["business_centers_direct_huggingface_access_allowed"])

    def test_bootstrap_files_expose_no_raw_storage(self) -> None:
        files = MODULE._bootstrap_files()
        layout = json.loads(files["schema/dataset-layout-v1.json"])
        self.assertTrue(layout["append_only_batches"])
        self.assertFalse(layout["raw_source_storage"])
        self.assertEqual(len(layout["sections"]), 12)

    def test_valid_export_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "export.json"
            path.write_text(json.dumps(sample_export(), ensure_ascii=False), encoding="utf-8")
            validated = MODULE.validate_export(path)
            self.assertEqual(validated["record_count"], 1)
            self.assertEqual(validated["records"][0]["confidence"], "MEDIUM_HIGH")

    def test_raw_url_is_rejected(self) -> None:
        value = sample_export()
        value["records"][0]["source_url"] = "https://example.com"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "export.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(MODULE.JusticeGatewayError):
                MODULE.validate_export(path)

    def test_unsafe_safety_flag_is_rejected(self) -> None:
        value = sample_export()
        value["records"][0]["safety"]["secret_operational_detail"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "export.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(MODULE.JusticeGatewayError):
                MODULE.validate_export(path)


if __name__ == "__main__":
    unittest.main()
