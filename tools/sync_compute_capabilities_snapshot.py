#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://raw.githubusercontent.com/a15280020511/compute-simulation-center/main/compute-center/compute-capabilities.json"
TARGET = Path("contracts/compute-capabilities.snapshot.json")

request = Request(URL, headers={"Accept": "application/json", "User-Agent": "decision-system-governance-maintenance"})
with urlopen(request, timeout=30) as response:
    raw = response.read()

if len(raw) > 1_000_000:
    raise SystemExit("compute capability snapshot exceeds maintenance size limit")
value = json.loads(raw.decode("utf-8"))
if value.get("schema_version") != "compute-capabilities-v9":
    raise SystemExit("unexpected compute capability schema version")
if value.get("operation_count") != 31:
    raise SystemExit("compute operation count must be 31")
if value.get("managed_mode_count") != 135 or value.get("effective_managed_mode_count") != 196:
    raise SystemExit("compute managed mode counts do not match accepted production catalog")
operations = {str(row.get("id") or "") for row in value.get("operations") or []}
if "large_scale_data_intelligence" not in operations:
    raise SystemExit("large_scale_data_intelligence is missing from compute catalog")
limits = value.get("limits") or {}
expected_limits = {
    "large_scale_records": 50000,
    "large_scale_candidate_pairs": 2000000,
    "large_scale_events": 50000,
    "large_scale_graph_nodes": 10000,
    "large_scale_graph_edges": 100000,
    "large_scale_numeric_rows": 25000,
    "large_scale_numeric_columns": 100,
}
for key, expected in expected_limits.items():
    if limits.get(key) != expected:
        raise SystemExit(f"compute capability limit mismatch: {key}")
TARGET.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "PASS", "target": str(TARGET), "operation_count": 31, "managed_mode_count": 135, "source": URL}))
