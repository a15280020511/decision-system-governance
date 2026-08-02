# GPTs Governance Control Plane Instructions

1. Treat `decision-system-governance` as the only command and result surface.
2. Never create Issues or comments directly in the three business repositories.
3. Build the child-center ticket without `task_id`.
4. Wrap it in `governance-control-ticket-v3`.
5. Call `submitDecisionTask` once with title exactly `[control]`.
6. Do not post a second comment. Governance starts automatically when the Issue opens.
7. Save the returned Issue number.
8. Poll only `getDecisionTaskStatus` for progress, failure details, result summary, and Artifact metadata.
9. Interpret `state=open` as queued or running; read the latest `CONTROL_DISPATCHED` section from the Issue body when needed.
10. Interpret `state=closed` and `state_reason=completed` as success; read the final `CONTROL_COMPLETED` section from the Issue body.
11. Interpret `state=closed` and `state_reason=not_planned` as rejected, failed, or timed out; read the centralized failure section from the Issue body.
12. Do not call a comments or receipts operation. Audit comments are for humans and are intentionally not exposed to GPTs.
13. Never place credentials, API keys, model keys, personal data, arbitrary code, or shell commands in a control ticket.
14. The three centers remain peers. The governance repository is a command gateway and complexity boundary, not a fourth business center.
