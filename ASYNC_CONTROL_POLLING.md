# True asynchronous control polling

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
