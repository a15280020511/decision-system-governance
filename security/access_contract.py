from __future__ import annotations

import re
from pathlib import Path

GOVERNANCE_REPOSITORY = "a15280020511/decision-system-governance"
CHILD_REPOSITORIES = {
    "a15280020511/evidence-data-center",
    "a15280020511/compute-simulation-center",
    "a15280020511/expert-assessment-center",
}
EXPECTED_PATHS = {
    f"/repos/{GOVERNANCE_REPOSITORY}/issues:",
    f"/repos/{GOVERNANCE_REPOSITORY}/issues/{{issue_number}}:",
}
EXPECTED_TOP_LEVEL_PERMISSIONS = {
    "contents: read",
    "issues: write",
    "actions: write",
}
FORBIDDEN_OPENAPI_FRAGMENTS = {
    "/contents",
    "/git/refs",
    "/pulls",
    "/actions",
    "/workflows",
    "/secrets",
    "/variables",
    "/environments",
    "/hooks",
    "/deployments",
    "/releases",
    "/collaborators",
}
ALLOWED_WRITE_GRANTS = {"issues", "actions"}


def validate_access_contract(openapi: str, workflow: str) -> None:
    errors: list[str] = []

    actual_paths = {
        line.strip()
        for line in openapi.splitlines()
        if re.fullmatch(r"/repos/[^:]+:", line.strip())
    }
    if actual_paths != EXPECTED_PATHS:
        errors.append(
            "GPT Action paths must be exactly "
            f"{sorted(EXPECTED_PATHS)}; got {sorted(actual_paths)}"
        )

    for repository in CHILD_REPOSITORIES:
        if repository in openapi:
            errors.append(f"GPT Action exposes child repository: {repository}")

    methods = re.findall(
        r"(?mi)^    (get|post|patch|put|delete|options|head|trace):\s*$",
        openapi,
    )
    if methods != ["post", "get"]:
        errors.append(f"GPT Action methods must be exactly ['post', 'get']; got {methods}")

    if openapi.count("operationId:") != 2:
        errors.append("GPT Action must expose exactly two operations")

    if "type: http" not in openapi or "scheme: bearer" not in openapi:
        errors.append("GPT Action must use bearer-token authentication")

    for fragment in FORBIDDEN_OPENAPI_FRAGMENTS:
        if fragment in openapi:
            errors.append(f"GPT Action contains forbidden API surface: {fragment}")

    permission_headers = re.findall(r"(?m)^(\s*)permissions:(?:\s*(\S.*))?$", workflow)
    if len(permission_headers) != 1 or permission_headers[0][0] != "":
        errors.append(
            "control-plane workflow must contain exactly one top-level permissions block"
        )
    elif permission_headers[0][1]:
        errors.append("top-level permissions must be an explicit mapping")

    top_permissions_match = re.search(
        r"(?ms)^permissions:\n(?P<body>(?:^[ \t].*\n)+)",
        workflow,
    )
    if not top_permissions_match:
        errors.append("control-plane workflow top-level permissions not found")
    else:
        normalized = {
            line.strip()
            for line in top_permissions_match.group("body").splitlines()
            if line.strip()
        }
        if normalized != EXPECTED_TOP_LEVEL_PERMISSIONS:
            errors.append(
                "control-plane permissions must be exactly "
                f"{sorted(EXPECTED_TOP_LEVEL_PERMISSIONS)}; got {sorted(normalized)}"
            )

    if re.search(r"(?mi)^\s*permissions:\s*(write-all|read-all)\s*$", workflow):
        errors.append("workflow-wide permission aliases are forbidden")

    write_grants = set(
        re.findall(r"(?mi)^\s*([a-z0-9-]+):\s*write\s*$", workflow)
    )
    unexpected_writes = sorted(write_grants - ALLOWED_WRITE_GRANTS)
    if unexpected_writes:
        errors.append(f"forbidden write grants detected: {unexpected_writes}")

    if workflow.count("persist-credentials: false") != 1:
        errors.append("checkout must disable persisted credentials exactly once")
    if "persist-credentials: true" in workflow:
        errors.append("persisted checkout credentials are forbidden")

    action_uses = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", workflow)
    unpinned = [
        value
        for value in action_uses
        if not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value)
    ]
    if unpinned:
        errors.append(f"third-party actions must be pinned by commit SHA: {unpinned}")

    if "pull_request_target:" in workflow:
        errors.append("pull_request_target is forbidden")

    token_lines = [
        line.strip()
        for line in workflow.splitlines()
        if "CONTROL_PLANE_TOKEN" in line
    ]
    expected_token_line = "CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}"
    if token_lines != [expected_token_line, expected_token_line]:
        errors.append(
            "CONTROL_PLANE_TOKEN must appear exactly twice as a step env assignment; "
            f"got {token_lines}"
        )

    exfiltration_patterns = (
        r"(?i)\becho\b.*CONTROL_PLANE_TOKEN",
        r"(?i)\bprintf\b.*CONTROL_PLANE_TOKEN",
        r"(?i)\bcat\b.*CONTROL_PLANE_TOKEN",
        r"(?i)\bset\s+-x\b",
        r"(?i)ACTIONS_STEP_DEBUG",
    )
    for pattern in exfiltration_patterns:
        if re.search(pattern, workflow):
            errors.append(f"possible token exfiltration or debug tracing detected: {pattern}")

    if errors:
        raise ValueError("\n".join(errors))


def main() -> int:
    openapi = Path("gpts-action/openapi.yaml").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/control-plane-ticket.yml").read_text(
        encoding="utf-8"
    )
    validate_access_contract(openapi, workflow)
    print("GPTs access contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
