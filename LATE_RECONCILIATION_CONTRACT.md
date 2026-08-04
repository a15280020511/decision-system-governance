# Late Terminal Reconciliation Contract

Version: 2026-08-05

Late reconciliation is a corrective evidence operation, not a second business execution path.

## Eligible governance record

A record is eligible only when all conditions hold:

1. the GitHub Issue is closed;
2. the title is exactly `[control]`;
3. the Issue author is `a15280020511`;
4. the governance status is `CONTROL_FAILED`;
5. the child status is `CONTROL_TIMEOUT` or `CONTROL_MONITOR_ERROR`;
6. the route is one of `compute`, `intelligence`, `expert`;
7. the Task ID equals `gov-<governance_issue_number>-<route>`;
8. the child repository equals the repository fixed by the route;
9. the child Issue number is explicit in the governance receipt.

Any failed condition makes the record ineligible. The reconciler must not comment on or modify it.

## Eligible child terminal

The child result must:

- be authored by `github-actions[bot]`;
- use a terminal heading allowed for the route;
- contain the exact expected Task ID;
- satisfy the route Artifact contract when it is a success terminal.

A terminal with a missing or mismatched Task ID is provisional evidence. An incomplete success terminal is also provisional evidence. Neither may be used to reconcile a governance result.

## Terminal precedence

A valid Artifact-backed success is an absorbing terminal for its Task ID.

- The newest valid success is selected when one or more valid successes exist.
- A later duplicate-admission, already-running, replay or idempotency rejection cannot revoke that success.
- A success without a complete Artifact contract is not absorbing and remains provisional.
- When no valid success exists, the latest trusted task-bound failure is selected.

This rule prevents a child Issue reopen or duplicate workflow run from converting an already completed task into a governance failure.

## State transition

A valid late success becomes `CONTROL_RECONCILED_LATE_SUCCESS` with `state_reason=completed`.
A valid late failure becomes `CONTROL_RECONCILED_LATE_FAILURE` with `state_reason=not_planned`.

The reconciled receipt preserves the original monitor status, Task ID, route, child Issue and trusted child terminal excerpt.

## Execution and permission boundary

- the reconciler uses the same global concurrency group as the normal control worker;
- it does not dispatch a new business task;
- it does not call a model, external data source or compute operation;
- `GITHUB_TOKEN` is limited to governance Issue writes;
- `CONTROL_PLANE_TOKEN` remains limited to child Issue reads/writes;
- no Contents, branch, PR, Workflow, Actions Secret or administration permission is added.

## Triggers

- scheduled scans remain the authoritative fallback;
- a user-generated Issue close event may start an immediate scan;
- Issue changes made by `GITHUB_TOKEN` are not assumed to recursively trigger another workflow.

## Fail-closed rule

When identity, authorship, route mapping, Task ID or Artifact evidence is ambiguous, the existing timeout/monitor-error record remains unchanged. Reconciliation is never inferred from Issue body text alone.
