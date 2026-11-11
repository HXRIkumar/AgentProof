# Engineering decisions and failure boundaries

## A model proposes; the application owns authority

The live provider receives an observation assembled from a synthetic order,
authenticated actor, requested amount, retrieved policy version and untrusted
note. It does not receive the evaluator's expected outcome. The same initial
prompt is used for baseline and guarded runs.

The typed proposal contains an action, order, actor, amount, policy version and
reason. Pydantic rejects unsupported fields, actions and non-integer money.
The guarded validator then compares the proposal with authoritative application
state. Valid syntax alone cannot authorize a refund.

This is intentionally a constrained action workflow. It demonstrates where to
put authority when integrating a probabilistic component; it does not claim a
general-purpose autonomous planning system.

## Why a receipt matters more than a confident sentence

For the timeout-after-commit scenario, the tool writes a refund before its
acknowledgement is discarded. The runtime retries delivery. The baseline uses a
new delivery identity; the guarded path uses the same logical operation key.
SQLite's unique constraint and transaction return the existing effect on a retry.
A key reused with a different amount, order or policy is rejected.

The grader reads the ledger. It checks authorization, eligibility, grounded order
identity, bounded total amount, effect count, human approval and policy version.
It also checks the expected task disposition. A safe escalation is not silently
treated as a completed eligible refund.

## Durability is a boundary, not a label

`Store` persists run snapshots and scenario inputs separately from ledger effects.
An approval transaction records its decision, optional effect and updated run
together under `BEGIN IMMEDIATE`. Repeating the same decision returns the stored
result; attempting to reverse it returns a conflict.

An interrupted experiment remains incomplete or failed and cannot pass a release
gate. Automatic recovery of an in-flight LangGraph node is not implemented.
Replay deliberately gives a stored scenario a new isolated run identity.

For an actual payment integration, the remote service must support stable keys,
receipt lookup, reconciliation and authorization. A local database transaction
cannot make two independent services atomic. That is a future distributed-systems
problem, not a feature claimed here.

## Why the gate is strict about evidence

The gate requires a completed experiment and every planned scenario/repetition
pair. It then requires every guarded safety check to pass, at least 90% task
completion and no aggregate task regression against baseline. This is a fixed
example release policy. It is not calibrated to an organization's risk tolerance.

A correct pending approval counts as the expected stop in an approval scenario;
it does not mean money was already refunded. Inspect its zero-effect ledger.
Custom scenario outcomes are authored labels and must be reviewed by the suite's
owner. Typed validation prevents typos; it cannot determine whether an author's
business requirement is sensible.

## What would justify a version 0.2

1. A second domain and externally authored held-out cases, without tuning on them.
2. Retries-only and validation-only ablations to separate intervention effects.
3. An asynchronous worker with cancellation, leases and tested restart recovery.
4. Authenticated operator decisions and tenant-isolated storage before remote use.
5. Integration with a real sandbox API using its own transaction receipts.

These are deliberately listed as future work. The current release makes a smaller
set of verifiable claims and gives reviewers the raw evidence to challenge them.
