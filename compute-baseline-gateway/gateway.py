#!/usr/bin/env python3
"""Governance-owned gateway for the private compute numeric baseline Dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "gateway-contract.json"
TOPOLOGY_PATH = HERE.parent / "control-plane" / "topology-contract.json"
HF_TOKEN_ENV = "HF_TOKEN"
HF_REPO_ENV = "HF_NUMERIC_BASELINE_DATASET_REPO"
DEFAULT_REPO_NAME = "compute-numeric-baselines"
REMOTE_ROOT = "numeric-baselines/v1/data"
OWNER = "a15280020511"
ISSUE_TITLE = "[baseline]"
TABLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GatewayError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any, limit: int = 1500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _write_output(name: str, value: Any) -> None:
    target = os.getenv("GITHUB_OUTPUT", "")
    if not target:
        return
    normalized = str(value).replace("\r", " ").replace("\n", " ")
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={normalized}\n")


def validate_contracts() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    topology = _load(TOPOLOGY_PATH)
    if contract.get("schema_version") != "governance-compute-baseline-gateway-v1":
        raise GatewayError("unsupported gateway contract")
    if contract.get("status") != "production-control":
        raise GatewayError("gateway contract is not production-control")
    dataset = contract.get("dataset") or {}
    if dataset.get("default_repository_name") != DEFAULT_REPO_NAME:
        raise GatewayError("default baseline repository mismatch")
    if dataset.get("visibility") != "private" or dataset.get("remote_root") != REMOTE_ROOT:
        raise GatewayError("private numeric Dataset contract mismatch")
    if dataset.get("payload_scope") != "pure-numeric-parquet-only":
        raise GatewayError("numeric-only payload contract missing")
    if dataset.get("control_metadata_uploaded") is not False:
        raise GatewayError("control metadata must remain outside Hugging Face")
    if set(contract.get("operations") or []) != {"health", "ingest_evidence_artifact"}:
        raise GatewayError("gateway operation set mismatch")
    source = contract.get("source") or {}
    if source.get("repository") != f"{OWNER}/evidence-data-center":
        raise GatewayError("evidence source repository mismatch")
    if source.get("manifest_schema_version") != "governance-baseline-export-v1":
        raise GatewayError("manifest schema mismatch")
    validation = contract.get("validation") or {}
    required_true = (
        "sha256_required",
        "numeric_columns_only",
        "schema_match_required_for_append",
        "path_traversal_rejected",
        "unexpected_files_rejected",
        "duplicate_batch_rejected",
    )
    if any(validation.get(key) is not True for key in required_true):
        raise GatewayError("gateway validation controls incomplete")
    if validation.get("null_values_allowed") is not False:
        raise GatewayError("null values must be forbidden")
    boundaries = contract.get("boundaries") or {}
    if boundaries.get("gpts_is_only_external_controller") is not True:
        raise GatewayError("GPTs control boundary missing")
    for key in (
        "child_centers_direct_communication_allowed",
        "compute_direct_huggingface_access_allowed",
        "knowledge_base_storage_allowed",
        "knowledge_graph_storage_allowed",
        "raw_text_storage_allowed",
        "document_storage_allowed",
    ):
        if boundaries.get(key) is not False:
            raise GatewayError(f"forbidden boundary enabled: {key}")
    if topology.get("schema_version") != "decision-system-topology-v1":
        raise GatewayError("topology contract missing")
    baseline = topology.get("compute_baseline") or {}
    if baseline.get("storage_gateway_owner") != f"{OWNER}/decision-system-governance":
        raise GatewayError("governance is not the baseline gateway owner")
    if baseline.get("beneficiary_center") != f"{OWNER}/compute-simulation-center":
        raise GatewayError("compute baseline beneficiary mismatch")
    forbidden = set(topology.get("forbidden_runtime_edges") or [])
    for edge in (
        "intelligence->huggingface_private_dataset",
        "compute->huggingface_private_dataset",
        "expert->huggingface_private_dataset",
    ):
        if edge not in forbidden:
            raise GatewayError(f"missing forbidden edge: {edge}")
    return {"contract": contract, "topology": topology}


def _event_ticket(path: Path) -> tuple[int, str, Mapping[str, Any]]:
    event = _load(path)
    issue = event.get("issue") if isinstance(event.get("issue"), Mapping) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), Mapping) else {}
    title = str(issue.get("title") or "")
    actor = str(sender.get("login") or "")
    number = int(issue.get("number") or 0)
    if title != ISSUE_TITLE:
        raise GatewayError(f"issue title must be exactly {ISSUE_TITLE}")
    if actor != OWNER:
        raise GatewayError("baseline gateway issue actor must be repository owner")
    if number <= 0:
        raise GatewayError("issue number missing")
    raw = json.loads(str(issue.get("body") or ""))
    if not isinstance(raw, Mapping):
        raise GatewayError("baseline ticket must be a JSON object")
    return number, actor, raw


def prepare(event_path: Path, output: Path) -> dict[str, Any]:
    validate_contracts()
    number, _, ticket = _event_ticket(event_path)
    allowed = {
        "schema_version",
        "operation",
        "source_run_id",
        "artifact_name",
        "expected_manifest_sha256",
    }
    extra = sorted(set(ticket) - allowed)
    if extra:
        raise GatewayError(f"unknown ticket fields: {extra}")
    if ticket.get("schema_version") != "governance-baseline-ticket-v1":
        raise GatewayError("unsupported baseline ticket schema")
    operation = str(ticket.get("operation") or "")
    if operation not in {"health", "ingest_evidence_artifact"}:
        raise GatewayError("operation must be health or ingest_evidence_artifact")
    source_run_id = int(ticket.get("source_run_id") or 0)
    artifact_name = str(ticket.get("artifact_name") or "")
    manifest_sha = str(ticket.get("expected_manifest_sha256") or "")
    if operation == "ingest_evidence_artifact":
        if source_run_id <= 0:
            raise GatewayError("source_run_id must be positive")
        if not artifact_name.startswith("compute-baseline-export-"):
            raise GatewayError("artifact_name prefix invalid")
        if not SHA256_RE.fullmatch(manifest_sha):
            raise GatewayError("expected_manifest_sha256 must be lowercase SHA-256")
    else:
        source_run_id = 0
        artifact_name = ""
        manifest_sha = ""
    status = {
        "status": "BASELINE_GATEWAY_ACCEPTED",
        "governance_issue_number": number,
        "operation": operation,
        "source_repository": f"{OWNER}/evidence-data-center",
        "source_run_id": source_run_id,
        "artifact_name": artifact_name,
        "expected_manifest_sha256": manifest_sha,
        "secret_values_exposed": False,
        "model_calls": 0,
    }
    _dump(output / "prepare-status.json", status)
    for key, value in status.items():
        if key in {"operation", "source_repository", "source_run_id", "artifact_name", "expected_manifest_sha256"}:
            _write_output(key, value)
    return status


def _resolve_repo(api: HfApi, token: str) -> str:
    identity = api.whoami(token=token)
    owner = str(identity.get("name") or "") if isinstance(identity, Mapping) else ""
    if not owner:
        raise GatewayError("Hugging Face identity unavailable")
    repo = os.getenv(HF_REPO_ENV, "").strip() or f"{owner}/{DEFAULT_REPO_NAME}"
    parts = repo.split("/")
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if len(parts) != 2 or any(not part or any(ch not in safe for ch in part) for part in parts):
        raise GatewayError("invalid Hugging Face Dataset repository id")
    return repo


def _visible_repo_files(api: HfApi, repo: str, token: str) -> set[str]:
    rows = set(api.list_repo_files(repo_id=repo, repo_type="dataset", token=token))
    visible = {row for row in rows if not row.startswith(".") and row != "README.md"}
    unexpected = sorted(
        row
        for row in visible
        if not row.startswith(REMOTE_ROOT + "/") or not row.endswith(".parquet")
    )
    if unexpected:
        raise GatewayError("private baseline contains unexpected files: " + ", ".join(unexpected[:20]))
    return visible


def health(output: Path) -> dict[str, Any]:
    validate_contracts()
    token = os.getenv(HF_TOKEN_ENV, "").strip()
    if not token:
        raise GatewayError("HF_TOKEN is not configured in governance repository")
    api = HfApi()
    repo = _resolve_repo(api, token)
    info = api.repo_info(repo_id=repo, repo_type="dataset", token=token)
    if not bool(getattr(info, "private", False)):
        raise GatewayError("compute baseline Dataset must be private")
    files = _visible_repo_files(api, repo, token)
    receipt = {
        "status": "BASELINE_GATEWAY_HEALTHY",
        "repository": repo,
        "private": True,
        "numeric_parquet_file_count": len(files),
        "storage_gateway_owner": f"{OWNER}/decision-system-governance",
        "beneficiary_center": f"{OWNER}/compute-simulation-center",
        "direct_business_center_hf_access_allowed": False,
        "secret_values_exposed": False,
        "model_calls": 0,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def _numeric_table(path: Path, expected_rows: int) -> pa.Table:
    schema = pq.read_schema(path)
    if not schema.names:
        raise GatewayError(f"empty schema: {path.name}")
    for field in schema:
        if not (pa.types.is_integer(field.type) or pa.types.is_floating(field.type)):
            raise GatewayError(f"non-numeric column rejected: {path.name}:{field.name}")
        if field.nullable:
            raise GatewayError(f"nullable schema rejected: {path.name}:{field.name}")
    table = pq.read_table(path)
    if table.num_rows != expected_rows:
        raise GatewayError(f"row count mismatch: {path.name}")
    if any(column.null_count for column in table.columns):
        raise GatewayError(f"null values rejected: {path.name}")
    return table


def _manifest_root(input_dir: Path) -> tuple[Path, Mapping[str, Any]]:
    manifests = list(input_dir.rglob("manifest.json"))
    if len(manifests) != 1:
        raise GatewayError("artifact must contain exactly one manifest.json")
    manifest_path = manifests[0]
    manifest = _load(manifest_path)
    if not isinstance(manifest, Mapping):
        raise GatewayError("manifest must be a JSON object")
    return manifest_path, manifest


def _validate_manifest(
    input_dir: Path,
    expected_sha: str,
    contract: Mapping[str, Any],
) -> tuple[Mapping[str, Any], list[tuple[str, Path, pa.Table]]]:
    manifest_path, manifest = _manifest_root(input_dir)
    if _sha_file(manifest_path) != expected_sha:
        raise GatewayError("manifest SHA-256 mismatch")
    if manifest.get("schema_version") != "governance-baseline-export-v1":
        raise GatewayError("unsupported export manifest")
    if manifest.get("producer_repository") != f"{OWNER}/evidence-data-center":
        raise GatewayError("producer repository mismatch")
    mode = manifest.get("mode")
    if mode not in {"append_batch", "replace_snapshot"}:
        raise GatewayError("manifest mode invalid")
    batch_id = str(manifest.get("batch_id") or "")
    if not batch_id or len(batch_id) > 120 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in batch_id):
        raise GatewayError("batch_id invalid")
    if manifest.get("numeric_only") is not True:
        raise GatewayError("numeric_only must be true")
    if manifest.get("raw_text_included") is not False or manifest.get("control_json_for_hf") is not False:
        raise GatewayError("forbidden payload declared in manifest")
    rows = manifest.get("files")
    limits = contract.get("limits") or {}
    if not isinstance(rows, list) or not 1 <= len(rows) <= int(limits.get("max_files") or 0):
        raise GatewayError("manifest file count invalid")
    root = manifest_path.parent.resolve()
    listed: set[Path] = {manifest_path.resolve()}
    result: list[tuple[str, Path, pa.Table]] = []
    total_bytes = 0
    table_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise GatewayError("manifest file entry must be object")
        table_id = str(row.get("table_id") or "")
        rel = str(row.get("path") or "")
        sha = str(row.get("sha256") or "")
        expected_rows = int(row.get("rows") or 0)
        if not TABLE_ID_RE.fullmatch(table_id) or table_id in table_ids:
            raise GatewayError(f"invalid or duplicate table_id: {table_id}")
        if not SHA256_RE.fullmatch(sha):
            raise GatewayError(f"invalid SHA-256 for {table_id}")
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise GatewayError("artifact path traversal rejected") from exc
        if path.suffix != ".parquet" or not path.is_file():
            raise GatewayError(f"missing Parquet file: {rel}")
        if path.name != f"{table_id}.parquet":
            raise GatewayError(f"table filename mismatch: {rel}")
        if _sha_file(path) != sha:
            raise GatewayError(f"file SHA-256 mismatch: {rel}")
        total_bytes += path.stat().st_size
        if total_bytes > int(limits.get("max_uncompressed_bytes") or 0):
            raise GatewayError("artifact exceeds size limit")
        if expected_rows < 0 or expected_rows > int(limits.get("max_rows_per_file") or 0):
            raise GatewayError(f"row count outside limit: {rel}")
        table = _numeric_table(path, expected_rows)
        listed.add(path)
        table_ids.add(table_id)
        result.append((table_id, path, table))
    actual = {path.resolve() for path in root.rglob("*") if path.is_file()}
    if actual != listed:
        extras = sorted(str(path.relative_to(root)) for path in actual - listed)
        raise GatewayError("unexpected artifact files rejected: " + ", ".join(extras[:20]))
    return manifest, result


def _duplicate_batch(api: HfApi, repo: str, token: str, batch_id: str) -> bool:
    marker = f"baseline-batch:{batch_id}"
    try:
        commits = api.list_repo_commits(repo_id=repo, repo_type="dataset", token=token)
    except Exception as exc:
        raise GatewayError(f"cannot inspect Dataset commit history: {exc}") from exc
    for commit in commits[:200]:
        title = str(getattr(commit, "title", "") or "")
        message = str(getattr(commit, "message", "") or "")
        if marker in title or marker in message:
            return True
    return False


def ingest(input_dir: Path, expected_sha: str, output: Path) -> dict[str, Any]:
    control = validate_contracts()
    token = os.getenv(HF_TOKEN_ENV, "").strip()
    if not token:
        raise GatewayError("HF_TOKEN is not configured in governance repository")
    manifest, incoming = _validate_manifest(input_dir, expected_sha, control["contract"])
    api = HfApi()
    repo = _resolve_repo(api, token)
    api.create_repo(repo_id=repo, repo_type="dataset", private=True, exist_ok=True, token=token)
    info = api.repo_info(repo_id=repo, repo_type="dataset", token=token)
    if not bool(getattr(info, "private", False)):
        raise GatewayError("compute baseline Dataset must be private")
    visible = _visible_repo_files(api, repo, token)
    batch_id = str(manifest["batch_id"])
    if _duplicate_batch(api, repo, token, batch_id):
        raise GatewayError(f"duplicate baseline batch rejected: {batch_id}")
    mode = str(manifest["mode"])
    operations: list[CommitOperationAdd] = []
    table_receipts: list[dict[str, Any]] = []
    temp_root = Path(tempfile.mkdtemp(prefix="baseline-gateway-"))
    try:
        for table_id, source_path, incoming_table in incoming:
            remote_path = f"{REMOTE_ROOT}/{table_id}.parquet"
            final_table = incoming_table
            previous_rows = 0
            if mode == "append_batch" and remote_path in visible:
                local = hf_hub_download(
                    repo_id=repo,
                    repo_type="dataset",
                    filename=remote_path,
                    token=token,
                    force_download=True,
                )
                existing_path = Path(local)
                existing_schema = pq.read_schema(existing_path)
                if existing_schema != incoming_table.schema:
                    raise GatewayError(f"append schema mismatch: {table_id}")
                existing_table = pq.read_table(existing_path)
                if any(column.null_count for column in existing_table.columns):
                    raise GatewayError(f"existing table contains null values: {table_id}")
                previous_rows = existing_table.num_rows
                final_table = pa.concat_tables([existing_table, incoming_table], promote_options="none")
            target = temp_root / f"{table_id}.parquet"
            pq.write_table(
                final_table,
                target,
                compression="zstd",
                use_dictionary=False,
                write_statistics=True,
                version="2.6",
                data_page_version="2.0",
            )
            verified = _numeric_table(target, final_table.num_rows)
            operations.append(CommitOperationAdd(path_in_repo=remote_path, path_or_fileobj=target))
            table_receipts.append(
                {
                    "table_id": table_id,
                    "previous_rows": previous_rows,
                    "incoming_rows": incoming_table.num_rows,
                    "final_rows": verified.num_rows,
                    "sha256": _sha_file(target),
                }
            )
        commit = api.create_commit(
            repo_id=repo,
            repo_type="dataset",
            operations=operations,
            commit_message=f"baseline-batch:{batch_id} mode:{mode}",
            token=token,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    receipt = {
        "status": "BASELINE_INGEST_COMPLETED",
        "repository": repo,
        "private": True,
        "batch_id": batch_id,
        "mode": mode,
        "table_count": len(table_receipts),
        "tables": table_receipts,
        "commit_oid": str(getattr(commit, "oid", "") or ""),
        "control_metadata_uploaded": False,
        "raw_text_uploaded": False,
        "knowledge_graph_uploaded": False,
        "storage_gateway_owner": f"{OWNER}/decision-system-governance",
        "secret_values_exposed": False,
        "model_calls": 0,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def render(output: Path) -> str:
    receipt_path = output / "receipt.json"
    failure_path = output / "failure.json"
    if receipt_path.exists():
        row = _load(receipt_path)
    elif failure_path.exists():
        row = _load(failure_path)
    else:
        raise GatewayError("no gateway receipt found")
    lines = [
        "## GOVERNANCE_BASELINE_GATEWAY",
        "",
        f"- Status: `{row.get('status', 'UNKNOWN')}`",
        f"- Dataset: `{row.get('repository', 'not-opened')}`",
        f"- Private: `{str(bool(row.get('private'))).lower()}`",
        f"- Batch ID: `{row.get('batch_id', 'n/a')}`",
        f"- Table count: `{row.get('table_count', row.get('numeric_parquet_file_count', 0))}`",
        f"- Storage owner: `{row.get('storage_gateway_owner', 'a15280020511/decision-system-governance')}`",
        f"- Secret values exposed: `{str(bool(row.get('secret_values_exposed'))).lower()}`",
        f"- Model calls: `{row.get('model_calls', 0)}`",
    ]
    if row.get("commit_oid"):
        lines.append(f"- Hugging Face commit: `{row['commit_oid']}`")
    if row.get("error"):
        lines.append(f"- Error: `{row['error']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "prepare", "health", "ingest", "render"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--event-path")
    parser.add_argument("--input-dir")
    parser.add_argument("--expected-manifest-sha256", default="")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "validate":
            validate_contracts()
            result = {
                "status": "BASELINE_GATEWAY_CONTRACT_VALIDATED",
                "storage_gateway_owner": f"{OWNER}/decision-system-governance",
                "business_center_hf_tokens_allowed": False,
                "secret_values_exposed": False,
                "model_calls": 0,
            }
            _dump(output / "receipt.json", result)
        elif args.command == "prepare":
            if not args.event_path:
                raise GatewayError("--event-path is required")
            result = prepare(Path(args.event_path), output)
        elif args.command == "health":
            result = health(output)
        elif args.command == "ingest":
            if not args.input_dir or not SHA256_RE.fullmatch(args.expected_manifest_sha256):
                raise GatewayError("valid --input-dir and --expected-manifest-sha256 are required")
            result = ingest(Path(args.input_dir), args.expected_manifest_sha256, output)
        else:
            print(render(output), end="")
            return 0
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "status": "BASELINE_GATEWAY_FAILED",
            "error": _clean(f"{type(exc).__name__}: {exc}"),
            "storage_gateway_owner": f"{OWNER}/decision-system-governance",
            "secret_values_exposed": False,
            "model_calls": 0,
        }
        _dump(output / "failure.json", failure)
        print(failure["error"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
