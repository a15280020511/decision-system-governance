"""Run one paid OpenRouter governance-copilot canary and validate its output.

The canary is intentionally separate from the zero-inference selector. It makes
exactly one model request, grants no repository or tool capability, and writes a
sanitized receipt. Failure is closed: there is no fallback model and no retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Mapping

CHAT_API = "https://openrouter.ai/api/v1/chat/completions"
REQUIRED_CATEGORIES = {"permission", "secret", "loop", "topology"}

SYSTEM_PROMPT = """You are the read-only governance copilot for a four-repository decision system.
You may diagnose and propose changes, but you cannot execute tools, modify repositories,
merge pull requests, change secrets, or directly control a business center.
Return only one compact JSON object. Do not use Markdown fences or prose outside JSON."""

USER_PROMPT = """Audit this synthetic governance change and propose the smallest safe correction.
The architecture requires every business center to communicate only through
decision-system-governance; direct center-to-center dispatch is forbidden.

```yaml
name: unsafe-governance-change
permissions:
  contents: write
steps:
  - run: |
      python - <<'PY'
      import os
      print(os.environ.get('OPENROUTER_API_KEY'))
      while True:
          dispatch('evidence-data-center', 'compute-simulation-center')
      PY
```

Return exactly these fields:
{
  "verdict": "REVISE",
  "recommended_route": ["decision-system-governance"],
  "critical_findings": [
    {
      "category": "permission|secret|loop|topology",
      "evidence": "specific evidence from the change",
      "remediation": "specific minimal correction"
    }
  ],
  "minimal_patch_plan": ["ordered minimal edits"],
  "required_tests": ["tests that prove the correction"],
  "rollback_plan": ["safe rollback actions"],
  "confidence": 0.0
}

The findings must independently cover permission scope, secret exposure, unbounded
execution, and forbidden topology. Keep the complete JSON concise."""


class CanaryError(RuntimeError):
    """Raised when the paid canary request or response fails validation."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CanaryError(f"{field} is not numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise CanaryError(f"{field} must be finite and nonnegative")
    return number


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def validate_model_content(content: str) -> dict[str, Any]:
    """Validate the governance reasoning contract without subjective grading."""
    if not isinstance(content, str) or not content.strip():
        raise CanaryError("model returned empty content")
    try:
        payload = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise CanaryError("model content is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CanaryError("model content is not a JSON object")

    required = {
        "verdict",
        "recommended_route",
        "critical_findings",
        "minimal_patch_plan",
        "required_tests",
        "rollback_plan",
        "confidence",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise CanaryError(f"model content is missing fields: {missing}")
    if payload["verdict"] != "REVISE":
        raise CanaryError("unsafe change was not rejected")
    if payload["recommended_route"] != ["decision-system-governance"]:
        raise CanaryError("model recommended an invalid repository route")

    findings = payload["critical_findings"]
    if not isinstance(findings, list) or len(findings) < 4:
        raise CanaryError("fewer than four independent critical findings")
    categories: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise CanaryError("critical finding is not an object")
        category = finding.get("category")
        evidence = finding.get("evidence")
        remediation = finding.get("remediation")
        if category not in REQUIRED_CATEGORIES:
            raise CanaryError(f"unexpected finding category: {category}")
        if not isinstance(evidence, str) or not evidence.strip():
            raise CanaryError(f"finding {category} has no evidence")
        if not isinstance(remediation, str) or not remediation.strip():
            raise CanaryError(f"finding {category} has no remediation")
        categories.add(category)
    if categories != REQUIRED_CATEGORIES:
        raise CanaryError(
            f"finding categories do not cover the full contract: {sorted(categories)}"
        )

    for field, minimum in (
        ("minimal_patch_plan", 3),
        ("required_tests", 3),
        ("rollback_plan", 1),
    ):
        value = payload[field]
        if not isinstance(value, list) or len(value) < minimum:
            raise CanaryError(f"{field} is incomplete")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise CanaryError(f"{field} contains an empty item")

    confidence = _finite_nonnegative(payload["confidence"], "confidence")
    if confidence > 1:
        raise CanaryError("confidence must be between 0 and 1")
    payload["confidence"] = confidence
    return payload


def _post_one_request(token: str, model_id: str) -> Mapping[str, Any]:
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        CHAT_API,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "decision-system-governance-paid-canary/1.0",
            "X-Title": "Decision System Governance Paid Canary",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CanaryError(f"single paid canary request failed: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CanaryError("OpenRouter canary response is not a JSON object")
    return payload


def run_canary(token: str, cost_selection: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(cost_selection.get("selected_model"))
    model_id = selected.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise CanaryError("cost selection has no selected model")

    response = _post_one_request(token, model_id)
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise CanaryError("OpenRouter response does not contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise CanaryError("OpenRouter choice is not an object")
    message = _mapping(choice.get("message"))
    content = message.get("content")
    validated = validate_model_content(content)

    usage = _mapping(response.get("usage"))
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    if prompt_tokens < 0 or completion_tokens < 0 or total_tokens < 0:
        raise CanaryError("OpenRouter returned invalid usage")

    prompt_rate = _finite_nonnegative(
        selected.get("prompt_usd_per_million"), "prompt_usd_per_million"
    )
    completion_rate = _finite_nonnegative(
        selected.get("completion_usd_per_million"),
        "completion_usd_per_million",
    )
    request_raw = selected.get("request_usd")
    request_fee = (
        0.0
        if request_raw in {None, ""}
        else _finite_nonnegative(request_raw, "request_usd")
    )
    estimated_actual_cost = (
        prompt_rate * prompt_tokens / 1_000_000
        + completion_rate * completion_tokens / 1_000_000
        + request_fee
    )

    return {
        "schema_version": "governance-openrouter-paid-canary-v1",
        "status": "PAID_GOVERNANCE_COPILOT_CANARY_PASS",
        "requested_model": model_id,
        "response_model": response.get("model"),
        "response_id": response.get("id"),
        "validation": {
            "verdict": validated["verdict"],
            "recommended_route": validated["recommended_route"],
            "finding_categories": sorted(
                finding["category"] for finding in validated["critical_findings"]
            ),
            "patch_plan_items": len(validated["minimal_patch_plan"]),
            "required_test_items": len(validated["required_tests"]),
            "rollback_items": len(validated["rollback_plan"]),
            "confidence": validated["confidence"],
        },
        "validated_model_output": validated,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "estimated_actual_cost_usd": estimated_actual_cost,
        "prompt_sha256": hashlib.sha256(
            (SYSTEM_PROMPT + "\n" + USER_PROMPT).encode("utf-8")
        ).hexdigest(),
        "source_cost_selection_sha256": hashlib.sha256(
            json.dumps(cost_selection, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "model_calls": 1,
        "fallback_model_calls": 0,
        "secret_values_exposed": False,
        "repository_write_capability": False,
        "tool_capability": False,
    }


def write_receipts(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "paid-canary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validation = _mapping(result.get("validation"))
    usage = _mapping(result.get("usage"))
    lines = [
        "# 治理副驾驶真实付费 Canary",
        "",
        f"- 状态：`{result.get('status')}`",
        f"- 请求模型：`{result.get('requested_model')}`",
        f"- 响应模型：`{result.get('response_model')}`",
        f"- Verdict：`{validation.get('verdict')}`",
        f"- 覆盖类别：`{validation.get('finding_categories')}`",
        f"- 输入 Token：`{usage.get('prompt_tokens')}`",
        f"- 输出 Token：`{usage.get('completion_tokens')}`",
        f"- 估算实际费用：`${float(result.get('estimated_actual_cost_usd', 0)):.8f}`",
        "- 模型调用：`1`",
        "- Fallback：`0`",
        "- 仓库写权限：`false`",
        "- 工具权限：`false`",
        "- Secret暴露：`false`",
        "",
    ]
    (output_dir / "paid-canary.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True)
    parser.add_argument("--output-dir", default="governance-paid-canary")
    args = parser.parse_args()

    token = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token:
        raise SystemExit("OPENROUTER_API_KEY is empty")
    selection = json.loads(Path(args.selection).read_text("utf-8"))
    if not isinstance(selection, Mapping):
        raise SystemExit("cost selection is not a JSON object")
    result = run_canary(token, selection)
    write_receipts(result, Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
