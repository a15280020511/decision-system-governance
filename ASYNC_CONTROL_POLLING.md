# True asynchronous control polling

The governance control plane separates dispatch from terminal collection.

1. `Governance Control Plane` validates and dispatches the oldest FIFO task.
2. After `CONTROL_DISPATCHED`, that workflow exits and releases its Runner.
3. The open governance Issue remains the single global-slot lock.
4. Completion of the dispatch workflow starts a separate asynchronous monitor.
5. The monitor performs bounded 30-second polls for at most ten minutes.
6. A five-minute scheduled reconciliation remains the independent fallback.
7. Only a matching `github-actions[bot]` terminal with the route-specific Artifact contract can close the task.
8. Closing the task wakes the next FIFO worker.

This is not a permanent socket or live connection. The user-facing dispatch
request and its Runner finish before monitoring begins. A separate monitor
handles the common short-running case; scheduled polling protects against
monitor interruption, GitHub queue delays and longer child executions.

The event-driven monitor may occupy its own Runner for a bounded period, but it
does not hold the dispatch request open and cannot bypass the single-task lock.
Monitor timeout changes only result-delivery latency. It does not alter the child
center's model call, numerical calculation, random seed, Artifact or expert
output. The five-minute cron interval is a target rather than a strict real-time
SLA because GitHub can delay scheduled runs.

Deadlines are anchored to the child Issue's immutable `created_at` timestamp,
not the governance Issue's mutable `updated_at`. Comments or status refreshes
therefore cannot extend the execution window. Route deadlines are two hours for
intelligence and compute and three hours for expert work; late trusted terminals
remain eligible for the existing closed-Issue reconciliation path.
