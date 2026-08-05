from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "governance-copilot" / "select_paid_high_level_model.py"


def load_base():
    spec = importlib.util.spec_from_file_location("selector_static_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_base()


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class HttpFailureTests(unittest.TestCase):
    def test_http_429_is_retried_once_then_recovers(self):
        error = base.urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "rate limited",
            hdrs=None,
            fp=io.BytesIO(b""),
        )
        response = FakeResponse(json.dumps({"data": [{"id": "ok"}]}).encode("utf-8"))
        with mock.patch.object(
            base.urllib.request,
            "urlopen",
            side_effect=[error, response],
        ) as urlopen, mock.patch.object(base.time, "sleep") as sleep:
            payload = base._fetch_json("https://example.invalid", "secret")
        self.assertEqual(payload["data"][0]["id"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_http_500_has_bounded_retry_and_fails_closed(self):
        def error():
            return base.urllib.error.HTTPError(
                "https://example.invalid",
                500,
                "server error",
                hdrs=None,
                fp=io.BytesIO(b""),
            )

        with mock.patch.object(
            base.urllib.request,
            "urlopen",
            side_effect=[error(), error()],
        ) as urlopen, mock.patch.object(base.time, "sleep"):
            with self.assertRaises(base.SelectorError):
                base._fetch_json("https://example.invalid", "secret")
        self.assertEqual(urlopen.call_count, 2)

    def test_invalid_json_has_bounded_retry_and_fails_closed(self):
        malformed = FakeResponse(b"{not-json")
        with mock.patch.object(
            base.urllib.request,
            "urlopen",
            side_effect=[malformed, malformed],
        ) as urlopen, mock.patch.object(base.time, "sleep"):
            with self.assertRaises(base.SelectorError):
                base._fetch_json("https://example.invalid", "secret")
        self.assertEqual(urlopen.call_count, 2)

    def test_non_object_json_fails_closed(self):
        response = FakeResponse(json.dumps([1, 2, 3]).encode("utf-8"))
        with mock.patch.object(
            base.urllib.request,
            "urlopen",
            side_effect=[response, response],
        ), mock.patch.object(base.time, "sleep"):
            with self.assertRaises(base.SelectorError):
                base._fetch_json("https://example.invalid", "secret")


class StaticSafetyTests(unittest.TestCase):
    def selector_sources(self) -> str:
        return "\n".join(
            path.read_text("utf-8")
            for path in sorted((ROOT / "governance-copilot").glob("*.py"))
        )

    def workflow_texts(self) -> dict[str, str]:
        paths = (
            ROOT / ".github" / "workflows" / "openrouter-selector-resilience.yml",
            ROOT / ".github" / "workflows" / "openrouter-selector-security.yml",
        )
        return {path.name: path.read_text("utf-8").lower() for path in paths}

    def test_selector_contains_no_inference_endpoint_or_post_request(self):
        source = self.selector_sources().lower()
        forbidden = (
            "/chat/completions",
            "/responses",
            "method=\"post\"",
            "method='post'",
            "requests.post",
            "httpx.post",
            "urlopen(request, data=",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)
        self.assertIn("https://openrouter.ai/api/v1/models", source)
        self.assertIn("https://openrouter.ai/api/v1/benchmarks", source)

    def test_selector_workflows_have_read_only_repository_permission(self):
        forbidden = (
            "contents: write",
            "actions: write",
            "issues: write",
            "pull-requests: write",
            "packages: write",
            "id-token: write",
        )
        for text in self.workflow_texts().values():
            self.assertIn("permissions:\n  contents: read", text)
            for marker in forbidden:
                self.assertNotIn(marker, text)

    def test_long_term_gates_cover_main_pr_schedule_and_concurrency(self):
        workflows = self.workflow_texts()
        resilience = workflows["openrouter-selector-resilience.yml"]
        security = workflows["openrouter-selector-security.yml"]
        self.assertIn("pull_request:", resilience)
        self.assertIn("pull_request:", security)
        self.assertIn("- main", resilience)
        self.assertIn("- main", security)
        self.assertIn("schedule:", resilience)
        self.assertIn('cron: "17 3 * * 1"', resilience)
        self.assertIn("concurrency:", resilience)
        self.assertIn("cancel-in-progress: true", resilience)
        self.assertIn("concurrency:", security)
        self.assertIn("cancel-in-progress: true", security)

    def test_live_check_is_blocked_until_offline_matrix_passes(self):
        resilience = self.workflow_texts()["openrouter-selector-resilience.yml"]
        self.assertIn("needs: offline-validation", resilience)
        self.assertIn("ubuntu-22.04", resilience)
        self.assertIn("ubuntu-24.04", resilience)
        self.assertIn("run three independent live catalog selections", resilience)
        self.assertIn("attempts\": 3", resilience)

    def test_secret_is_only_read_from_environment_and_never_serialized(self):
        source = self.selector_sources()
        self.assertIn('os.environ.get("OPENROUTER_API_KEY"', source)
        forbidden = (
            '"OPENROUTER_API_KEY": token',
            '"api_key": token',
            'print(token)',
            'write_text(token',
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)

    def test_network_retry_is_bounded(self):
        source = BASE_PATH.read_text("utf-8")
        self.assertIn("for attempt in range(2):", source)
        self.assertNotIn("while True", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
