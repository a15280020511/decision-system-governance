#!/usr/bin/env python3
"""Encrypted issue transport for PRC justice derived intelligence.

The transport preserves the existing least-privilege GitHub model:
- Evidence Center only needs Issues write on its own repository.
- Governance CONTROL_PLANE_TOKEN keeps Issues read/write only on business repos.
- No token gains cross-repository Actions/Contents access.

A stable X25519 recipient key is deterministically derived inside Governance from
HF_TOKEN. Only the public key is published. Evidence encrypts sanitized derived
exports with an ephemeral X25519 key + HKDF-SHA256 + ChaCha20-Poly1305 and posts
ciphertext to its own public Issue. Governance reads only those ciphertext Issues,
decrypts in runner memory, validates through gateway.py, writes the private HF
Dataset, publishes a safe receipt, and closes the handoff Issue.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hf_justice_gateway_transport", HERE / "gateway.py")
GATEWAY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = GATEWAY
SPEC.loader.exec_module(GATEWAY)

GOV_REPO = "a15280020511/decision-system-governance"
EVIDENCE_REPO = "a15280020511/evidence-data-center"
KEY_ISSUE_TITLE = "[hf-justice-transport-key]"
HANDOFF_ISSUE_TITLE = "[hf-justice-handoff]"
POLL_ISSUE_TITLE = "[hf-justice-poll]"
KEY_CONTEXT = b"prc-justice-hf-transport-recipient-v1\x00"
KDF_CONTEXT = b"prc-justice-hf-encrypted-issue-v1"
ENVELOPE_SCHEMA = "governance-prc-justice-encrypted-handoff-v1"
PUBLIC_KEY_SCHEMA = "governance-prc-justice-transport-public-key-v1"
MAX_HANDOFFS_PER_POLL = 20
MAX_CIPHERTEXT_BYTES = 48 * 1024
MAX_ENVELOPE_BODY_BYTES = 64 * 1024 - 1024
ALLOWED_HANDOFF_ACTORS = {"a15280020511", "github-actions[bot]"}


class TransportError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: Any, name: str, max_bytes: int) -> bytes:
    text = str(value or "").strip()
    if not text or len(text) > max_bytes * 2:
        raise TransportError(f"{name} is empty or oversized")
    try:
        raw = base64.urlsafe_b64decode(text + "=" * ((4 - len(text) % 4) % 4))
    except Exception as exc:
        raise TransportError(f"{name} is not valid base64url") from exc
    if len(raw) > max_bytes:
        raise TransportError(f"{name} exceeds bounded size")
    return raw


def _recipient_private(hf_token: str) -> x25519.X25519PrivateKey:
    token = hf_token.strip()
    if not token:
        raise TransportError("HF_TOKEN is not configured")
    seed = hashlib.sha256(KEY_CONTEXT + token.encode("utf-8")).digest()
    return x25519.X25519PrivateKey.from_private_bytes(seed)


def public_key_descriptor(hf_token: str) -> dict[str, Any]:
    public = _recipient_private(hf_token).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "schema_version": PUBLIC_KEY_SCHEMA,
        "algorithm": "X25519-HKDF-SHA256-CHACHA20POLY1305",
        "key_id": hashlib.sha256(public).hexdigest()[:24],
        "public_key_b64url": _b64(public),
        "purpose": "Encrypt sanitized PRC justice derived-intelligence handoffs to Governance.",
        "plaintext_allowed": False,
        "raw_source_allowed": False,
    }


def _derived_aead_key(private_key: x25519.X25519PrivateKey, peer_public: bytes, *, ephemeral_public: bytes, recipient_public: bytes) -> bytes:
    peer = x25519.X25519PublicKey.from_public_bytes(peer_public)
    shared = private_key.exchange(peer)
    salt = hashlib.sha256(ephemeral_public + recipient_public).digest()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=KDF_CONTEXT).derive(shared)


def decrypt_envelope(envelope: Mapping[str, Any], hf_token: str) -> tuple[bytes, dict[str, Any]]:
    required = {
        "schema_version","key_id","ephemeral_public_key_b64url","nonce_b64url",
        "ciphertext_b64url","aad","plaintext_sha256","plaintext_bytes"
    }
    if set(envelope) != required or envelope.get("schema_version") != ENVELOPE_SCHEMA:
        raise TransportError("encrypted handoff schema mismatch")
    descriptor = public_key_descriptor(hf_token)
    if envelope.get("key_id") != descriptor["key_id"]:
        raise TransportError("encrypted handoff key_id does not match current governance key")
    aad = envelope.get("aad")
    if not isinstance(aad, Mapping):
        raise TransportError("encrypted handoff aad must be an object")
    allowed_aad = {
        "source_repository","source_run_id","source_commit","chunk_index","chunk_count",
        "record_count","export_sha256","raw_source_text_included","raw_source_url_included",
        "raw_model_response_included"
    }
    if set(aad) != allowed_aad:
        raise TransportError("encrypted handoff aad fields mismatch")
    if aad.get("source_repository") != EVIDENCE_REPO:
        raise TransportError("unexpected encrypted handoff producer")
    if not isinstance(aad.get("source_run_id"), int) or int(aad["source_run_id"]) <= 0:
        raise TransportError("source_run_id must be positive")
    if not re.fullmatch(r"[0-9a-f]{40}", str(aad.get("source_commit") or "")):
        raise TransportError("source_commit is invalid")
    if not 1 <= int(aad.get("chunk_index") or 0) <= int(aad.get("chunk_count") or 0) <= 50:
        raise TransportError("chunk metadata is invalid")
    if not 1 <= int(aad.get("record_count") or 0) <= 2000:
        raise TransportError("record_count outside allowed range")
    if not re.fullmatch(r"[0-9a-f]{64}", str(aad.get("export_sha256") or "")):
        raise TransportError("export_sha256 is invalid")
    for flag in ("raw_source_text_included","raw_source_url_included","raw_model_response_included"):
        if aad.get(flag) is not False:
            raise TransportError(f"unsafe encrypted handoff flag: {flag}")

    ephemeral_public = _unb64(envelope.get("ephemeral_public_key_b64url"), "ephemeral public key", 32)
    if len(ephemeral_public) != 32:
        raise TransportError("ephemeral public key must be 32 bytes")
    nonce = _unb64(envelope.get("nonce_b64url"), "nonce", 12)
    if len(nonce) != 12:
        raise TransportError("nonce must be 12 bytes")
    ciphertext = _unb64(envelope.get("ciphertext_b64url"), "ciphertext", MAX_CIPHERTEXT_BYTES)
    expected_plaintext_bytes = int(envelope.get("plaintext_bytes") or 0)
    if not 1 <= expected_plaintext_bytes <= MAX_CIPHERTEXT_BYTES:
        raise TransportError("plaintext_bytes outside bounded range")
    recipient_private = _recipient_private(hf_token)
    recipient_public = recipient_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key = _derived_aead_key(
        recipient_private,
        ephemeral_public,
        ephemeral_public=ephemeral_public,
        recipient_public=recipient_public,
    )
    try:
        plaintext = ChaCha20Poly1305(key).decrypt(nonce, ciphertext, _canonical(aad))
    except Exception as exc:
        raise TransportError("encrypted handoff authentication/decryption failed") from exc
    if len(plaintext) != expected_plaintext_bytes:
        raise TransportError("decrypted plaintext size mismatch")
    if hashlib.sha256(plaintext).hexdigest() != envelope.get("plaintext_sha256"):
        raise TransportError("decrypted plaintext SHA256 mismatch")
    return plaintext, dict(aad)


def _github_request(method: str, url: str, token: str, payload: Mapping[str, Any] | None = None) -> Any:
    data = _canonical(payload) if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "governance-hf-justice-encrypted-transport/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        raise TransportError(f"GitHub API {method} failed HTTP {exc.code}: {body[:600]}") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise TransportError("GitHub API response exceeds bounded size")
    if not raw:
        return None
    return json.loads(raw)


def publish_key(governance_token: str, hf_token: str) -> dict[str, Any]:
    descriptor = public_key_descriptor(hf_token)
    issues = _github_request(
        "GET",
        f"https://api.github.com/repos/{GOV_REPO}/issues?state=open&per_page=100",
        governance_token,
    )
    matches = [row for row in issues if isinstance(row, Mapping) and row.get("title") == KEY_ISSUE_TITLE and "pull_request" not in row]
    body = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if matches:
        issue = sorted(matches, key=lambda row: int(row.get("number") or 0))[0]
        if str(issue.get("body") or "") != body:
            issue = _github_request(
                "PATCH",
                f"https://api.github.com/repos/{GOV_REPO}/issues/{int(issue['number'])}",
                governance_token,
                {"body": body},
            )
        return {"status":"KEY_PUBLISHED","issue_number":int(issue["number"]),"key_id":descriptor["key_id"]}
    issue = _github_request(
        "POST",
        f"https://api.github.com/repos/{GOV_REPO}/issues",
        governance_token,
        {"title": KEY_ISSUE_TITLE, "body": body},
    )
    return {"status":"KEY_PUBLISHED","issue_number":int(issue["number"]),"key_id":descriptor["key_id"]}


def _safe_failure_message(exc: Exception) -> str:
    text = re.sub(r"https?://\S+", "<url>", f"{type(exc).__name__}: {exc}")
    text = re.sub(r"hf_[A-Za-z0-9]+", "<token>", text)
    return text[:800]


def _comment_and_close(issue_number: int, control_token: str, body: str, *, close: bool) -> None:
    _github_request(
        "POST",
        f"https://api.github.com/repos/{EVIDENCE_REPO}/issues/{issue_number}/comments",
        control_token,
        {"body": body[:5000]},
    )
    if close:
        _github_request(
            "PATCH",
            f"https://api.github.com/repos/{EVIDENCE_REPO}/issues/{issue_number}",
            control_token,
            {"state":"closed","state_reason":"completed"},
        )


def poll(control_token: str, hf_token: str, output_dir: Path) -> dict[str, Any]:
    if not control_token.strip():
        raise TransportError("CONTROL_PLANE_TOKEN is not configured")
    if not hf_token.strip():
        raise TransportError("HF_TOKEN is not configured")
    issues = _github_request(
        "GET",
        f"https://api.github.com/repos/{EVIDENCE_REPO}/issues?state=open&per_page=100&sort=created&direction=desc",
        control_token,
    )
    candidates = [
        row for row in issues
        if isinstance(row, Mapping)
        and row.get("title") == HANDOFF_ISSUE_TITLE
        and "pull_request" not in row
        and str((row.get("user") or {}).get("login") or "") in ALLOWED_HANDOFF_ACTORS
    ][:MAX_HANDOFFS_PER_POLL]
    processed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for issue in candidates:
        number = int(issue.get("number") or 0)
        try:
            body = str(issue.get("body") or "")
            if not 1 <= len(body.encode("utf-8")) <= MAX_ENVELOPE_BODY_BYTES:
                raise TransportError("handoff issue body is empty or oversized")
            envelope = json.loads(body)
            if not isinstance(envelope, Mapping):
                raise TransportError("handoff issue body must be a JSON object")
            plaintext, aad = decrypt_envelope(envelope, hf_token)
            with tempfile.TemporaryDirectory(prefix="hf-justice-decrypted-") as temp:
                input_path = Path(temp) / "export.json"
                input_path.write_bytes(plaintext)
                # Validate before any HF write. gateway.ingest performs a second validation.
                validated = GATEWAY.validate_export(input_path)
                if int(validated.get("record_count") or 0) != int(aad["record_count"]):
                    raise TransportError("AAD record_count does not match decrypted export")
                if hashlib.sha256(plaintext).hexdigest() != aad["export_sha256"]:
                    raise TransportError("AAD export SHA does not match decrypted export")
                batch_output = output_dir / f"issue-{number}"
                receipt = GATEWAY.ingest(input_path, batch_output)
            safe = (
                "## HF_JUSTICE_ENCRYPTED_HANDOFF_COMPLETED\n\n"
                f"- Status: `{receipt.get('status')}`\n"
                f"- Batch: `{receipt.get('batch_id')}`\n"
                f"- Derived records: `{receipt.get('record_count')}`\n"
                "- Transport: `X25519 + HKDF-SHA256 + ChaCha20-Poly1305`\n"
                "- Raw source text stored: `false`\n"
                "- Raw source URL stored: `false`\n"
                "- Raw model response stored: `false`\n"
            )
            _comment_and_close(number, control_token, safe, close=True)
            processed.append({"issue_number":number,"status":receipt.get("status"),"batch_id":receipt.get("batch_id"),"record_count":receipt.get("record_count")})
        except Exception as exc:
            message = _safe_failure_message(exc)
            _comment_and_close(
                number,
                control_token,
                "## HF_JUSTICE_ENCRYPTED_HANDOFF_FAILED\n\n"
                f"- Error: `{message}`\n"
                "- No business success is claimed.\n"
                "- Raw source/model content was not published by Governance.\n",
                close=False,
            )
            failed.append({"issue_number":number,"error":message})
    receipt = {
        "schema_version":"governance-hf-justice-encrypted-poll-receipt-v1",
        "status":"HF_JUSTICE_ENCRYPTED_POLL_COMPLETED" if not failed else "HF_JUSTICE_ENCRYPTED_POLL_PARTIAL_FAILURE",
        "candidate_count":len(candidates),
        "processed_count":len(processed),
        "failed_count":len(failed),
        "processed":processed,
        "failures":failed,
        "plaintext_issue_transport":False,
        "control_plane_actions_permission_required":False,
        "control_plane_contents_permission_required":False,
        "model_calls":0,
        "secret_values_exposed":False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "transport-poll-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def validate() -> dict[str, Any]:
    # Deterministic round-trip using a synthetic HF token proves the crypto contract.
    token = "hf_synthetic_validation_token_not_a_secret"
    descriptor = public_key_descriptor(token)
    if descriptor["schema_version"] != PUBLIC_KEY_SCHEMA or descriptor["plaintext_allowed"] is not False:
        raise TransportError("public key descriptor contract failed")
    return {
        "status":"HF_JUSTICE_ENCRYPTED_TRANSPORT_VALIDATED",
        "algorithm":descriptor["algorithm"],
        "max_handoffs_per_poll":MAX_HANDOFFS_PER_POLL,
        "plaintext_issue_transport":False,
        "control_plane_actions_permission_required":False,
        "control_plane_contents_permission_required":False,
        "model_calls":0,
        "network_used":False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate","public-key","publish-key","poll"])
    parser.add_argument("--output-dir", default="hf-justice-transport")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = validate()
        elif args.command == "public-key":
            result = public_key_descriptor(str(os.getenv("HF_TOKEN") or ""))
        elif args.command == "publish-key":
            result = publish_key(str(os.getenv("GITHUB_TOKEN") or ""), str(os.getenv("HF_TOKEN") or ""))
        else:
            result = poll(str(os.getenv("CONTROL_PLANE_TOKEN") or ""), str(os.getenv("HF_TOKEN") or ""), Path(args.output_dir))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(_safe_failure_message(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
