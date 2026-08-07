#!/usr/bin/env python3
"""Governance-owned Hugging Face gateway for derived PRC justice intelligence.

This gateway never performs model inference. It accepts only sanitized structured
exports produced by Evidence Center after primary verification and semantic
transformation. Raw web/PDF text, raw URLs, raw model responses, targeting data,
secret operational details and evasion/anti-forensics content are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "contract.json"
TOKEN_ENV = "HF_TOKEN"
SAFE_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
EVREF_RE = re.compile(r"^evref:[0-9a-f]{64}$")
RECORD_ID_RE = re.compile(r"^jintel:[0-9a-f]{40}$")
MAX_RECORDS_PER_BATCH = 2000
MAX_EXPORT_BYTES = 10 * 1024 * 1024


class JusticeGatewayError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical(value).encode("utf-8"))


def validate_contract() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("schema_version") != "governance-hf-justice-intelligence-gateway-v1":
        raise JusticeGatewayError("unsupported justice intelligence gateway contract")
    if contract.get("status") != "production-control":
        raise JusticeGatewayError("justice intelligence gateway is not production-control")
    if contract.get("storage_owner") != "a15280020511/decision-system-governance":
        raise JusticeGatewayError("storage owner mismatch")
    if contract.get("producer_repository") != "a15280020511/evidence-data-center":
        raise JusticeGatewayError("producer repository mismatch")
    if contract.get("token_environment_variable") != TOKEN_ENV:
        raise JusticeGatewayError("unexpected token environment variable")
    repo = contract.get("repository")
    if not isinstance(repo, Mapping):
        raise JusticeGatewayError("repository contract missing")
    if repo.get("repo_type") != "dataset" or repo.get("visibility") != "private":
        raise JusticeGatewayError("justice intelligence must use a private dataset")
    if repo.get("repository_variable") != "HF_JUSTICE_INTELLIGENCE_DATASET_REPO":
        raise JusticeGatewayError("unexpected dataset repository variable")
    if not SAFE_PART_RE.fullmatch(str(repo.get("default_repository_name") or "")):
        raise JusticeGatewayError("unsafe default dataset name")
    boundaries = contract.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise JusticeGatewayError("boundaries missing")
    required_true = (
        "gpts_is_only_external_controller",
        "derived_structured_records_only",
        "opaque_evidence_reference_required",
        "immutable_batch_files_required",
    )
    required_false = (
        "business_centers_direct_huggingface_access_allowed",
        "raw_web_page_text_allowed",
        "raw_pdf_text_allowed",
        "raw_source_url_allowed",
        "raw_model_response_allowed",
        "personal_targeting_data_allowed",
        "secret_operational_details_allowed",
        "investigation_evasion_or_anti_forensics_allowed",
        "credentials_or_private_endpoints_allowed",
        "model_inference_in_gateway_allowed",
        "training_allowed",
    )
    if any(boundaries.get(key) is not True for key in required_true):
        raise JusticeGatewayError("required positive boundary missing")
    if any(boundaries.get(key) is not False for key in required_false):
        raise JusticeGatewayError("forbidden capability enabled")
    sections = contract.get("dataset_sections")
    if not isinstance(sections, list) or len(sections) != 12 or len(set(sections)) != 12:
        raise JusticeGatewayError("dataset section contract must contain twelve unique sections")
    return contract


def _record_schema() -> dict[str, Any]:
    return {
        "schema_version": "prc-justice-derived-intelligence-record-v1",
        "required_fields": [
            "record_id","as_of_date","institution_type","signal_type","subject_type",
            "summary","confidence","evidence_ref_ids","model_transform","safety"
        ],
        "forbidden_fields": [
            "source_url","url","raw_text","raw_source_text","raw_pdf_text",
            "raw_model_response","full_text","quote","cookie","credential","secret"
        ],
        "evidence_reference_pattern": "^evref:[0-9a-f]{64}$",
        "record_id_pattern": "^jintel:[0-9a-f]{40}$",
        "storage_class": "derived-structured-only",
    }


def _bootstrap_files() -> dict[str, bytes]:
    contract = validate_contract()
    readme = """---
pretty_name: PRC Justice Intelligence
---

# PRC Justice Intelligence

Governance-owned private dataset for **derived, normalized, structured** PRC justice intelligence.

Stored: normalized capability/technology/practice/doctrine/enforcement records, opaque evidence references, approved trend metrics and report snapshots.

Not stored: raw web/PDF text, raw source URLs, raw model responses, credentials, personal targeting data, secret operational details, investigation-evasion or anti-forensics material.

Primary-source provenance remains in Evidence Center and is resolved by opaque `evref:` identifiers under governance control.
"""
    layout = {
        "schema_version": "prc-justice-intelligence-dataset-layout-v1",
        "sections": contract["dataset_sections"],
        "batch_path": "records/YYYY-MM-DD/<source-run>-<export-sha-prefix>.jsonl",
        "manifest_path": "manifests/YYYY-MM-DD/<source-run>-<export-sha-prefix>.json",
        "append_only_batches": True,
        "raw_source_storage": False,
        "query_keys": ["record_id","as_of_date","institution_type","region","signal_type","subject_type","capability_ids","technology_terms","legal_domains","lifecycle_stage","trend_direction","confidence","evidence_ref_ids"],
    }
    return {
        "README.md": readme.encode("utf-8"),
        "schema/derived-record-v1.json": (json.dumps(_record_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "schema/dataset-layout-v1.json": (json.dumps(layout, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def _identity(api: HfApi, token: str) -> str:
    row = api.whoami(token=token)
    owner = str(row.get("name") or "") if isinstance(row, Mapping) else ""
    if not SAFE_PART_RE.fullmatch(owner):
        raise JusticeGatewayError("Hugging Face identity unavailable or unsafe")
    return owner


def _repo_id(api: HfApi, token: str, contract: Mapping[str, Any]) -> str:
    owner = _identity(api, token)
    repo = contract["repository"]
    variable = str(repo["repository_variable"])
    configured = str(os.getenv(variable) or "").strip()
    value = configured or f"{owner}/{repo['default_repository_name']}"
    parts = value.split("/")
    if len(parts) != 2 or any(not SAFE_PART_RE.fullmatch(part) for part in parts):
        raise JusticeGatewayError(f"invalid repository id in {variable}")
    if parts[0] != owner:
        raise JusticeGatewayError(f"repository owner in {variable} must match authenticated account")
    return value


def _ensure_repo(api: HfApi, token: str, contract: Mapping[str, Any]) -> tuple[str, list[str]]:
    repo_id = _repo_id(api, token, contract)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True, token=token)
    info = api.repo_info(repo_id=repo_id, repo_type="dataset", token=token)
    if bool(getattr(info, "private", False)) is not True:
        raise JusticeGatewayError("justice intelligence dataset must remain private")
    existing = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    operations: list[CommitOperationAdd] = []
    changed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hf-justice-bootstrap-") as temp:
        root = Path(temp)
        for path, payload in sorted(_bootstrap_files().items()):
            same = False
            if path in existing:
                local = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=path, token=token, force_download=True)
                same = Path(local).read_bytes() == payload
            if same:
                continue
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            operations.append(CommitOperationAdd(path_in_repo=path, path_or_fileobj=target))
            changed.append(path)
        if operations:
            api.create_commit(repo_id=repo_id, repo_type="dataset", operations=operations, commit_message="Initialize governed PRC justice intelligence dataset", token=token)
    return repo_id, changed


def _forbidden_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    forbidden = {
        "source_url","url","raw_text","raw_source_text","raw_pdf_text","raw_model_response",
        "full_text","quote","cookie","cookies","credential","credentials","secret","secrets",
        "private_endpoint","target_person","target_account","surveillance_blind_spot","evasion_method","anti_forensics_method",
    }
    return normalized in forbidden


def _scan_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _forbidden_key(str(key)):
                raise JusticeGatewayError(f"forbidden raw/sensitive field in export: {path}.{key}")
            _scan_forbidden(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden(item, f"{path}[{index}]")


def _validate_record(row: Any, index: int) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise JusticeGatewayError(f"record {index} must be an object")
    value = dict(row)
    required = set(_record_schema()["required_fields"])
    missing = sorted(required - set(value))
    if missing:
        raise JusticeGatewayError(f"record {index} missing fields: {', '.join(missing)}")
    if not RECORD_ID_RE.fullmatch(str(value.get("record_id") or "")):
        raise JusticeGatewayError(f"record {index} has invalid record_id")
    refs = value.get("evidence_ref_ids")
    if not isinstance(refs, list) or not refs or len(refs) > 100 or any(not EVREF_RE.fullmatch(str(ref)) for ref in refs):
        raise JusticeGatewayError(f"record {index} has invalid opaque evidence references")
    transform = value.get("model_transform")
    if not isinstance(transform, Mapping) or transform.get("provider") != "cloudflare" or transform.get("method") != "browser-rendering-json":
        raise JusticeGatewayError(f"record {index} has unexpected model transform provenance")
    safety = value.get("safety")
    expected_safety = {
        "public_or_authorized": True,
        "raw_source_text_stored": False,
        "raw_source_url_stored": False,
        "raw_model_response_stored": False,
        "personal_targeting": False,
        "secret_operational_detail": False,
        "evasion_or_anti_forensics": False,
    }
    if not isinstance(safety, Mapping) or any(safety.get(key) != expected for key, expected in expected_safety.items()):
        raise JusticeGatewayError(f"record {index} violates safety contract")
    summary = str(value.get("summary") or "").strip()
    if not summary or len(summary) > 1800:
        raise JusticeGatewayError(f"record {index} has invalid normalized summary")
    _scan_forbidden(value)
    return value


def validate_export(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_EXPORT_BYTES:
        raise JusticeGatewayError("export file missing or exceeds bounded size")
    value = _load(path)
    if not isinstance(value, Mapping):
        raise JusticeGatewayError("export root must be an object")
    contract = validate_contract()
    if value.get("schema_version") != contract["accepted_export_schema"]:
        raise JusticeGatewayError("unsupported export schema")
    if value.get("producer_repository") != contract["producer_repository"]:
        raise JusticeGatewayError("unexpected export producer")
    for key in (
        "raw_source_text_included","raw_source_url_included","raw_model_response_included",
        "personal_data_included","secret_operational_details_included","evasion_or_anti_forensics_included","direct_huggingface_write",
    ):
        if value.get(key) is not False:
            raise JusticeGatewayError(f"export boundary violation: {key}")
    if value.get("storage_gateway_owner") != "a15280020511/decision-system-governance":
        raise JusticeGatewayError("export storage gateway mismatch")
    records = value.get("records")
    if not isinstance(records, list) or not 0 <= len(records) <= MAX_RECORDS_PER_BATCH:
        raise JusticeGatewayError("export record count outside bounded range")
    if int(value.get("record_count") or 0) != len(records):
        raise JusticeGatewayError("export record_count mismatch")
    validated = [_validate_record(row, index) for index, row in enumerate(records)]
    if len({row["record_id"] for row in validated}) != len(validated):
        raise JusticeGatewayError("duplicate record_id inside export")
    _scan_forbidden(value)
    return {**dict(value), "records": validated}


def bootstrap(output: Path) -> dict[str, Any]:
    contract = validate_contract()
    token = str(os.getenv(TOKEN_ENV) or "").strip()
    if not token:
        raise JusticeGatewayError("HF_TOKEN is not configured in governance")
    api = HfApi()
    repo_id, changed = _ensure_repo(api, token, contract)
    receipt = {
        "schema_version": "governance-hf-justice-bootstrap-receipt-v1",
        "status": "HF_JUSTICE_INTELLIGENCE_BOOTSTRAPPED",
        "repository": repo_id,
        "private": True,
        "changed_paths": changed,
        "raw_source_storage": False,
        "model_calls": 0,
        "secret_values_exposed": False,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def health(output: Path) -> dict[str, Any]:
    contract = validate_contract()
    token = str(os.getenv(TOKEN_ENV) or "").strip()
    if not token:
        raise JusticeGatewayError("HF_TOKEN is not configured in governance")
    api = HfApi()
    repo_id, _ = _ensure_repo(api, token, contract)
    files = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    missing = sorted(set(contract["required_bootstrap_files"]) - files)
    if missing:
        raise JusticeGatewayError("required dataset files missing: " + ", ".join(missing))
    receipt = {
        "schema_version": "governance-hf-justice-health-receipt-v1",
        "status": "HF_JUSTICE_INTELLIGENCE_HEALTHY",
        "repository": repo_id,
        "private": True,
        "required_files_present": True,
        "raw_source_storage": False,
        "model_calls": 0,
        "secret_values_exposed": False,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def ingest(input_path: Path, output: Path) -> dict[str, Any]:
    export = validate_export(input_path)
    contract = validate_contract()
    token = str(os.getenv(TOKEN_ENV) or "").strip()
    if not token:
        raise JusticeGatewayError("HF_TOKEN is not configured in governance")
    api = HfApi()
    repo_id, _ = _ensure_repo(api, token, contract)
    export_sha = _sha_bytes(input_path.read_bytes())
    as_of = str(export.get("as_of_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise JusticeGatewayError("export as_of_date must use YYYY-MM-DD")
    source_run_id = str(export.get("source_run_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", source_run_id):
        raise JusticeGatewayError("invalid source_run_id")
    batch_id = f"{source_run_id}-{export_sha[:16]}"
    record_path = f"records/{as_of}/{batch_id}.jsonl"
    manifest_path = f"manifests/{as_of}/{batch_id}.json"
    record_bytes = "".join(_canonical(row) + "\n" for row in export["records"]).encode("utf-8")
    manifest = {
        "schema_version": "prc-justice-intelligence-batch-manifest-v1",
        "batch_id": batch_id,
        "as_of_date": as_of,
        "producer_repository": export["producer_repository"],
        "producer_commit": export.get("producer_commit"),
        "source_run_id": source_run_id,
        "export_sha256": export_sha,
        "record_count": len(export["records"]),
        "record_file": record_path,
        "record_file_sha256": _sha_bytes(record_bytes),
        "opaque_evidence_reference_only": True,
        "raw_source_text_included": False,
        "raw_source_url_included": False,
        "raw_model_response_included": False,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    existing = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token))
    desired = {record_path: record_bytes, manifest_path: manifest_bytes}
    if set(desired).issubset(existing):
        for path, payload in desired.items():
            local = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=path, token=token, force_download=True)
            if Path(local).read_bytes() != payload:
                raise JusticeGatewayError("immutable batch path already exists with different content")
        commit_oid = ""
        status = "HF_JUSTICE_INTELLIGENCE_ALREADY_INGESTED"
    else:
        if set(desired) & existing:
            raise JusticeGatewayError("partial immutable batch already exists")
        with tempfile.TemporaryDirectory(prefix="hf-justice-ingest-") as temp:
            root = Path(temp)
            operations: list[CommitOperationAdd] = []
            for path, payload in desired.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                operations.append(CommitOperationAdd(path_in_repo=path, path_or_fileobj=target))
            commit = api.create_commit(repo_id=repo_id, repo_type="dataset", operations=operations, commit_message=f"Append PRC justice intelligence batch {batch_id}", token=token)
            commit_oid = str(getattr(commit, "oid", "") or "")
        status = "HF_JUSTICE_INTELLIGENCE_INGESTED"
    receipt = {
        "schema_version": "governance-hf-justice-ingest-receipt-v1",
        "status": status,
        "repository": repo_id,
        "private": True,
        "batch_id": batch_id,
        "record_count": len(export["records"]),
        "record_path": record_path,
        "manifest_path": manifest_path,
        "export_sha256": export_sha,
        "commit_oid": commit_oid,
        "raw_source_text_stored": False,
        "raw_source_url_stored": False,
        "raw_model_response_stored": False,
        "direct_business_center_hf_access": False,
        "model_calls": 0,
        "secret_values_exposed": False,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def render(output: Path) -> str:
    path = output / "receipt.json"
    if not path.is_file():
        path = output / "failure.json"
    if not path.is_file():
        raise JusticeGatewayError("no receipt found")
    row = _load(path)
    lines = ["## GOVERNANCE_HF_JUSTICE_INTELLIGENCE", "", f"- Status: `{row.get('status', 'UNKNOWN')}`"]
    if row.get("repository"):
        lines.append(f"- Repository: `{row['repository']}`")
    if row.get("batch_id"):
        lines.append(f"- Batch: `{row['batch_id']}`")
    if "record_count" in row:
        lines.append(f"- Derived records: `{row['record_count']}`")
    lines.extend([
        "- Raw source text stored: `false`",
        "- Raw source URL stored: `false`",
        "- Raw model response stored: `false`",
        f"- Model calls in gateway: `{row.get('model_calls', 0)}`",
        f"- Secret values exposed: `{str(bool(row.get('secret_values_exposed'))).lower()}`",
    ])
    if row.get("error"):
        lines.append(f"- Error: `{row['error']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate","bootstrap","health","ingest","render"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "validate":
            validate_contract()
            result = {"status":"HF_JUSTICE_INTELLIGENCE_CONTRACT_VALIDATED","secret_values_exposed":False,"model_calls":0}
            _dump(output / "receipt.json", result)
        elif args.command == "bootstrap":
            result = bootstrap(output)
        elif args.command == "health":
            result = health(output)
        elif args.command == "ingest":
            if not args.input:
                raise JusticeGatewayError("--input is required for ingest")
            result = ingest(Path(args.input), output)
        else:
            print(render(output), end="")
            return 0
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {"status":"HF_JUSTICE_INTELLIGENCE_FAILED","error":f"{type(exc).__name__}: {exc}"[:1200],"secret_values_exposed":False,"model_calls":0}
        _dump(output / "failure.json", failure)
        print(failure["error"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
