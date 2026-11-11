# Runtime hardening after the frozen v0.2 evaluation

These changes were developed separately from the frozen `e86c058` backend used
for the v0.2 live-model experiment. They change operational limits and add a
comparison API; they do not change the model's system prompt, JSON generation
settings or refund-policy rules. Do not attach the old backend fingerprint to
results produced by this build.

## Provider request lifecycle

The existing synchronous engine calls an async HTTP request through
`asyncio.run` in its dedicated worker thread. A production request owns its
`httpx.AsyncClient` and closes it on success or failure. `asyncio.timeout`
cancels HTTP I/O across connection, upload, response headers and body instead of
resetting the budget whenever another chunk arrives. HTTPX phase timeouts remain
set as well.

**This is not a universal wall-clock bound on `propose()`.** Hostname resolution
can use asyncio's resolver executor, and `asyncio.run` waits for its cleanup.
An independent local test delayed `socket.getaddrinfo` by 2.5 seconds: a one-second
configuration returned its timeout only after approximately 2.66 seconds. The
resolver had finished before return; no attempt was made to abandon its thread.
Numeric loopback avoids that resolver path and the real slow-drip socket test
exercises cancellation there. DNS cleanup, synchronous setup and process
scheduling can extend elapsed time. Supporting a cancellable DNS resolver would
require a further networking design change.

`AGENTPROOF_TIMEOUT_SECONDS` retains its 1–120 second effective range and now
defines the HTTP I/O cancellation budget as well as phase timeouts. Each proposal
has that budget; a guarded trial can make up to three proposals. Cancellation
still waits for its current trial, including any resolver cleanup, and no rollback
is implied. Do not advertise a fixed worst-case shutdown duration.

Responses are read in 16 KiB chunks with a 1,048,576-byte ceiling before JSON
parsing. An excessive declared Content-Length fails immediately; actual bytes
are counted even without that header. Requests explicitly ask for identity
encoding. Any compressed Content-Encoding is rejected before reading or
decompressing its body. This deliberately supports small JSON completions, not
arbitrary compressed output. A provider that ignores `Accept-Encoding: identity`
will fail clearly rather than receive an unbounded decompression allowance.

Redirects are disabled explicitly. Loopback clients ignore inherited proxy
variables so a local request is not accidentally sent through a proxy. Remote
HTTPS endpoints may still use configured environment proxies. URLs must use HTTP
or HTTPS, have a hostname and valid port, and contain no embedded credentials,
query or fragment. HTTP remains restricted to exact supported loopback hostnames;
remote HTTPS requires the separate environment API key. Invalid settings produce
redacted configuration errors. Timeouts must be finite and positive; token limits
must be positive integers.

The injected AsyncClient constructor argument is a test seam used with
MockTransport. Production uses the owned-client path. A caller integrating a
custom persistent async connection pool would need a persistent event-loop
lifecycle rather than reusing network connections across separate `asyncio.run`
invocations.

## Local HTTP boundary and readiness

An ASGI middleware caps actual request-body bytes at 1 MiB before JSON parsing.
It checks Content-Length early and counts received chunks, including requests
without a declared length. Oversize input returns `413` and creates no experiment.
This is a total request limit; the UI's file limit does not include the additional
JSON wrapper, so a file exactly at that UI ceiling may require reducing its size.
There are no additional per-field note/description caps yet.

Host validation accepts only `localhost`, `127.0.0.1`, bracketed IPv6 loopback
and the explicit ASGI test hostname `testserver`, with optional ports. Arbitrary
Host values fail with `400` before API execution. The test hostname is present
for local ASGI testing; this is still a local-only product, not an authentication
or tenant-isolation scheme. Origin-based authorization and remote deployment
remain separate future work.

`/api/health` remains process liveness. `/api/ready` returns `200` only when the
experiment worker is available and a short read-only database check succeeds;
otherwise it returns `503` with boolean availability flags. It does not call a
model, expose database errors or recreate a deleted database. Compose now uses
readiness for its healthcheck.

## Comparison API

`POST /api/comparisons` accepts exactly:

```json
{"reference_id": "existing-experiment-id", "candidate_id": "existing-experiment-id"}
```

It reads the two existing experiments and invokes the same strict comparison as
`scripts/compare.py`. Missing records return `404`; incompatible or incomplete
evidence returns `422`. A compatible comparison returns `200` with a passing or
failing comparison gate. That gate can fail even when the candidate's own
experiment gate passes, because a case-specific regression cannot be offset by
improvement elsewhere. The response also includes `reference_snapshot`,
`candidate_snapshot` and a UTC `captured_at` timestamp. These are the exact
detached experiment documents used for grading; the UI displays them rather than
fetching new evidence that a later approval could have changed. The timestamp
records completion of snapshot collection, not an atomic cross-experiment
database transaction. Comparison makes no provider calls and does not mutate
runs or experiments. The standalone comparison CLI's output format is unchanged.

## Verification performed for the backend changes

- The integrated Python suite passed with **283 tests**, including 52 new
  operational/comparison API cases and three independent hardening review tests.
- A real numeric-loopback slow-drip server continually made progress inside the
  inactivity interval, yet the one-second I/O cancellation budget stopped the
  request and closed its socket. The test allows scheduling tolerance and verifies
  disconnection; it does not establish the same wall-clock bound for DNS.
- The next queued experiment completed after a timed-out mocked request, with
  the failed attempt counted and the worker remaining ready.
- Tests cover streamed oversize output, compression rejection before any body
  read, exact/over-limit request bytes, chunked and multibyte bodies, malformed
  URLs/configuration, IPv6 Host syntax, missing-worker/database readiness, and
  comparison success/refusal without mutations.
- Ruff passed for the backend and tests. No hosted model or paid API was used for
  this operational validation.

Final integrated local verification: **284 Python tests passed**, Ruff clean,
four web import-test groups and the production build passed. The comparison
browser workflow verified passing results, incompatible/partial refusals,
aggregate improvement with a case regression, mobile layout, and a real approval
after comparison capture. The last case preserves the exact zero-effect snapshot
in the inspector/export while the current stored run has the approved effect.
Remote CI and release commit are recorded separately when completed.
