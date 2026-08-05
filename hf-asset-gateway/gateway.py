#!/usr/bin/env python3
"""Governance-owned bootstrap and health gateway for controlled Hugging Face assets."""
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


class AssetGatewayError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate_contract() -> Mapping[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("schema_version") != "governance-hf-asset-gateway-v1":
        raise AssetGatewayError("unsupported Hugging Face asset gateway contract")
    if contract.get("status") != "production-control":
        raise AssetGatewayError("asset gateway contract is not production-control")
    if contract.get("storage_owner") != "a15280020511/decision-system-governance":
        raise AssetGatewayError("governance storage owner mismatch")
    if contract.get("token_environment_variable") != TOKEN_ENV:
        raise AssetGatewayError("unexpected token environment variable")

    expected = {
        "evaluation_results": ("dataset", "private", "HF_EVALUATION_RESULTS_DATASET_REPO"),
        "managed_models": ("model", "private", "HF_MANAGED_MODEL_REPO"),
        "readonly_space": ("space", "public", "HF_READONLY_SPACE_REPO"),
    }
    repositories = contract.get("repositories")
    if not isinstance(repositories, Mapping) or set(repositories) != set(expected):
        raise AssetGatewayError("managed repository set mismatch")
    for key, (repo_type, visibility, variable) in expected.items():
        row = repositories.get(key)
        if not isinstance(row, Mapping):
            raise AssetGatewayError(f"repository contract missing: {key}")
        if row.get("repo_type") != repo_type or row.get("visibility") != visibility:
            raise AssetGatewayError(f"repository type or visibility mismatch: {key}")
        if row.get("repository_variable") != variable:
            raise AssetGatewayError(f"repository variable mismatch: {key}")
        default_name = str(row.get("default_repository_name") or "")
        if not SAFE_PART_RE.fullmatch(default_name):
            raise AssetGatewayError(f"unsafe default repository name: {key}")
    if repositories["readonly_space"].get("space_sdk") != "static":
        raise AssetGatewayError("read-only Space must use the static SDK")

    boundaries = contract.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise AssetGatewayError("asset gateway boundaries missing")
    required_true = (
        "gpts_is_only_external_controller",
        "evaluation_records_structured_only",
        "immutable_commit_required",
        "model_assets_require_separate_approval",
    )
    required_false = (
        "business_centers_direct_huggingface_access_allowed",
        "inference_allowed",
        "training_allowed",
        "jobs_allowed",
        "space_backend_execution_allowed",
        "space_write_or_control_actions_allowed",
        "raw_prompts_allowed",
        "raw_business_data_allowed",
        "personal_data_allowed",
        "secrets_allowed_in_payloads",
    )
    if any(boundaries.get(key) is not True for key in required_true):
        raise AssetGatewayError("required positive boundary missing")
    if any(boundaries.get(key) is not False for key in required_false):
        raise AssetGatewayError("forbidden capability enabled")

    required_files = contract.get("required_bootstrap_files")
    if not isinstance(required_files, Mapping) or set(required_files) != set(expected):
        raise AssetGatewayError("bootstrap file contract mismatch")
    for key, paths in required_files.items():
        if not isinstance(paths, list) or not paths or any(not isinstance(path, str) or not path for path in paths):
            raise AssetGatewayError(f"invalid bootstrap file list: {key}")
    return contract


def _identity(api: HfApi, token: str) -> str:
    row = api.whoami(token=token)
    owner = str(row.get("name") or "") if isinstance(row, Mapping) else ""
    if not SAFE_PART_RE.fullmatch(owner):
        raise AssetGatewayError("Hugging Face account identity is unavailable or unsafe")
    return owner


def _repo_id(owner: str, row: Mapping[str, Any]) -> str:
    variable = str(row["repository_variable"])
    value = os.getenv(variable, "").strip() or f"{owner}/{row['default_repository_name']}"
    parts = value.split("/")
    if len(parts) != 2 or any(not SAFE_PART_RE.fullmatch(part) for part in parts):
        raise AssetGatewayError(f"invalid repository id in {variable}")
    if parts[0] != owner:
        raise AssetGatewayError(f"repository owner in {variable} must match the authenticated account")
    return value


def _evaluation_files() -> dict[str, bytes]:
    readme = """---\npretty_name: Decision System Evaluation Results\n---\n\n# Decision System Evaluation Results\n\nGovernance-owned, private, versioned storage for sanitized structured evaluation summaries.\n\nForbidden payloads: raw prompts, business records, personal data, secrets, model inputs/outputs and unrestricted logs.\n"""
    schema = {
        "schema_version": "evaluation-result-record-v1",
        "required": [
            "result_id", "producer_repository", "producer_commit", "run_id",
            "subject_type", "subject_id", "dataset_version", "test_suite",
            "status", "metrics", "artifact_sha256"
        ],
        "subject_type": ["model", "data", "pipeline", "compute-operation"],
        "status": ["pass", "fail", "partial", "informational"],
        "forbidden_fields": [
            "raw_prompt", "raw_input", "raw_output", "secret", "personal_data",
            "business_payload", "unredacted_log"
        ],
        "metrics_value_types": ["integer", "number", "boolean", "short-string"],
        "append_only": True
    }
    ledger = {
        "schema_version": "evaluation-version-ledger-v1",
        "status": "initialized-empty",
        "entries": [],
        "append_only": True,
        "raw_prompts_stored": False,
        "raw_business_data_stored": False,
        "personal_data_stored": False,
        "secrets_stored": False
    }
    return {
        "README.md": readme.encode("utf-8"),
        "evaluation-results/v1/schema.json": (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "evaluation-results/v1/version-ledger.json": (json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def _model_files() -> dict[str, bytes]:
    readme = """---\nlicense: other\n---\n\n# Managed Model Registry\n\nPrivate governance registry for user-owned model cards, adapters and explicitly approved model assets.\n\nNo external model is copied automatically. No model execution, inference, training or arbitrary upload is enabled by this bootstrap. Binary model assets require a separate reviewed ingestion contract and immutable digest.\n"""
    registry = {
        "schema_version": "managed-model-registry-v1",
        "status": "initialized-empty",
        "models": [],
        "automatic_public_model_copy_allowed": False,
        "binary_asset_ingestion_enabled": False,
        "separate_approval_required": True,
        "immutable_digest_required": True,
        "inference_allowed": False,
        "training_allowed": False
    }
    return {
        "README.md": readme.encode("utf-8"),
        "registry.json": (json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def _space_files() -> dict[str, bytes]:
    readme = """---\ntitle: Decision System Read-only Status\nemoji: 📊\ncolorFrom: gray\ncolorTo: blue\nsdk: static\npinned: false\nlicense: apache-2.0\n---\n\n# Decision System Read-only Status\n\nNon-critical public display only. This Space has no production control, write action, secret, business payload, model inference or backend execution.\n"""
    status = {
        "schema_version": "decision-system-readonly-status-v1",
        "display_only": True,
        "production_control": False,
        "write_actions": False,
        "backend_execution": False,
        "model_inference": False,
        "secrets_present": False,
        "business_data_present": False,
        "capabilities": {
            "numeric_baseline_library": "enabled",
            "public_model_dataset_catalog": "enabled",
            "evaluation_result_repository": "enabled-after-bootstrap",
            "managed_model_registry": "enabled-after-bootstrap"
        }
    }
    index = """<!doctype html>\n<html lang=\"zh-CN\">\n<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Decision System Read-only Status</title><style>body{font-family:system-ui,sans-serif;max-width:900px;margin:3rem auto;padding:0 1rem;line-height:1.6}code{background:#eee;padding:.15rem .35rem;border-radius:.25rem}.card{border:1px solid #ddd;border-radius:.6rem;padding:1rem;margin:1rem 0}</style></head>\n<body><h1>决策系统只读状态页</h1><div class=\"card\"><strong>用途：</strong>非关键、只读展示和原型验证。</div><div class=\"card\"><strong>安全边界：</strong>无生产控制、无写操作、无后台执行、无模型推理、无业务数据、无 Secret。</div><p>机器可读状态：<code>status.json</code></p></body></html>\n"""
    return {
        "README.md": readme.encode("utf-8"),
        "index.html": index.encode("utf-8"),
        "status.json": (json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def _sync_repo(
    api: HfApi,
    *,
    token: str,
    repo_id: str,
    repo_type: str,
    private: bool,
    files: Mapping[str, bytes],
    message: str,
    space_sdk: str | None = None,
) -> dict[str, Any]:
    create_kwargs: dict[str, Any] = {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "private": private,
        "exist_ok": True,
        "token": token,
    }
    if repo_type == "space":
        create_kwargs["space_sdk"] = space_sdk or "static"
    api.create_repo(**create_kwargs)
    info = api.repo_info(repo_id=repo_id, repo_type=repo_type, token=token)
    if bool(getattr(info, "private", False)) is not private:
        raise AssetGatewayError(f"repository visibility mismatch: {repo_id}")

    existing = set(api.list_repo_files(repo_id=repo_id, repo_type=repo_type, token=token))
    operations: list[CommitOperationAdd] = []
    changed_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hf-assets-") as temp:
        root = Path(temp)
        for path, payload in sorted(files.items()):
            changed = True
            if path in existing:
                local = hf_hub_download(
                    repo_id=repo_id,
                    repo_type=repo_type,
                    filename=path,
                    token=token,
                    force_download=True,
                )
                changed = Path(local).read_bytes() != payload
            if changed:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                operations.append(CommitOperationAdd(path_in_repo=path, path_or_fileobj=target))
                changed_paths.append(path)
        commit_oid = ""
        if operations:
            commit = api.create_commit(
                repo_id=repo_id,
                repo_type=repo_type,
                operations=operations,
                commit_message=message,
                token=token,
            )
            commit_oid = str(getattr(commit, "oid", "") or "")

    final_files = set(api.list_repo_files(repo_id=repo_id, repo_type=repo_type, token=token))
    missing = sorted(set(files) - final_files)
    if missing:
        raise AssetGatewayError(f"required files missing from {repo_id}: {missing}")
    checksums = {path: _sha_bytes(payload) for path, payload in sorted(files.items())}
    return {
        "repository": repo_id,
        "repo_type": repo_type,
        "private": private,
        "required_file_count": len(files),
        "changed_paths": changed_paths,
        "commit_oid": commit_oid,
        "checksums": checksums,
    }


def _resolve_repositories(api: HfApi, token: str, contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    owner = _identity(api, token)
    return {
        key: {**dict(row), "repo_id": _repo_id(owner, row)}
        for key, row in contract["repositories"].items()
    }


def bootstrap(output: Path) -> dict[str, Any]:
    contract = validate_contract()
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise AssetGatewayError("HF_TOKEN is not configured in the governance repository")
    api = HfApi()
    repositories = _resolve_repositories(api, token, contract)
    results = {
        "evaluation_results": _sync_repo(
            api,
            token=token,
            repo_id=repositories["evaluation_results"]["repo_id"],
            repo_type="dataset",
            private=True,
            files=_evaluation_files(),
            message="Initialize governed evaluation result version repository",
        ),
        "managed_models": _sync_repo(
            api,
            token=token,
            repo_id=repositories["managed_models"]["repo_id"],
            repo_type="model",
            private=True,
            files=_model_files(),
            message="Initialize governed managed model registry",
        ),
        "readonly_space": _sync_repo(
            api,
            token=token,
            repo_id=repositories["readonly_space"]["repo_id"],
            repo_type="space",
            private=False,
            files=_space_files(),
            message="Initialize non-critical read-only status Space",
            space_sdk="static",
        ),
    }
    receipt = {
        "schema_version": "governance-hf-asset-bootstrap-receipt-v1",
        "status": "HF_ASSET_REPOSITORIES_BOOTSTRAPPED",
        "repositories": results,
        "inference_used": False,
        "training_used": False,
        "space_backend_execution_enabled": False,
        "business_center_direct_access_enabled": False,
        "secret_values_exposed": False,
        "model_calls": 0,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def health(output: Path) -> dict[str, Any]:
    contract = validate_contract()
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise AssetGatewayError("HF_TOKEN is not configured in the governance repository")
    api = HfApi()
    repositories = _resolve_repositories(api, token, contract)
    rows = {}
    for key, row in repositories.items():
        repo_id = row["repo_id"]
        repo_type = row["repo_type"]
        expected_private = row["visibility"] == "private"
        info = api.repo_info(repo_id=repo_id, repo_type=repo_type, token=token)
        actual_private = bool(getattr(info, "private", False))
        files = set(api.list_repo_files(repo_id=repo_id, repo_type=repo_type, token=token))
        required = set(contract["required_bootstrap_files"][key])
        missing = sorted(required - files)
        if actual_private is not expected_private or missing:
            raise AssetGatewayError(f"unhealthy Hugging Face asset repository: {repo_id}")
        rows[key] = {
            "repository": repo_id,
            "repo_type": repo_type,
            "private": actual_private,
            "required_files_present": True,
            "required_file_count": len(required),
        }
    receipt = {
        "schema_version": "governance-hf-asset-health-receipt-v1",
        "status": "HF_ASSET_REPOSITORIES_HEALTHY",
        "repositories": rows,
        "secret_values_exposed": False,
        "model_calls": 0,
    }
    _dump(output / "receipt.json", receipt)
    return receipt


def render(output: Path) -> str:
    path = output / "receipt.json"
    if not path.exists():
        path = output / "failure.json"
    if not path.exists():
        raise AssetGatewayError("no asset gateway receipt found")
    row = _load(path)
    lines = ["## GOVERNANCE_HF_ASSET_GATEWAY", "", f"- Status: `{row.get('status', 'UNKNOWN')}`"]
    for key, value in (row.get("repositories") or {}).items():
        lines.append(f"- {key}: `{value.get('repository', 'unknown')}` ({value.get('repo_type', 'unknown')}, private={str(bool(value.get('private'))).lower()})")
        if value.get("commit_oid"):
            lines.append(f"  - Commit: `{value['commit_oid']}`")
    lines.extend([
        f"- Secret values exposed: `{str(bool(row.get('secret_values_exposed'))).lower()}`",
        f"- Model calls: `{row.get('model_calls', 0)}`",
    ])
    if row.get("error"):
        lines.append(f"- Error: `{row['error']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "bootstrap", "health", "render"])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "validate":
            validate_contract()
            result = {
                "status": "HF_ASSET_GATEWAY_CONTRACT_VALIDATED",
                "secret_values_exposed": False,
                "model_calls": 0,
            }
            _dump(output / "receipt.json", result)
        elif args.command == "bootstrap":
            result = bootstrap(output)
        elif args.command == "health":
            result = health(output)
        else:
            print(render(output), end="")
            return 0
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        token = os.getenv(TOKEN_ENV, "")
        message = _clean(exc).replace(token, "[REDACTED]") if token else _clean(exc)
        failure = {
            "status": "HF_ASSET_GATEWAY_FAILED",
            "error": message,
            "secret_values_exposed": False,
            "model_calls": 0,
        }
        _dump(output / "failure.json", failure)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
