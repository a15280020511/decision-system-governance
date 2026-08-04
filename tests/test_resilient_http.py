from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "resilient_http.py"
SPEC = importlib.util.spec_from_file_location("resilient_http", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.body = body.encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body


def http_error(code: int, *, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/test",
        code=code,
        msg="test",
        hdrs=headers or {},
        fp=io.BytesIO(b'{"message":"test failure"}'),
    )


class ResilientHttpTests(unittest.TestCase):
    def test_requires_token(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "token is not configured"):
            MODULE.github_request("GET", "/repos/o/r", token="")

    def test_success_parses_json_without_retry(self) -> None:
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            return_value=FakeResponse('{"ok":true}'),
        ) as urlopen, mock.patch.object(MODULE.time, "sleep") as sleep:
            result = MODULE.github_request("GET", "/repos/o/r", token="secret")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_network_failure_retries_and_recovers(self) -> None:
        side_effect = [
            urllib.error.URLError("temporary"),
            FakeResponse("[]"),
        ]
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=side_effect,
        ), mock.patch.object(MODULE.time, "sleep") as sleep:
            result = MODULE.github_request("GET", "/repos/o/r/issues", token="secret")
        self.assertEqual(result, [])
        self.assertEqual(sleep.call_count, 1)

    def test_rate_limit_403_retries(self) -> None:
        side_effect = [
            http_error(
                403,
                headers={"X-RateLimit-Remaining": "0", "Retry-After": "1"},
            ),
            FakeResponse('{"full_name":"o/r"}'),
        ]
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=side_effect,
        ), mock.patch.object(MODULE.time, "sleep") as sleep:
            result = MODULE.github_request("GET", "/repos/o/r", token="secret")
        self.assertEqual(result["full_name"], "o/r")
        sleep.assert_called_once_with(1.0)

    def test_normal_403_does_not_retry(self) -> None:
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=http_error(403, headers={"X-RateLimit-Remaining": "4999"}),
        ) as urlopen, mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                MODULE.github_request("GET", "/repos/o/r/contents", token="secret")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_429_uses_retry_after_and_is_bounded(self) -> None:
        side_effect = [
            http_error(429, headers={"Retry-After": "9999"}),
            FakeResponse("null"),
        ]
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=side_effect,
        ), mock.patch.object(MODULE.time, "sleep") as sleep:
            result = MODULE.github_request("GET", "/rate_limit", token="secret")
        self.assertIsNone(result)
        sleep.assert_called_once_with(MODULE.MAX_BACKOFF_SECONDS)

    def test_retry_audit_excludes_token_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audit = Path(temp) / "audit.jsonl"
            side_effect = [
                http_error(503),
                FakeResponse('{"token":"response-secret"}'),
            ]
            with mock.patch.dict(
                os.environ,
                {"GOVERNANCE_HTTP_AUDIT_FILE": str(audit)},
                clear=False,
            ), mock.patch.object(
                MODULE.urllib.request,
                "urlopen",
                side_effect=side_effect,
            ), mock.patch.object(MODULE.time, "sleep"):
                MODULE.github_request("GET", "/repos/o/r", token="request-secret")
            text = audit.read_text(encoding="utf-8")
            self.assertNotIn("request-secret", text)
            self.assertNotIn("response-secret", text)
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(rows[0]["event"], "request-retry")
            self.assertEqual(rows[-1]["event"], "request-recovered")

    def test_max_attempts_is_bounded(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"GOVERNANCE_HTTP_MAX_ATTEMPTS": "2"},
            clear=False,
        ), mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("down"),
        ) as urlopen, mock.patch.object(MODULE.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "network failure"):
                MODULE.github_request("GET", "/repos/o/r", token="secret")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
