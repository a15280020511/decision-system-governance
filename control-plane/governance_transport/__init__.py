"""Internal zero-third-party transport and reliability primitives.

This package is private to the governance repository. It intentionally uses
only the Python 3.12 standard library so the production control path does not
depend on PyPI availability, a package resolver, or a long-running service.
"""
from .client import API_ROOT, GitHubRequestError, github_request
from .diagnostics import (
    comment_readback_verified,
    issue_readback_verified,
    repository_metadata_verified,
)
from .idempotency import (
    CLIENT_REQUEST_ID_RE,
    SUPPORTED,
    V3,
    V4,
    fingerprint_packet,
    is_canonical_client_request_id,
    normalize_client_request_id,
    packet_from_text,
)
from .status import append_machine_status, build_machine_status

__all__ = [
    "API_ROOT",
    "CLIENT_REQUEST_ID_RE",
    "GitHubRequestError",
    "SUPPORTED",
    "V3",
    "V4",
    "append_machine_status",
    "build_machine_status",
    "comment_readback_verified",
    "fingerprint_packet",
    "github_request",
    "is_canonical_client_request_id",
    "issue_readback_verified",
    "normalize_client_request_id",
    "packet_from_text",
    "repository_metadata_verified",
]
