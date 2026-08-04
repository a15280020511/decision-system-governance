from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "security" / "access_contract.py"
SPEC = importlib.util.spec_from_file_location("access_contract", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

OPENAPI = (ROOT / "gpts-action" / "openapi.yaml").read_text(encoding="utf-8")
WORKFLOW = (
    ROOT / ".github" / "workflows" / "control-plane-ticket.yml"
).read_text(encoding="utf-8")


class AccessContractTests(unittest.TestCase):
    def assert_rejected(self, *, openapi: str = OPENAPI, workflow: str = WORKFLOW) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_access_contract(openapi, workflow)

    def test_current_contract_passes(self) -> None:
        MODULE.validate_access_contract(OPENAPI, WORKFLOW)

    def test_comments_operation_is_read_only(self) -> None:
        self.assertIn("operationId: getDecisionTaskReceipts", OPENAPI)
        comments_section = OPENAPI.split(
            "/issues/{issue_number}/comments:", 1
        )[1]
        self.assertIn("    get:", comments_section)
        self.assertNotIn("    post:", comments_section)

    def test_rejects_direct_child_repository_path(self) -> None:
        mutated = OPENAPI.replace(
            "paths:\n",
            "paths:\n"
            "  /repos/a15280020511/evidence-data-center/issues:\n"
            "    post:\n"
            "      operationId: bypassGovernance\n",
            1,
        )
        self.assert_rejected(openapi=mutated)

    def test_rejects_patch_put_delete_and_extra_operations(self) -> None:
        for method in ("patch", "put", "delete"):
            with self.subTest(method=method):
                mutated = OPENAPI.replace(
                    "    post:\n",
                    f"    {method}:\n      operationId: forbiddenMutation\n"
                    "    post:\n",
                    1,
                )
                self.assert_rejected(openapi=mutated)

    def test_rejects_sensitive_github_api_surfaces(self) -> None:
        for fragment in (
            "/contents",
            "/git/refs",
            "/pulls",
            "/actions",
            "/workflows",
            "/secrets",
            "/hooks",
            "/deployments",
        ):
            with self.subTest(fragment=fragment):
                mutated = OPENAPI + f"\n# forbidden {fragment}\n"
                self.assert_rejected(openapi=mutated)

    def test_rejects_write_all_and_job_level_permissions(self) -> None:
        self.assert_rejected(
            workflow=WORKFLOW.replace(
                "permissions:\n  contents: read\n  issues: write\n  actions: write",
                "permissions: write-all",
                1,
            )
        )
        self.assert_rejected(
            workflow=WORKFLOW.replace(
                "jobs:\n",
                "jobs:\n  injected:\n    permissions:\n      contents: write\n"
                "    runs-on: ubuntu-latest\n    steps: []\n",
                1,
            )
        )

    def test_rejects_every_unapproved_write_grant(self) -> None:
        for permission in (
            "contents",
            "pull-requests",
            "workflows",
            "administration",
            "packages",
            "deployments",
            "id-token",
            "security-events",
            "statuses",
        ):
            with self.subTest(permission=permission):
                mutated = WORKFLOW.replace(
                    "  actions: write\n",
                    f"  actions: write\n  {permission}: write\n",
                    1,
                )
                self.assert_rejected(workflow=mutated)

    def test_rejects_persisted_checkout_credentials(self) -> None:
        self.assert_rejected(
            workflow=WORKFLOW.replace(
                "persist-credentials: false",
                "persist-credentials: true",
                1,
            )
        )

    def test_rejects_unpinned_actions(self) -> None:
        mutated = WORKFLOW.replace(
            "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
            "actions/checkout@v6",
            1,
        )
        self.assert_rejected(workflow=mutated)

    def test_rejects_pull_request_target(self) -> None:
        self.assert_rejected(
            workflow=WORKFLOW.replace("workflow_dispatch:", "pull_request_target:", 1)
        )

    def test_rejects_token_reuse_or_exfiltration(self) -> None:
        marker = "run: |\n          python control-plane/resilient_control.py dispatch"
        self.assertIn(marker, WORKFLOW)
        self.assert_rejected(
            workflow=WORKFLOW.replace(
                marker,
                "run: |\n          echo \"$CONTROL_PLANE_TOKEN\"\n"
                "          python control-plane/resilient_control.py dispatch",
                1,
            )
        )
        self.assert_rejected(
            workflow=WORKFLOW.replace(
                "CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}",
                "CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}\n"
                "          EXTRA_TOKEN_COPY: ${{ secrets.CONTROL_PLANE_TOKEN }}",
                1,
            )
        )


if __name__ == "__main__":
    unittest.main()
