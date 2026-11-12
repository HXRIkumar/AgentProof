# Correlating saved runs with OTLP traces

Each instrumented `Engine.run()` now has one `agentproof.run` span. Its observe,
propose, validate, execute and grade spans are direct children in the same trace.
Retries produce additional child spans rather than unrelated traces. The run
span covers initial persistence, graph execution and the final save. Input
validation and provider construction happen before it starts.
Its duration includes those journal bookends; the run's existing `latency_ms`
measurement keeps its original timing scope.

This is observability instrumentation. It does not change prompts, model
decisions, proposal budgets, retries, approval checks, ledger identity or grading.
The stage event journal and exported OTLP spans remain separate representations.

## Enable and correlate

Set `OTEL_EXPORTER_OTLP_ENDPOINT` before starting the process or its first run.
For example, a collector accepting OTLP HTTP on localhost can be configured with:

```sh
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

The exporter posts protobuf traces to `/v1/traces`. AgentProof owns its SDK
provider and batch processor; it does not replace another application's global
provider or silently use that application's exporter. Initialization is guarded
against concurrent first calls. Configuration is cached for the process lifetime;
restart after changing it. Call `agentproof.telemetry.flush_telemetry()` for an
explicit best-effort flush in a command-line integration. Normal SDK shutdown also
flushes pending spans. Delivery still depends on collector availability and process
shutdown; this is not a durable telemetry queue.

A persisted run has a `trace_context` field containing a 32-character hexadecimal
`trace_id`, a 16-character hexadecimal run-level `span_id`, and a boolean `sampled`.
These identify the run span, not its final stage. The identifiers are attached
before the initial journal save and retained in subsequent snapshots and API/JSON
exports. No database schema migration is needed.

The span describes the evaluation when `Engine.run()` finished. A later human
approval can change the saved run without reopening its completed span; approval
actions are not instrumented by this change. Replay creates a new run and span.
Its existing `parent_run_id` is a journal relationship, not an OTLP parent link.

Without an endpoint, `trace_context` is null and AgentProof creates no recording
spans. It neither borrows IDs from an unrelated SDK nor replaces its ambient
context: independently instrumented calls inside the workflow retain that parent.
With tracing enabled, an existing ambient parent is retained: the run is its child,
and all workflow stages are children of the run. Concurrent invocations keep
their own run spans. Runs without an ambient parent receive separate traces.

Sampling may produce valid IDs with `sampled: false`, without exporting spans.
A saved identifier, even with `sampled: true`, is not proof that a collector
received the span. Crashes may leave an initial run snapshot and no completed
exported run span. Older saved runs may have no correlation field.

## Controlled attributes and failures

The existing stage attributes remain the generated run ID and the fixed strategy
name. The run span additionally records the provider enum, proposal budget,
controlled status/outcome values, execution/grading completion flags, proposal
and model-attempt counts, retries and reported tokens. Integer counters are
bounded to the nonnegative signed 64-bit range in telemetry; persisted run
evidence remains the source of truth and is not modified by that bound.

Correctness (`passed`) and defined effect checks (`safe`) are exported only after
a successful final save, with grading checks present and a finished evaluation
status. Unexpected failures export `evaluation_completed: false`,
`grading_completed: false`, `status: failed` and `outcome: interrupted`. They omit
`passed` and `safe`; the run object's initial `safe: true` is not verified safety.
The original exception still propagates and existing persistence/recovery behavior
is unchanged. Initial-save failures cannot provide a stored correlation record.

An operationally completed evaluation has span status `OK`, including a correctly
rejected request or a failed task grade; inspect its controlled outcome and grade
attributes. Unexpected exceptions set span status `ERROR`. Automatic exception
events, messages and stack traces are disabled for AgentProof spans. Only the
exception class name, limited to 64 characters, is added as `error.type`.

AgentProof adds no raw prompts, retrieved notes, model outputs, customer/order
identifiers, credentials, arbitrary provider error text or exception messages to
its spans. Existing structured proposal evidence remains in the local journal.
Embedding applications and collector/exporter configuration have their own
telemetry policies; this instrumentation does not sanitize independently created
third-party spans or operator-supplied resource attributes.

Reported token counts retain their existing uncertainty: zero does not establish
free inference, and aggregate totals do not establish complete response accounting.
The run trace is a correlation aid, not an alternative release gate or usage audit.

## Verification

The tests launch subprocesses using the actual SDK and HTTP exporter, receive
OTLP protobuf payloads in a localhost collector and decode their IDs, parents,
attributes and status. They compare collector identifiers with SQLite run
snapshots, overlap concurrent first runs, exercise external SDK/parent coexistence
and disabled mode, retain retry and approval accounting, and check exception
redaction. Independent collector tests also check unsampled valid IDs without
exports, overlapping calls on one Engine instance, `KeyboardInterrupt` and
`SystemExit`, and a final persistence failure after a graded snapshot. These
failure paths omit unverified correctness/safety attributes. Synthetic providers
are used throughout; no model calls are made.
