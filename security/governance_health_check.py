#!/usr/bin/env python3
"""Zero-business-call health check for governance repository identity and token scope."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HTTP_PATH = ROOT / "control-plane" / "resilient_http.py"
SPEC = importlib.util.spec_from_file_location("governance_health_http", HTTP_PATH)
HTTP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HTTP)

GOVERNANCE_REPOSITORY = "a15280020511/decision-system-governance"
CHILD_REPOSITORIES = (
    "a15280020511/evidence-data-center",
    "a15280020511/compute-simulation-center",
    "a15280020511/expert-assessment-center",
)
EXPECTED_OWNER = "a15280020511"
EXPECTED_DEFAULT_BRANCH = "main"
HTTP_CODE_RE = re.compile(r"HTTP (\d{3})")


def _request(method: str, path: str, token: str) -> Any:
    return HTTP.github_request(method, path, token=token)


def _failure_code(exc: RuntimeError) -> int:
    match = HTTP_CODE_RE.search(str(exc))
    return int(match.group(1)) if match else 0


def _expect_forbidden(path: str, token: str) -> dict[str, Any]:
    try:
        _request("GET", path, token)
    except RuntimeError as exc:
        code = _failure_code(exc)
        return {
            "path": path,
            "status": "PASS" if code in {403, 404} else "FAIL",
            "observed_http": code or "network-or-parse-error",
            "expected_http": [403, 404],
        }
    return {
        "path": path,
        "status": "FAIL",
        "observed_http": 200,
        "expected_http": [403, 404],
    }


def _repository_identity(repo: str, token: str) -> dict[str, Any]:
    row = _request("GET", f"/repos/{repo}", token)
    owner = row.get("owner") if isinstance(row, dict) and isinstance(row.get("owner"), dict) else {}
    checks = {
        "full_name": str(row.get("full_name") or "") == repo,
        "owner": str(owner.get("login") or "") == EXPECTED_OWNER,
        "default_branch": str(row.get("default_branch") or "") == EXPECTED_DEFAULT_BRANCH,
        "archived": row.get("archived") is False,
        "disabled": row.get("disabled") is False,
    }
    return {
        "repository": repo,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "visibility": str(row.get("visibility") or "unknown"),
    }


def run_check() -> dict[str, Any]:
    governance_token = os.getenv("GITHUB_TOKEN", "")
    child_token = os.getenv("CONTROL_PLANE_TOKEN", "")
    report: dict[str, Any] = {
        "schema_version": "governance-health-report-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "model_calls": 0,
        "external_business_data_calls": 0,
        "secret_values_recorded": False,
        "repositories": [],
        "issue_access": [],
        "negative_scope_checks": [],
        "errors": [],
    }

    try:
        report["repositories"].append(
            _repository_identity(GOVERNANCE_REPOSITORY, governance_token)
        )
        rows = _request(
            "GET",
            f"/repos/{GOVERNANCE_REPOSITORY}/issues?state=all&per_page=1",
            governance_token,
        )
        report["issue_access"].append(
            {
                "repository": GOVERNANCE_REPOSITORY,
                "status": "PASS" if isinstance(rows, list) else "FAIL",
                "mode": "governance-read",
            }
        )
    except RuntimeError as exc:
        report["errors"].append(
            {"scope": "governance", "error_class": type(exc).__name__}
        )

    for repo in CHILD_REPOSITORIES:
        try:
            report["repositories"].append(_repository_identity(repo, child_token))
            rows = _request(
                "GET",
                f"/repos/{repo}/issues?state=all&per_page=1",
                child_token,
            )
            report["issue_access"].append(
                {
                    "repository": repo,
                    "status": "PASS" if isinstance(rows, list) else "FAIL",
                    "mode": "child-issues-read",
                }
            )
        except RuntimeError as exc:
            report["errors"].append(
                {"scope": repo, "error_class": type(exc).__name__}
            )
        report["negative_scope_checks"].append(
            _expect_forbidden(f"/repos/{repo}/contents", child_token)
        )
        report["negative_scope_checks"].append(
            _expect_forbidden(f"/repos/{repo}/actions/secrets", child_token)
        )

    report["negative_scope_checks"].append(
        _expect_forbidden(f"/repos/{GOVERNANCE_REPOSITORY}", child_token)
    )

    statuses = [
        item.get("status")
        for section in ("repositories", "issue_access", "negative_scope_checks")
        for item in report[section]
    ]
    report["status"] = (
        "PASS"
        if statuses and all(status == "PASS" for status in statuses) and not report["errors"]
        else "FAIL"
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    failed = []
    for section in ("repositories", "issue_access", "negative_scope_checks"):
        for item in report.get(section, []):
            if item.get("status") != "PASS":
                failed.append(f"{section}: {item}")
    for item in report.get("errors", []):
        failed.append(f"error: {item}")
    lines = [
        f"## GOVERNANCE_HEALTH_{report['status']}",
        "",
        f"- Observed at: `{report['observed_at']}`",
        f"- Repository identity checks: `{len(report.get('repositories', []))}`",
        f"- Issue access checks: `{len(report.get('issue_access', []))}`",
        f"- Negative scope checks: `{len(report.get('negative_scope_checks', []))}`",
        "- Model calls: `0`",
        "- External business data calls: `0`",
        "- Secret values recorded: `false`",
    ]
    if failed:
        lines.extend(["", "### Failed checks"])
        lines.extend(f"- `{text[:1000]}`" for text in failed)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="health-artifacts/governance-health.json")
    parser.add_argument("--markdown", default="health-artifacts/governance-health.md")
    args = parser.parse_args()

    report = run_check()
    output = Path(args.output)
    markdown = Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"]}))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
