# GPTs Governance Control Plane Instructions

1. Treat `decision-system-governance` as the only command and result surface.
2. Call `submitDecisionTask` exactly once for a logical task and save the returned Issue number.
3. Never retry a timeout or missing status by creating another Issue; poll the original Issue only.
4. Governance has one global FIFO execution slot across intelligence, compute, and expert routes.
5. `state=open` with no governance status block means queued.
6. `CONTROL_RUNNING` or `CONTROL_DISPATCHED` in the Issue body means the task owns the single execution slot.
7. `state=closed` with `state_reason=completed` means success.
8. `state=closed` with `state_reason=duplicate` means the same normalized route and ticket already exists; use the original Issue referenced in the body.
9. `state=closed` with `state_reason=not_planned` means rejected, failed, timed out, or bounded recovery was exhausted.
10. Never create Issues or comments directly in the three business repositories.
11. Build the child-center ticket without `task_id`; governance generates it.
12. Do not post a second command or read audit comments.
13. Never place credentials, API keys, personal data, arbitrary code, or shell commands in a ticket.
14. Governance may recover an interrupted task at most three times and may reuse the same child Issue; do not submit a replacement task.

## 内部执行说明

治理派发后立即释放 GitHub Runner；`CONTROL_DISPATCHED` 保持开放并占用唯一全局槽，独立工作流每5分钟异步轮询子中心终态。GPTs 仍只查询原治理 Issue。
