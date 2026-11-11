# Engineering decisions and failure boundaries

## A model proposes; the application owns authority

The live provider receives an observation assembled from a synthetic order,
authenticated actor, requested amount, retrieved policy version and untrusted
note. It does not receive the evaluator's expected outcome. Baseline and guarded
runs use the same initial prompt.

The typed proposal contains an action, order, actor, amount, policy version and
reason. Pydantic rejects unsupported fields, actions and non-integer money.
The guarded validator compares the proposal with authoritative application state.
Valid syntax alone cannot authorize a refund. Scenario money and age fields also
reject coercion from booleans, strings and fractional values.

This is a constrained action workflow, not a general-purpose autonomous planner.
Its useful boundary is the separation between a probabilistic proposal and the
application's authority to execute a tool.

## Bounded correction without automatic approval

An eligible request can fail because a model treats an untrusted note as policy
or continues using an outdated policy version. The guarded runtime checks the
structured order's owner, delivery status, age and remaining balance first. An
ineligible request is rejected before any corrective feedback.

For an eligible request, a reject/escalate proposal receives factual feedback and
another opportunity to propose the exact requested refund. A stale observed
policy is refreshed from the authoritative version, with a `refresh_policy`
trace event. Neither path consults the evaluator's expected outcome. They do not
turn a refusal directly into a refund: the next proposal must still pass every
validation check, and amounts above 10,000 cents still require human approval.

The existing budget is three total proposals, including the original attempt.
Exhausting it escalates without a monetary effect. This mechanism is application
policy feedback, not an independent LLM critic or proof of improved model
reasoning. Its false refusals, remaining failures, token use and latency must be
measured alongside any recovered outcomes.

## Why a receipt matters more than a confident sentence

In the timeout-after-commit scenario, the tool writes a refund before its
acknowledgement is discarded. The runtime retries delivery. The baseline uses a
new delivery identity; the guarded path uses the same logical operation key.
SQLite's unique constraint and transaction return the existing effect on a retry.
A key reused with a different amount, order or policy is rejected.

The grader reads the ledger. It checks authorization, eligibility, grounded order
identity, bounded total amount, effect count, human approval and policy version.
It separately checks the expected task disposition. A safe escalation is not a
completed eligible refund.

A pending approval is correct only when it contains an actionable refund proposal
for the authenticated owner's eligible order, exact requested high-value amount,
available balance and current policy, with `awaiting_approval` status and no
effect. An `approval_required` label by itself cannot earn task success. These
pending-proposal checks affect task correctness; the defined effect-invariant
rate still concerns effects that actually occurred.

## One durable queue for synchronous and background requests

Both submission modes use the same SQLite queue and one worker:

- `POST /api/experiments?background=true` returns `202` with the persisted
  experiment, allowing the UI to poll progress while trials run.
- `POST /api/experiments` waits for the same queue and returns `201` with the
  final experiment, preserving the synchronous client contract.
- `GET /api/experiments/{id}` exposes completed trials and recomputes the summary.
  An active or partial experiment cannot pass the release gate.

Queue admission and job claiming use `BEGIN IMMEDIATE`. The default waiting
capacity is eight jobs, configurable through `AGENTPROOF_MAX_QUEUED` within
1–100; it excludes the currently running job. A full queue returns `429` without
creating an experiment. Normal ASGI lifespan startup is required. Submission
returns `503` when the worker is unavailable.

A POSIX file lock beside the resolved database path grants one API worker
ownership of that database. A second process using the same path or a symlink
alias fails startup rather than silently becoming another executor. This is a
single-host Mac/Linux design; it is not a distributed queue or Windows support.
An execution lock also keeps replay requests from overlapping an active
experiment: such requests return `409`. Other applications sharing the model
endpoint can still affect latency and are outside this lock's scope.

## Cancellation and restart have explicit outcomes

`POST /api/experiments/{id}/cancel` is idempotent. A waiting job becomes
`cancelled` immediately. A running job records `cancel_requested` and stops after
the current trial finishes. The completed trial, including any simulated effect,
is retained. Cancellation does not abort an in-flight provider request or undo
an already committed effect. Cancelling a completed, failed or cancelled job
leaves its terminal result unchanged.

A graceful shutdown waits for the current trial. If further trials
remain, the running experiment fails with partial evidence retained; waiting jobs
remain queued. After an abrupt process exit, the next lease-owning worker marks
interrupted running experiments failed and drains the untouched queue. It also
recognizes pre-queue v0.1 experiments left in `running` state.

Queued work therefore survives restart, but interrupted LangGraph nodes and
partially completed experiments are never automatically resumed or replayed.
Replay deliberately gives a stored scenario a new isolated run identity. A
cancelled, failed or incomplete experiment cannot pass either release gate.

Unexpected execution errors fail that job with a redacted error class so the
worker can continue to the next job. A queue-read failure makes the worker
unavailable and releases its lease; its log contains the error class, not private
exception text. Recovery then requires resolving the runtime issue and restarting
the server.

## Freeze configuration before execution

Submission stores the scenario inputs, their hash, prompt hash, backend source
fingerprint and effective provider settings. These settings include the model,
operator-provided revision, timeout, output-token bound and thinking option. The
endpoint is represented by a SHA-256 digest; credentials are never exported.

The worker checks the snapshot before execution and checks effective provider
settings between trials. A changed model/configuration, prompt or backend source
fails the queued job rather than mixing evidence under its original label.
Settings changed mid-experiment preserve already completed trials and prevent
further ones. The selected provider instance is held for that experiment.

These fingerprints describe what was configured. They do not attest that a
remote endpoint actually served particular weights, and backend source is
snapshotted when the API application is created. Do not edit or replace runtime
code during a measurement session.

Provider-reported `total_tokens` must be a nonnegative integer. Booleans, negative
or fractional counts and malformed usage objects fail as redacted provider
errors. An omitted usage object/count is recorded as zero, meaning no reported
usage, not demonstrated zero-token inference. No monetary cost is inferred.

## Durability stops at the simulated tool boundary

`Store` persists run snapshots and scenario inputs separately from ledger effects.
An approval transaction records its decision, optional effect and updated run
together under `BEGIN IMMEDIATE`. Repeating the same decision returns the stored
result; attempting to reverse it returns a conflict.

For an actual payment integration, the remote service must support stable keys,
receipt lookup, reconciliation and authorization. A local database transaction
cannot make two independent services atomic. The current tool only changes a
synthetic local ledger. The API has no operator authentication or tenant
isolation and should remain local.

## Two gates answer different release questions

The experiment gate requires completed, full paired coverage, every guarded
effect invariant passing, at least 90% guarded task success, and no aggregate
task regression against that experiment's baseline. It is a fixed example policy,
not a threshold calibrated to an organization's risk tolerance.

`scripts/compare.py` evaluates a candidate against a prior export. It validates
coverage and embedded scenario hashes, regrades final states, requires matching
suite and model/evaluation controls, and rejects any guarded per-case decrease
in correctness or effect-invariant passes. This catches a regression hidden by
an improved aggregate score. It also enforces the candidate success threshold
and comparison with its own baseline. Prompt and source changes are disclosed
rather than forbidden: those are often the implementation being evaluated.

See [the evaluation protocol](EVALUATION_PROTOCOL.md) for invocation, exit codes
and limits. Export validation detects inconsistent evidence; it does not make
editable JSON tamper-proof. Latency and token ceilings are not automatically
gated and must be reviewed separately.

## Further work that requires new evidence

1. Add a second domain and externally authored, disjoint held-out cases without
   tuning on them.
2. Run retries-only and validation-only ablations to isolate intervention effects.
3. Measure several models/seeds and test abrupt crashes at more execution stages.
4. Add authenticated operator decisions and tenant-isolated storage before remote use.
5. Integrate a real sandbox API using its own transaction receipts and reconciliation.

A more elaborate stack is not evidence of these capabilities. Each needs its own
implementation, failure tests and reproducible results.
