# P1 Operational Resilience

Version: 2026-08-05

## Scope

This release adds operational recovery around the already validated P0 control plane. It does not add another Agent, database, business execution path or broader token permission.

## GitHub API resilience

All direct control-plane commands use `resilient_control.py`, which injects `resilient_http.py` into the deterministic control runtime.

Retries are permitted only for:

- HTTP 429;
- HTTP 403 when `X-RateLimit-Remaining=0` or `Retry-After` is present;
- HTTP 502, 503 and 504;
- temporary URL/network errors.

Normal authorization and validation 4xx responses fail immediately. The default maximum is four attempts and every delay is capped at 120 seconds.

Retry audit JSONL may contain method, path, status, attempt, delay, reason and rate-limit headers. It must not contain Token values, authorization headers or response bodies.

## Queue wake degradation

After a task is handled, the worker tries to wake the next FIFO worker at delays:

```text
0 seconds
5 seconds
15 seconds
```

If all three attempts fail:

- the handled task result remains unchanged;
- the current governance Issue receives `CONTROL_QUEUE_WAKE_DEGRADED`;
- no child task or model call is created;
- open `[control]` Issues remain the queue of record;
- the 15-minute scheduled worker remains the automatic fallback.

Wake failure is not converted into business task failure.

## Daily health check

The daily health workflow performs zero business calls and zero model calls. It validates:

- governance and three child repository identities;
- owner and default branch;
- repository is not archived or disabled;
- governance Issue read access using `GITHUB_TOKEN`;
- child Issue read access using `CONTROL_PLANE_TOKEN`;
- child Contents and Actions Secrets remain forbidden;
- the child token cannot access the governance repository.

The health report records no secret values. A single `[health] Governance Control Plane` Issue is created or reopened only when health fails. A later passing run comments recovery and closes the same Issue.

## User status vocabulary

`control-plane/status-dictionary.json` is the machine-readable source for status meaning and next action.

Required interpretation:

- `CREATED` is not accepted;
- `CONTROL_DISPATCHED` is not completed;
- `CHILD_ACCEPTED` is not completed;
- `CONTROL_TIMEOUT` and `CONTROL_MONITOR_ERROR` do not prove the child stopped;
- `CONTROL_COMPLETED` requires Task ID and success evidence contract;
- reconciled late status supersedes the earlier unconfirmed timeout/monitor state;
- queue wake degradation changes queue recovery state, not the completed business result.

## Evidence retention

`ISSUE_AND_ARTIFACT_RETENTION_POLICY.md` defines the current bounded retention policy. No indefinite archive is claimed. A durable archive requires a separate reviewed storage design and must preserve the original Artifact identity and digest.

## Operational limits

- GitHub platform-wide outages cannot be bypassed safely.
- The minimum-permission control token cannot cancel a running child workflow.
- A repository OpenAPI change does not automatically update the custom GPT configuration.
- Daily health checks reduce detection time but do not replace the exact token scope probe after key creation or rotation.

## Acceptance

P1 qualification requires:

1. deterministic tests for rate-limit, network recovery and non-retryable 4xx;
2. no Token or response body in retry audit;
3. exactly one bounded wake loop with an explicit degradation receipt;
4. one health Issue identity;
5. health check positive and negative scope tests;
6. unchanged GPT Action operation count and repository boundary;
7. exact release manifest;
8. a zero-call production health run after merge.
