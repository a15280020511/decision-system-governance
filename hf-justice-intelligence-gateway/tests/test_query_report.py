from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hf_justice_query_report", ROOT / "query_report.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class QueryReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            {
                "record_id": "jintel:" + "a" * 40,
                "as_of_date": "2026-08-07",
                "event_date": "2026-08-07",
                "institution_type": "public_security",
                "region": "福建",
                "signal_type": "case_practice",
                "subject_type": "technology",
                "capability_ids": ["electronic-data-forensics"],
                "technology_terms": ["电子数据取证"],
                "legal_domains": ["刑事诉讼"],
                "confidence": "HIGH",
            },
            {
                "record_id": "jintel:" + "b" * 40,
                "as_of_date": "2026-08-07",
                "event_date": "2026-08-06",
                "institution_type": "procuratorate",
                "region": "浙江",
                "signal_type": "policy_and_strategy",
                "subject_type": "institutional_capacity",
                "capability_ids": ["data-intelligence-and-correlation"],
                "technology_terms": ["数智检察"],
                "legal_domains": ["法律监督"],
                "confidence": "MEDIUM_HIGH",
            },
        ]

    def test_capability_region_and_institution_filters(self) -> None:
        result = MODULE.filter_records(
            self.rows,
            {
                "days": 365,
                "institution_type": "public_security",
                "region": "福建",
                "capability_id": "electronic-data-forensics",
                "limit": 50,
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["technology_terms"], ["电子数据取证"])

    def test_technology_and_legal_domain_filters(self) -> None:
        result = MODULE.filter_records(
            self.rows,
            {"days": 365, "technology_term": "数智", "legal_domain": "法律监督", "limit": 50},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["institution_type"], "procuratorate")

    def test_unknown_filter_is_rejected(self) -> None:
        with self.assertRaises(MODULE.QueryError):
            MODULE.filter_records(self.rows, {"days": 30, "source_url": "forbidden"})

    def test_result_limit_is_bounded(self) -> None:
        with self.assertRaises(MODULE.QueryError):
            MODULE.filter_records(self.rows, {"days": 30, "limit": 101})


if __name__ == "__main__":
    unittest.main()
