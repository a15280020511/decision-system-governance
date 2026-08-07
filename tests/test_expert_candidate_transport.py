from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "control-plane" / "resilient_control.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "governance_expert_candidate_transport_test",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _large_plan(module, count: int = 1200) -> tuple[dict, list[dict]]:
    pool = []
    for index in range(count):
        entropy = "".join(
            hashlib.sha256(f"{index}:{part}".encode()).hexdigest()
            for part in range(4)
        )
        pool.append(
            {
                "model": f"vendor-{index}/reasoner-{index}",
                "company": f"vendor-{index % 37}",
                "context_length": 131072 + index,
                "max_completion_tokens": 16384,
                "prompt_usd_per_million": index / 1000 + 0.01,
                "completion_usd_per_million": index / 500 + 0.02,
                "popularity_rank": index + 1,
                "catalog_evidence": entropy,
            }
        )
    plan = {
        "schema_version": "governance-expert-dynamic-candidate-plan-v1",
        "selection_authority": "decision-system-governance",
        "candidate_pool_authority": "decision-system-governance",
        "model_assignment_authority": "expert-assessment-center-dynamic-ortools",
        "selected_models": [],
        "recovery_models": [],
        "expert_count": 0,
        "recovery_count": 0,
        "company_uniqueness_required": False,
        "fixed_team_size_required": False,
        "provider_routing_mode": "unrestricted-openrouter",
        "provider_restrictions_applied": False,
        "expert_candidate_pool": pool,
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical(plan)).hexdigest()
    return plan, pool


class ExpertCandidateTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load()

    def test_large_candidate_pool_is_removed_from_issue_body_and_chunked(self) -> None:
        plan, pool = _large_plan(self.module)
        compact, chunks = self.module._compact_plan_and_chunks(  # noqa: SLF001
            plan,
            "gov-transport-test-expert",
        )

        self.assertNotIn("expert_candidate_pool", compact)
        self.assertEqual(compact["expert_candidate_pool_size"], len(pool))
        self.assertGreater(len(chunks), 1)

        child_ticket = {
            "task_id": "gov-transport-test-expert",
            "route": "expert-team",
            "task": {
                "question": "三种备用电源 A/B/C，比较价格、续航、故障率，并分别给预算优先、可靠性优先、综合均衡建议"
            },
            "governance_model_plan": compact,
        }
        body = json.dumps(child_ticket, ensure_ascii=False, separators=(",", ":"))
        self.assertLess(len(body), 60_000)

        for chunk in chunks:
            encoded = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
            self.assertLess(len(encoded), 50_000)
            self.assertLessEqual(len(chunk["data"]), self.module.POOL_CHUNK_CHARS)

    def test_chunk_sequence_reconstructs_exact_candidate_pool_and_hashes(self) -> None:
        plan, pool = _large_plan(self.module)
        compact, chunks = self.module._compact_plan_and_chunks(  # noqa: SLF001
            plan,
            "gov-transport-test-expert",
        )
        transport = compact["expert_candidate_pool_transport"]
        self.assertEqual(transport["schema_version"], self.module.POOL_TRANSPORT_SCHEMA)
        self.assertEqual(transport["chunk_schema_version"], self.module.POOL_CHUNK_SCHEMA)
        self.assertEqual(transport["chunk_count"], len(chunks))
        self.assertEqual([row["index"] for row in chunks], list(range(1, len(chunks) + 1)))
        self.assertTrue(all(row["count"] == len(chunks) for row in chunks))
        self.assertTrue(all(row["sha256"] == transport["raw_sha256"] for row in chunks))

        encoded = "".join(row["data"] for row in chunks)
        raw = zlib.decompress(base64.b64decode(encoded.encode("ascii"), validate=True))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), transport["raw_sha256"])
        self.assertEqual(json.loads(raw.decode("utf-8")), pool)

        material = dict(compact)
        declared = material.pop("plan_sha256")
        self.assertEqual(hashlib.sha256(_canonical(material)).hexdigest(), declared)

    def test_dispatch_posts_every_chunk_before_run_command(self) -> None:
        module = self.module
        chunks = [
            {
                "schema_version": module.POOL_CHUNK_SCHEMA,
                "task_id": "gov-42-expert",
                "sha256": "a" * 64,
                "encoding": "zlib+base64",
                "index": index,
                "count": 3,
                "data": f"chunk-{index}",
            }
            for index in range(1, 4)
        ]
        posts: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "prepare-status.json").write_text(
                json.dumps(
                    {
                        "child_command": "/run-expert-team gov-42-expert",
                        "target_repository": "a15280020511/expert-assessment-center",
                    }
                ),
                encoding="utf-8",
            )
            (root / "expert-candidate-pool-chunks.json").write_text(
                json.dumps(chunks), encoding="utf-8"
            )
            args = argparse.Namespace(output_dir=directory)

            def fake_base_dispatch(arguments):
                status = json.loads(
                    (Path(arguments.output_dir) / "prepare-status.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(status["child_command"], "")
                (Path(arguments.output_dir) / "dispatch-status.json").write_text(
                    json.dumps(
                        {
                            "repository": "a15280020511/expert-assessment-center",
                            "issue_number": 999,
                        }
                    ),
                    encoding="utf-8",
                )
                return 0

            def fake_request(method, path, *, token, payload=None):
                self.assertEqual(method, "POST")
                self.assertEqual(
                    path,
                    "/repos/a15280020511/expert-assessment-center/issues/999/comments",
                )
                self.assertEqual(token, "test-token")
                posts.append(str((payload or {}).get("body") or ""))
                return {}

            with (
                mock.patch.object(module, "_BASE_DISPATCH", side_effect=fake_base_dispatch),
                mock.patch.object(module.CONTROL, "_comment_exists", return_value=False),
                mock.patch.object(module.CONTROL, "_github_request", side_effect=fake_request),
                mock.patch.dict(os.environ, {"CONTROL_PLANE_TOKEN": "test-token"}),
            ):
                self.assertEqual(module._dispatch_with_candidate_chunks(args), 0)  # noqa: SLF001

            self.assertEqual(len(posts), 4)
            posted_chunks = [json.loads(body) for body in posts[:3]]
            self.assertEqual([row["index"] for row in posted_chunks], [1, 2, 3])
            self.assertEqual(posts[-1], "/run-expert-team gov-42-expert")

            dispatch = json.loads(
                (root / "dispatch-status.json").read_text(encoding="utf-8")
            )
            self.assertTrue(dispatch["candidate_transport_completed_before_command"])
            self.assertEqual(dispatch["candidate_pool_chunks_total"], 3)
            self.assertEqual(dispatch["candidate_pool_chunks_posted"], 3)
            self.assertTrue(dispatch["command_posted"])


if __name__ == "__main__":
    unittest.main()
