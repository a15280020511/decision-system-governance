from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hf_justice_transport_test", ROOT / "encrypted_transport.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def make_envelope(token: str, plaintext: bytes) -> dict:
    descriptor = MODULE.public_key_descriptor(token)
    recipient_public = base64.urlsafe_b64decode(descriptor["public_key_b64url"] + "==")
    ephemeral_private = x25519.X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    shared = ephemeral_private.exchange(x25519.X25519PublicKey.from_public_bytes(recipient_public))
    salt = hashlib.sha256(ephemeral_public + recipient_public).digest()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=MODULE.KDF_CONTEXT).derive(shared)
    aad = {
        "source_repository": MODULE.EVIDENCE_REPO,
        "source_run_id": 31191782538,
        "source_commit": "a" * 40,
        "chunk_index": 1,
        "chunk_count": 1,
        "record_count": 2,
        "export_sha256": hashlib.sha256(plaintext).hexdigest(),
        "raw_source_text_included": False,
        "raw_source_url_included": False,
        "raw_model_response_included": False,
    }
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext, MODULE._canonical(aad))
    return {
        "schema_version": MODULE.ENVELOPE_SCHEMA,
        "key_id": descriptor["key_id"],
        "ephemeral_public_key_b64url": b64(ephemeral_public),
        "nonce_b64url": b64(nonce),
        "ciphertext_b64url": b64(ciphertext),
        "aad": aad,
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
        "plaintext_bytes": len(plaintext),
    }


class EncryptedTransportTests(unittest.TestCase):
    def test_public_descriptor_contains_no_secret(self) -> None:
        token = "hf_test_private_value"
        descriptor = MODULE.public_key_descriptor(token)
        rendered = json.dumps(descriptor)
        self.assertNotIn(token, rendered)
        self.assertFalse(descriptor["plaintext_allowed"])
        self.assertFalse(descriptor["raw_source_allowed"])
        self.assertEqual(len(base64.urlsafe_b64decode(descriptor["public_key_b64url"] + "==")), 32)

    def test_round_trip_authenticated_encryption(self) -> None:
        token = "hf_test_private_value"
        plaintext = b'{"schema_version":"synthetic","records":[1,2]}'
        envelope = make_envelope(token, plaintext)
        restored, aad = MODULE.decrypt_envelope(envelope, token)
        self.assertEqual(restored, plaintext)
        self.assertEqual(aad["record_count"], 2)
        self.assertFalse(aad["raw_source_text_included"])

    def test_tampered_ciphertext_is_rejected(self) -> None:
        token = "hf_test_private_value"
        plaintext = b'{"schema_version":"synthetic","records":[1,2]}'
        envelope = make_envelope(token, plaintext)
        raw = bytearray(MODULE._unb64(envelope["ciphertext_b64url"], "ciphertext", MODULE.MAX_CIPHERTEXT_BYTES))
        raw[-1] ^= 1
        envelope["ciphertext_b64url"] = b64(bytes(raw))
        with self.assertRaises(MODULE.TransportError):
            MODULE.decrypt_envelope(envelope, token)

    def test_wrong_token_is_rejected_by_key_id(self) -> None:
        plaintext = b'{"schema_version":"synthetic","records":[1,2]}'
        envelope = make_envelope("hf_token_one", plaintext)
        with self.assertRaises(MODULE.TransportError):
            MODULE.decrypt_envelope(envelope, "hf_token_two")

    def test_unsafe_aad_is_rejected(self) -> None:
        token = "hf_test_private_value"
        plaintext = b'{"schema_version":"synthetic","records":[1,2]}'
        envelope = make_envelope(token, plaintext)
        envelope["aad"]["raw_source_url_included"] = True
        with self.assertRaises(MODULE.TransportError):
            MODULE.decrypt_envelope(envelope, token)

    def test_validate_reports_no_actions_or_contents_permission(self) -> None:
        result = MODULE.validate()
        self.assertFalse(result["plaintext_issue_transport"])
        self.assertFalse(result["control_plane_actions_permission_required"])
        self.assertFalse(result["control_plane_contents_permission_required"])


if __name__ == "__main__":
    unittest.main()
