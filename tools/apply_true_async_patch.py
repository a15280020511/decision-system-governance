#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "control-plane"

ASYNC_MODULE = r'''#!/usr/bin/env python3
"""True asynchronous governance reconciliation for open dispatched tasks.

The dispatch worker never waits for a child terminal.  This reconciler polls
only the oldest open CONTROL_DISPATCHED Issue, preserves the single global slot,
validates trusted bot and Artifact contracts, and wakes the next FIFO task only
after the current Issue reaches a terminal state.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
POLL_INTERVAL_SECONDS = 300
RECOVERY_AFTER_SECONDS = 900
ROUTE_DEADLINES = {
    "intelligence": 7_200,
    "compute": 7_200,
    "expert": 10_800,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTROL = _load("governance_async_control", ROOT / "control_plane.py")
DEFERRED = _load("governance_async_terminal", ROOT / "deferred_poll.py")
HTTP = _load("governance_async_http", ROOT / "resilient_http.py")
CONTROL._github_request = HTTP.github_request
CONTROL._trusted_terminal = DEFERRED.trusted_terminal


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("issue updated_at is missing")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def candidate(issue: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(issue.get("state") or "") != "open" or not CONTROL._is_owned_control_issue(issue):
        return None
    body = str(issue.get("body") or "")
    if CONTROL._governance_status_heading(body) != "## CONTROL_DISPATCHED":
        return None
    route_match = CONTROL.ROUTE_RE.search(body)
    task_match = CONTROL.TASK_ID_RE.search(body)
    child_match = CONTROL.CHILD_ISSUE_RE.search(body)
    if not route_match or not task_match or not child_match:
        return None
    route = route_match.group(1)
    issue_number = int(issue.get("number") or 0)
    if route not in CONTROL.ROUTES or issue_number <= 0:
        return None
    task_id = task_match.group(1)
    child_repository = child_match.group(1)
    child_issue_number = int(child_match.group(2))
    if task_id != CONTROL._generated_task_id(issue_number, route):
        return None
    if child_repository != CONTROL.ROUTES[route]["repository"]:
        return None
    return {
        "governance_issue_number": issue_number,
        "governance_body": body,
        "route": route,
        "task_id": task_id,
        "child_repository": child_repository,
        "child_issue_number": child_issue_number,
        "child_issue_url": f"https://github.com/{child_repository}/issues/{child_issue_number}",
        "updated_at": _parse_time(issue.get("updated_at")),
    }


def age_seconds(item: Mapping[str, Any], now: datetime | None = None) -> int:
    observed = now or datetime.now(timezone.utc)
    updated_at = item["updated_at"]
    if not isinstance(updated_at, datetime):
        raise TypeError("candidate updated_at must be datetime")
    return max(0, int((observed - updated_at).total_seconds()))


def render_terminal(item: Mapping[str, Any], terminal: tuple[str, str, bool]) -> str:
    heading, child_body, success = terminal
    return "\n".join([
        "## CONTROL_COMPLETED" if success else "## CONTROL_FAILED",
        "",
        f"- Task ID: `{item['task_id']}`",
        f"- Route: `{item['route']}`",
        f"- Child status: `{heading}`",
        f"- Child Issue: {item['child_issue_url']}",
        "- Reconciliation mode: `asynchronous scheduled polling`",
        f"- Poll interval target: `{POLL_INTERVAL_SECONDS} seconds`",
        "- Runner-held waiting: `false`",
        "- Authoritative result: `trusted github-actions[bot] terminal comment and validated child Artifact`",
        "",
        "<details><summary>Trusted terminal excerpt</summary>",
        "",
        child_body[:12000],
        "",
        "</details>",
    ])


def render_deadline(item: Mapping[str, Any], elapsed: int) -> str:
    return "\n".join([
        "## CONTROL_FAILED",
        "",
        f"- Task ID: `{item['task_id']}`",
        f"- Route: `{item['route']}`",
        "- Child status: `CONTROL_ASYNC_DEADLINE_EXCEEDED`",
        f"- Child Issue: {item['child_issue_url']}",
        f"- Elapsed seconds: `{elapsed}`",
        f"- Route deadline seconds: `{ROUTE_DEADLINES[item['route']]}`",
        "- Reconciliation mode: `asynchronous scheduled polling`",
        "- Runner-held waiting: `false`",
        "- Late trusted terminal reconciliation: `enabled`",
        "- Business success claimed: `false`",
    ])


def _finalize(
    *,
    governance_token: str,
    repository: str,
    item: Mapping[str, Any],
    receipt: str,
    success: bool,
) -> None:
    issue_number = int(item["governance_issue_number"])
    body = CONTROL._compose_text(str(item["governance_body"]), receipt)
    CONTROL._github_request(
        "POST",
        f"/repos/{repository}/issues/{issue_number}/comments",
        token=governance_token,
        payload={"body": receipt},
    )
    CONTROL._github_request(
        "PATCH",
        f"/repos/{repository}/issues/{issue_number}",
        token=governance_token,
        payload={
            "body": body,
            "state": "closed",
            "state_reason": "completed" if success else "not_planned",
        },
    )


def _wake_next(governance_token: str, repository: str) -> None:
    CONTROL._github_request(
        "POST",
        f"/repos/{repository}/actions/workflows/control-plane-ticket.yml/dispatches",
        token=governance_token,
        payload={"ref": "main"},
    )


def reconcile(repository: str, *, now: datetime | None = None) -> dict[str, Any]:
    governance_token = os.getenv("GITHUB_TOKEN", "")
    child_token = os.getenv("CONTROL_PLANE_TOKEN", "")
    open_issues = CONTROL._eligible_open_issues(
        CONTROL._list_issues(governance_token, repository, state="open")
    )
    candidates = [item for item in (candidate(issue) for issue in open_issues) if item]
    if not candidates:
        return {"status": "NO_ASYNC_TASK", "checked": 0, "finalized": 0, "waiting": 0}

    item = sorted(candidates, key=lambda row: int(row["governance_issue_number"]))[0]
    comments = CONTROL._list_comments(
        child_token,
        str(item["child_repository"]),
        int(item["child_issue_number"]),
    )
    terminal = DEFERRED.trusted_terminal(
        comments,
        route=str(item["route"]),
        expected_task_id=str(item["task_id"]),
    )
    elapsed = age_seconds(item, now)
    recovery_attempted = False
    if terminal:
        receipt = render_terminal(item, terminal)
        _finalize(
            governance_token=governance_token,
            repository=repository,
            item=item,
            receipt=receipt,
            success=terminal[2],
        )
        _wake_next(governance_token, repository)
        return {
            "status": "ASYNC_TERMINAL_FINALIZED",
            "checked": 1,
            "finalized": 1,
            "waiting": 0,
            "success": terminal[2],
            "child_status": terminal[0],
            "elapsed_seconds": elapsed,
            "recovery_attempted": False,
        }

    deadline = ROUTE_DEADLINES[str(item["route"])]
    if elapsed >= deadline:
        receipt = render_deadline(item, elapsed)
        _finalize(
            governance_token=governance_token,
            repository=repository,
            item=item,
            receipt=receipt,
            success=False,
        )
        _wake_next(governance_token, repository)
        return {
            "status": "ASYNC_DEADLINE_FINALIZED",
            "checked": 1,
            "finalized": 1,
            "waiting": 0,
            "success": False,
            "child_status": "CONTROL_ASYNC_DEADLINE_EXCEEDED",
            "elapsed_seconds": elapsed,
            "recovery_attempted": False,
        }

    if elapsed >= RECOVERY_AFTER_SECONDS and not CONTROL._trusted_bot_activity(comments):
        recovery_attempted = CONTROL._perform_one_recovery(
            token=child_token,
            repo=str(item["child_repository"]),
            issue_number=int(item["child_issue_number"]),
            route=str(item["route"]),
            task_id=str(item["task_id"]),
            comments=comments,
        )
    return {
        "status": "ASYNC_WAITING",
        "checked": 1,
        "finalized": 0,
        "waiting": 1,
        "success": None,
        "child_status": None,
        "elapsed_seconds": elapsed,
        "deadline_seconds": deadline,
        "recovery_attempted": recovery_attempted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    result = reconcile(args.repository)
    for key, value in result.items():
        CONTROL._write_output(key, str(value).lower() if isinstance(value, bool) else value)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = r'''from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "control-plane" / "async_reconcile.py"
SPEC = importlib.util.spec_from_file_location("async_reconcile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AsyncReconcileTests(unittest.TestCase):
    def issue(self, *, number: int = 42, route: str = "compute", state: str = "open") -> dict:
        repo = MODULE.CONTROL.ROUTES[route]["repository"]
        task_id = f"gov-{number}-{route}"
        body = "\n".join([
            '{"schema_version":"governance-control-ticket-v3"}',
            "",
            "---",
            "",
            MODULE.CONTROL.STATUS_START,
            "## CONTROL_DISPATCHED",
            "",
            f"- Task ID: `{task_id}`",
            f"- Route: `{route}`",
            f"- Child Issue: https://github.com/{repo}/issues/7",
            MODULE.CONTROL.STATUS_END,
        ])
        return {
            "number": number,
            "title": "[control]",
            "state": state,
            "body": body,
            "updated_at": "2026-08-05T00:00:00Z",
            "user": {"login": MODULE.CONTROL.OWNER},
        }

    def test_candidate_is_owner_task_and_route_bound(self):
        item = MODULE.candidate(self.issue())
        self.assertIsNotNone(item)
        self.assertEqual(item["task_id"], "gov-42-compute")
        self.assertEqual(item["child_repository"], "a15280020511/compute-simulation-center")

    def test_closed_or_wrong_task_is_rejected(self):
        self.assertIsNone(MODULE.candidate(self.issue(state="closed")))
        wrong = self.issue()
        wrong["body"] = wrong["body"].replace("gov-42-compute", "wrong")
        self.assertIsNone(MODULE.candidate(wrong))

    def test_deadline_is_route_specific_without_runner_wait(self):
        item = MODULE.candidate(self.issue(route="expert"))
        now = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(MODULE.age_seconds(item, now), 14400)
        receipt = MODULE.render_deadline(item, 14400)
        self.assertIn("CONTROL_ASYNC_DEADLINE_EXCEEDED", receipt)
        self.assertIn("Runner-held waiting: `false`", receipt)

    def test_terminal_receipt_declares_scheduled_polling(self):
        item = MODULE.candidate(self.issue())
        receipt = MODULE.render_terminal(
            item,
            ("COMPUTE_COMPLETED", "## COMPUTE_COMPLETED\n\n- Task ID: `gov-42-compute`", True),
        )
        self.assertTrue(receipt.startswith("## CONTROL_COMPLETED"))
        self.assertIn("asynchronous scheduled polling", receipt)
        self.assertIn("Runner-held waiting: `false`", receipt)


if __name__ == "__main__":
    unittest.main()
'''

DOC = '''# True asynchronous control polling

The governance control plane now separates dispatch from terminal collection.

1. `Governance Control Plane` validates and dispatches the oldest FIFO task.
2. After `CONTROL_DISPATCHED`, that workflow exits and releases its Runner.
3. The open governance Issue remains the single global-slot lock.
4. `Governance Async Terminal Reconciliation` polls every five minutes.
5. Only a matching `github-actions[bot]` terminal with the route-specific Artifact contract can close the task.
6. Closing the task wakes the next FIFO worker.

This is scheduled polling, not a permanent socket or live connection.  GitHub may
delay a cron run, so the five-minute interval is a target rather than a strict
real-time SLA.  A delay affects result delivery latency, not the child center's
calculation quality.  Route deadlines are two hours for intelligence and compute
and three hours for expert work; late trusted terminals remain eligible for the
existing closed-Issue reconciliation path.
'''


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


write(CONTROL / "async_reconcile.py", ASYNC_MODULE)
write(ROOT / "tests" / "test_async_reconcile.py", TEST)
write(ROOT / "ASYNC_CONTROL_POLLING.md", DOC)

control_path = CONTROL / "control_plane.py"
text = control_path.read_text(encoding="utf-8")
needle = '''    issue = queue[0]\n    issue_number = int(issue["number"])\n    request_body = _original_request_body(str(issue.get("body") or ""))\n'''
replacement = '''    issue = queue[0]\n    issue_number = int(issue["number"])\n    request_body = _original_request_body(str(issue.get("body") or ""))\n    current_heading = _governance_status_heading(str(issue.get("body") or ""))\n    if current_heading == "## CONTROL_DISPATCHED":\n        status = {\n            "has_task": False,\n            "in_flight": True,\n            "pending_count": len(queue),\n            "issue_number": issue_number,\n            "issue_url": str(issue.get("html_url") or ""),\n            "reason": "oldest governance task is asynchronously waiting for a child terminal",\n        }\n        _write_json(root / "selection-status.json", status)\n        for key, value in status.items():\n            _write_output(key, str(value).lower() if isinstance(value, bool) else value)\n        return 0\n'''
if needle not in text:
    raise SystemExit("control-plane select insertion point not found")
text = text.replace(needle, replacement, 1)
text = text.replace('"CONTROL_TIMEOUT",\n        "CONTROL_MONITOR_ERROR",', '"CONTROL_TIMEOUT",\n        "CONTROL_MONITOR_ERROR",\n        "CONTROL_ASYNC_DEADLINE_EXCEEDED",')
control_path.write_text(text, encoding="utf-8")

workflow_path = ROOT / ".github" / "workflows" / "control-plane-ticket.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("timeout-minutes: 50", "timeout-minutes: 20", 1)
workflow = workflow.replace(
    '      - name: Report empty queue\n        if: steps.select.outputs.has_task != \'true\'\n        run: echo "No owned open [control] Issue is waiting."\n',
    '      - name: Report queue or asynchronous in-flight state\n        if: steps.select.outputs.has_task != \'true\'\n        env:\n          IN_FLIGHT: ${{ steps.select.outputs.in_flight || \'false\' }}\n          ISSUE_NUMBER: ${{ steps.select.outputs.issue_number || \'\' }}\n        run: |\n          if [ "$IN_FLIGHT" = "true" ]; then\n            echo "Governance Issue #${ISSUE_NUMBER} is asynchronously waiting; no Runner is held."\n          else\n            echo "No owned open [control] Issue is waiting."\n          fi\n',
    1,
)
pattern = re.compile(
    r"\n      - name: Monitor trusted child terminal status[\s\S]*?\n      - name: Upload governance control evidence",
    re.MULTILINE,
)
replacement_block = '''
      - name: Record asynchronous handoff
        if: steps.dispatch.outcome == 'success'
        run: |
          cat > control-artifacts/async-handoff.json <<EOF
          {
            "schema_version": "governance-async-handoff-v1",
            "status": "CONTROL_DISPATCHED",
            "runner_held_waiting": false,
            "poll_owner": "control-plane-reconcile.yml",
            "poll_interval_target_seconds": 300,
            "legacy_wait_seconds_used_for_blocking": false
          }
          EOF

      - name: Upload governance control evidence'''
workflow, count = pattern.subn(replacement_block, workflow, count=1)
if count != 1:
    raise SystemExit("control workflow monitor block not found")
workflow = workflow.replace(
    '''          if [ "${{ steps.dispatch.outcome }}" != "success" ]; then
            exit 1
          fi
          if [ "${{ steps.monitor.outputs.success }}" != "true" ]; then
            exit 1
          fi
''',
    '''          if [ "${{ steps.dispatch.outcome }}" != "success" ]; then
            exit 1
          fi
          echo "Dispatch accepted; terminal collection is delegated to asynchronous reconciliation."
''',
    1,
)
if "steps.monitor" in workflow or "deferred_poll.py" in workflow:
    raise SystemExit("synchronous monitor references remain in control workflow")
workflow_path.write_text(workflow, encoding="utf-8")

reconcile_path = ROOT / ".github" / "workflows" / "control-plane-reconcile.yml"
reconcile_workflow = '''name: Governance Async Terminal Reconciliation

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"

permissions:
  contents: read
  issues: write
  actions: write

concurrency:
  group: governance-control-global-worker
  cancel-in-progress: false

jobs:
  reconcile:
    runs-on: ubuntu-24.04
    timeout-minutes: 12
    steps:
      - name: Checkout governance control plane
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          persist-credentials: false
      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: "3.12"
      - name: Reconcile oldest open asynchronous task
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}
          GOVERNANCE_HTTP_AUDIT_FILE: async-reconcile-http-audit.jsonl
          GOVERNANCE_HTTP_MAX_ATTEMPTS: "4"
        run: |
          python control-plane/async_reconcile.py \
            --repository "$GITHUB_REPOSITORY"
      - name: Reconcile closed late terminal results
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          CONTROL_PLANE_TOKEN: ${{ secrets.CONTROL_PLANE_TOKEN }}
          GOVERNANCE_HTTP_AUDIT_FILE: late-reconcile-http-audit.jsonl
          GOVERNANCE_HTTP_MAX_ATTEMPTS: "4"
        run: |
          python control-plane/deferred_reconcile.py \
            --repository "$GITHUB_REPOSITORY"
'''
reconcile_path.write_text(reconcile_workflow, encoding="utf-8")

status_path = CONTROL / "status-dictionary.json"
status = json.loads(status_path.read_text(encoding="utf-8"))
statuses = status["statuses"]
statuses["CONTROL_ASYNC_DEADLINE_EXCEEDED"] = {
    "terminal": False,
    "meaning": "异步轮询超过路由期限，治理任务关闭为未确认成功，但子任务可能仍会迟到完成。",
    "next_action": "不得重复宣称成功；等待迟到可信终态对账，或依据子中心证据决定是否重新提交。",
}
truth = status.setdefault("truth_rules", [])
line = "Scheduled polling releases the dispatch Runner; cron delay changes delivery latency, not child computation quality."
if line not in truth:
    truth.append(line)
status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

p1_path = ROOT / "tests" / "test_p1_operational_contract.py"
p1 = p1_path.read_text(encoding="utf-8")
p1 = p1.replace('        self.assertIn("python control-plane/deferred_poll.py", CONTROL_WORKFLOW)\n', '        self.assertNotIn("python control-plane/deferred_poll.py", CONTROL_WORKFLOW)\n        self.assertIn("poll_owner", CONTROL_WORKFLOW)\n        self.assertIn("runner_held_waiting", CONTROL_WORKFLOW)\n')
p1 = p1.replace('            "CONTROL_MONITOR_ERROR",\n', '            "CONTROL_MONITOR_ERROR",\n            "CONTROL_ASYNC_DEADLINE_EXCEEDED",\n')
p1_path.write_text(p1, encoding="utf-8")

runbook_path = ROOT / "CONTROL_PLANE_RUNBOOK.md"
runbook = runbook_path.read_text(encoding="utf-8")
runbook = runbook.replace(
    "提交是异步的。GPTs 创建一次 `[control]` Issue 后立即保存 Issue 编号，后续只轮询同一个 Issue；禁止通过再次创建 Issue 重试。",
    "提交与内部执行现在都是真异步。GPTs 创建一次 `[control]` Issue 后立即保存 Issue 编号；治理 worker 派发子任务后立即释放 Runner，独立对账工作流每5分钟读取同一个任务的可信终态。禁止通过再次创建 Issue 重试。",
)
runbook = runbook.replace("- 每 15 分钟执行一次恢复扫描，补偿丢失或被替换的 Actions 事件；", "- 主队列每15分钟执行恢复扫描；子中心终态由独立工作流每5分钟异步轮询；")
runbook = runbook.replace("`wait_seconds` 不参与业务身份，因此仅修改等待时间不能绕过去重。", "`wait_seconds` 为旧接口兼容字段，不再用于占用 Runner 等待；它仍不参与业务身份，因此不能用于绕过去重。")
insert = "\n## 内部异步轮询\n\n- 派发工作流不再现场等待子中心，不维持长连接，也不执行30秒循环轮询；\n- `CONTROL_DISPATCHED` 的开放 Issue 本身就是全局槽锁，下一任务不能越过它；\n- 独立对账工作流以5分钟为目标间隔运行；GitHub cron 可能延迟，因此不是严格实时 SLA；\n- cron 延迟只增加最终回执的送达时间，不改变子中心已经独立执行的模型、计算或采集质量；\n- 情报和计算路由期限为2小时，专家路由为3小时；超期后仍保留迟到可信终态对账。\n"
if "## 内部异步轮询" not in runbook:
    runbook = runbook.replace("\n## 禁止重复提交\n", insert + "\n## 禁止重复提交\n")
runbook_path.write_text(runbook, encoding="utf-8")

knowledge_path = ROOT / "gpts-knowledge" / "GPTS_CONTROL_PLANE.md"
if knowledge_path.exists():
    knowledge = knowledge_path.read_text(encoding="utf-8")
    note = "\n## 内部执行说明\n\n治理派发后立即释放 GitHub Runner；`CONTROL_DISPATCHED` 保持开放并占用唯一全局槽，独立工作流每5分钟异步轮询子中心终态。GPTs 仍只查询原治理 Issue。\n"
    if "## 内部执行说明" not in knowledge:
        knowledge += note
    knowledge_path.write_text(knowledge, encoding="utf-8")

print("true asynchronous governance patch applied")
