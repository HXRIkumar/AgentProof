# A refund commits, but the response disappears

This integration lab crosses an actual HTTP and process boundary. A separate
localhost service owns its own SQLite order and effect ledger. The client can
lose a connection after a committed write, reconcile the operation, and retry
without changing its identity. No LLM, external account, real customer data or
payment provider is involved.

The main evaluation engine remains unchanged. Its original enum-based fault
fixtures are still useful deterministic tests; this separate lab checks a
different boundary that those fixtures do not exercise.

## Run and inspect

From the repository root, with Python 3.12+ and the existing dependencies:

```sh
uv sync --frozen
uv run python scripts/remote_lab.py --output-dir artifacts/remote-tool-lab
uv run pytest -q tests/test_remote_tools.py
```

Choose a new output directory for each run. The command refuses an existing
directory rather than replacing evidence. It starts and terminates only its own
child processes, uses automatically allocated loopback ports, and leaves each
service database and log available for inspection.

The output contains `evidence.json`, `report.md`, `SHA256SUMS` and the separate
scenario directories. JSON includes client request events, service PIDs, source
file hashes and independent database snapshots. A zero exit status means all six
declared checks passed. It does not mean every control was safe: one intentionally
demonstrates why creating a new key after a timeout is unsafe.

## The six checks

| Check | What actually happens | Required independent evidence |
|---|---|---|
| Lost response | Service commits, then closes the socket without HTTP headers; client GETs the operation | Transport exception, reconciled receipt, exactly one 3100-cent effect |
| Restart before retry | First response is lost; service is stopped and restarted against the same database | Different service PIDs; same receipt, balance and one effect after retry |
| Concurrent same key | Eight client requests use one key | Eight matching receipts; one effect |
| Changed arguments | Existing key is reused with a different amount | HTTP conflict; unchanged database |
| Unavailable reconciliation | A write commits, its response is lost, and operation lookup returns 503 | Client returns unresolved with no receipt; independent ledger still shows one effect |
| New-key control | A deliberately naive caller replaces the key after a lost response | Two distinct operations and two effects totaling 6200 cents |

The client’s success message is never the sole evidence. The runner opens the
server database in SQLite read-only mode and checks effects, balances and
operation identities. In the unresolved case, this external inspection knows
more than the client: the client must not claim a failed refund or automatically
start a replacement operation.

## The protocol

The service binds only to `127.0.0.1`. The client accepts only an explicit numeric
loopback HTTP address and disables inherited HTTP proxies. Each logical request
has one caller-supplied `Idempotency-Key`, restricted to 64 ASCII letters,
numbers, underscores or hyphens. The client never generates a replacement key.

```text
POST /refunds
Idempotency-Key: checkout-refund-001
Content-Type: application/json

{"order_id":"ORD-100","customer_id":"CUS-17",
 "amount_cents":3100,"policy_version":"refund-v1"}

GET /operations/checkout-refund-001
```

The server uses `BEGIN IMMEDIATE` to serialize each decision. In one transaction
it binds the key to a canonical request hash, records the receipt and effect, and
updates the remaining balance. A matching replay returns the original receipt;
changed arguments return `409 idempotency_conflict`. Distinct keys represent
distinct operations, even when their fields happen to match.

The database owns the seeded order facts. A client cannot replace the order’s
owner, delivery status, age or balance by adding fields to the request. The
service rejects wrong ownership, missing or ineligible orders, stale policy and
excessive amounts. Values over 10000 cents return `approval_required` with zero
effects. This lab intentionally has no approval-execution endpoint.

`customer_id` is a synthetic identity assertion, not authenticated identity. A
real integration would obtain the customer identity from an authenticated
session, not accept it as proof from a JSON body.

## Failure handling

The client makes at most three POST attempts (two by default), each with the
same key and arguments. After an ambiguous transport, server or response-format
failure, it attempts GET reconciliation before retrying. A matching committed
receipt resolves the ambiguity. Receipts are strictly typed before comparing
their fields: floating-point and boolean money values are malformed, even when
Python equality would consider them equal to an integer. Malformed receipts
leave the effect unknown; a well-typed mismatched receipt is a conflict. If all
attempts are exhausted without authoritative evidence, the result is
`unresolved`, with the original key retained for a later operator decision.

A `404 operation_not_found` lookup is only a point-in-time observation. A
previous request might still be executing. The client therefore does not infer
safe rejection from a missing receipt. HTTP timeouts are per-operation I/O
timeouts and the attempt count is bounded; this is not a claim about an absolute
wall-clock deadline under every possible server behavior.

The service rejects extra JSON fields, non-integer money, oversized bodies,
chunked requests, invalid keys and unexpected Host headers. Requests are capped
at 8 KiB and client responses at 16 KiB. These limits make the local fixture
predictable; they do not turn the Python standard-library HTTP server into an
internet-facing service.

## Files and verification

- `src/agentproof/remote_service.py`: standalone HTTP process, authoritative
  synthetic orders, transactional idempotency and test-only transport faults.
- `src/agentproof/remote_client.py`: bounded same-key retry and reconciliation;
  explicit committed, reconciled, rejected, conflict and unresolved results.
- `scripts/remote_lab.py`: starts actual service processes, retains their
  databases, and writes JSON/Markdown evidence from independent inspection.
- `tests/test_remote_tools.py`: process/socket tests, strict input rejection,
  policy checks, concurrent balance protection, unavailable service handling
  and database integrity checks. No model endpoint is contacted.
- `tests/test_remote_tools_review.py`: independent tests for malformed receipt
  types, interrupted startup cleanup, concurrent conflicting arguments, hard-kill
  recovery and bounded oversized-response handling.

Source hashes identify the files used by a run, not a trusted attestation. Keep
the evidence and source snapshot together when comparing changes. This lab’s
results must not be added to the model benchmark’s success rate or sample count.

## What this demonstrates and what remains outside scope

The demonstration establishes deduplication across the tested process and
database restart boundary on one machine. It does not establish exactly-once
delivery for arbitrary remote systems. The remote service must implement its own
deduplication contract; a client-side cache or workflow checkpoint cannot create
that guarantee on its behalf.

For comparison, Stripe’s documented idempotency contract describes retaining
operation results and rejecting changed parameters under an existing key.
AgentProof does not call Stripe or claim compatibility with its payment API.
[Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests)

There is no production authentication, TLS deployment, multi-tenant isolation,
high-value approval execution, webhook recovery, key expiration, distributed
database or automatic mid-graph resumption. Keys remain indefinitely in this
small fixture. Process restart is tested; power-loss durability and filesystem
corruption are not. These limits keep the result specific and reproducible.
