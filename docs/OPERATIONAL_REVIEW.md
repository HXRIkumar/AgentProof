# Operational review of e86c058

Historical review of v0.2. The resulting fixes were implemented and tested in
v0.3; see [hardening notes](HARDENING_NOTES.md) for the current behavior and the
remaining DNS cleanup limitation. Reproductions below describe the old snapshot.

Reviewed on 12 November 2026. This review freezes the evaluated backend at
`e86c058`; the observations below are not fixes applied to that revision. The
application is a local synthetic sandbox, with no real-payment connector. Tests
used an ephemeral loopback HTTP server, HTTPX mock transport and isolated temporary
databases. No hosted model, remote target or real DNS-rebinding attempt was used.

Local reproducer: `artifacts/operational_review_probe.py`; measured output:
`artifacts/operational-review-probe.json`. These scratch files are ignored by Git.
The measured observations are recorded here so the review remains useful without
the scratch files.

## Priority 1: bound provider time and response size

`LiveProvider.propose` uses `Client.post`, which reads the response before JSON
validation. There is no response-byte limit. Setting `max_tokens` asks the model
to limit output; it does not limit an incompatible server's HTTP response.

A mock response containing 2,097,152 content bytes, gzip-compressed into 2,136
wire bytes, was fully accepted by the provider despite `max_tokens=128`. Later
proposal validation can reject an oversized reason, but the body has already
been downloaded, decompressed and parsed. The observed test consumed five
compressed stream chunks. It was a small controlled reproduction, not a memory
exhaustion test. HTTPX documents streaming as the way to avoid buffering an entire
response, and automatic decoding for compressed bodies. [HTTPX responses](https://www.python-httpx.org/quickstart/#streaming-responses)

The configured timeout is also not a total request deadline. A loopback server
sent short chunks less than one second apart; the provider configured with a
one-second timeout completed successfully after **1.62 seconds**. HTTPX read
timeouts bound the wait for the next chunk. They do not bound total elapsed
response time. [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)

Consequently, the three-proposal budget bounds attempts, not total trial duration.
Cancellation waits for the current trial and `ExperimentWorker.stop()` joins its
thread without a deadline. A continuously progressing but very slow provider
can delay both cancellation and shutdown beyond the timeout displayed in the
configuration. This affects local-provider failures too; it is not contingent on
a malicious remote service.

**Minimal next change:** stream the response with explicit wire/decoded size
limits, fail before JSON parsing, and always close the response. A `Content-Length`
check is only an early rejection; count actual bytes when the header is absent or
wrong. For compressed responses, checking the length only after `iter_bytes()`
yields can be too late for a single decompression allocation. The simplest safe
policy for this small JSON protocol is `Accept-Encoding: identity` and explicit
rejection of other encodings. A supported-compression implementation instead
needs a decoder with an output budget per call.

For a true total deadline, a cancellable async HTTP request under an overall
`asyncio.timeout`/AnyIO cancellation scope is a reasonable isolated adapter change.
Keep the entire response-read operation inside that scope, then close the client.
Do not wrap synchronous HTTP in a thread and call a timed `Future.result()`:
returning from that wait does not stop its network thread. A synchronous
monotonic check between chunks is only a checked deadline with possible I/O
overshoot and must be described that way.

**Follow-up implementation finding, separate from e86c058:** the isolated async
adapter cancelled a slow numeric-loopback response, but an independent test that
delayed `socket.getaddrinfo` by 2.5 seconds returned a one-second timeout after
approximately 2.66 seconds. `asyncio.run` waits for resolver-executor cleanup.
The small hardening implementation therefore documents an HTTP I/O cancellation
budget, not a universal wall-clock bound. It keeps cleanup rather than abandoning
a resolver thread. A cancellable DNS design remains further work.

Acceptance: a numeric-loopback slow-drip request is cancelled within the configured
I/O budget plus a documented small scheduling tolerance; a separate hostname
test exposes and documents DNS cleanup delay; an oversized uncompressed
or compressed response fails without buffering the whole output; the next queued
experiment still executes; no orphaned request task/thread remains.

## Priority 1: cap actual server request bytes

The UI import limit is 1,048,576 bytes. The server limits scenario count to 100
and repeats to five, but not request bytes or lengths of scenario strings.
A custom request containing a 1,048,577-byte `untrusted_note` (1,049,086 JSON bytes)
was accepted with `201` and completed. Direct clients therefore bypass the UI
limit. Request parsing happens before queue admission; a full queue does not
prevent this allocation.

Starlette's installed `Request.body()` implementation collects chunks and joins
them before JSON parsing. Repeated runs persist both scenario snapshots and trace
observations, so oversized input can amplify database size as well as prompt size.
The experiment-count bound is useful, but is not a byte, token or disk budget.

**Minimal next change:** add an ASGI receive wrapper that rejects actual request
bytes beyond 1 MiB with `413`, including chunked requests without Content-Length.
Check a valid declared size early, but do not trust it as the sole boundary.
Then add purposeful per-field limits: short identifiers/policy labels, compact
descriptions and a separately documented note budget. Preserve intentionally
invalid domain values such as negative requested amounts in authored rejection
scenarios; schema limits must not erase the policy tests.

Acceptance: below-limit valid requests still work; exact/over-limit, chunked,
incorrect declared length and multibyte text cases are covered; oversize failures
create no experiment or run. Enforce this on the server, not only the UI.

## Priority 2: validate configured URLs precisely

The provider's current check exempts loopback host strings from the HTTPS rule,
but does not explicitly constrain schemes, ports, URL credentials, query strings
or fragments. Constructors accepted these local-only examples:

- `ftp://localhost/v1`
- `http://localhost:bad/v1`
- A loopback URL containing username/password fields.
- Loopback URLs containing a query or fragment.

No network request was made for these malformed configuration probes. Some fail
later in HTTPX; a query/fragment can also change where the appended
`/chat/completions` text is interpreted. Rejecting these at configuration time
would give a more accurate error and avoid recording a non-network configuration
failure as a model-call attempt.

**Minimal next change:** parse once; require `http` or `https`, a hostname and a
valid port; disallow URL credentials, query and fragment; retain HTTP only for
literal loopback/localhost and require HTTPS plus the environment API key for
remote hosts. Reject non-finite timeout values with a clear configuration error
rather than silently clamping them. Keep error text free of the submitted URL
because it could contain credentials. Remote endpoints remain operator supplied;
the scenario API cannot choose a new endpoint.

## Priority 2: local bind is not a Host allowlist

The launcher binds `127.0.0.1`, and Compose exposes only that host address. These
are useful controls against direct remote connections. The FastAPI application
nevertheless accepted `Host: untrusted.example:8010` plus the corresponding
Origin on a scripted POST, returning `201`. This proves arbitrary Host acceptance,
not that a particular browser/DNS-rebinding attack succeeds; browser local-network
restrictions were not tested.

**Minimal next change:** use a strict Host allowlist for the local product:
`127.0.0.1`, `localhost`, IPv6 loopback and the explicit ASGI test hostname. Reject
other hosts before serving UI or API, with no wildcard suffix. Consider an Origin
check for browser mutations as a separate control. CORS alone should not be
presented as authentication or as a complete DNS-rebinding defense. If remote
use is introduced, require deliberate host configuration and authentication
instead of widening the default to `*`.

Acceptance: arbitrary hosts receive `400`; configured loopback hosts, explicit
ports and IPv6 syntax work. Do not claim remote authentication from this change.

## Priority 2: expose readiness separately from liveness

After stopping the worker in an isolated app, `/api/health` still returned
`{"status":"ok","version":"0.2.0"}`, `/api/config` reported
`background_available:false`, and submission returned `503`. The HTTP process was
alive, but it could not accept work. Compose currently uses the liveness route
for its healthcheck.

**Minimal next change:** preserve `/api/health` as liveness and add `/api/ready`
returning `503` when the worker is unavailable or a small database read fails.
Update deployment healthchecks to the readiness route. Avoid returning raw DB
exceptions or filesystem paths. Readiness should not require a paid model call.

## Priority 3: bound work and history growth explicitly

One accepted experiment can schedule 100 scenarios × 5 repeats × 2 strategies =
1,000 trials. With one baseline proposal and up to three guarded proposals, that
can mean up to 2,000 provider attempts before injected faults reduce the count.
The default queue allows eight waiting experiments plus one running. These are
configured finite limits, not a measured acceptable workload for this laptop.

`GET /api/experiments` currently rebuilds each experiment's complete summary by
loading its runs with separate SQLite connections. History and evidence remain
unbounded over repeated sessions. A larger test history could make polling costly;
no load/latency claim was measured in this review.

Minimal follow-up: a selectable total-trial budget at admission, paginated history
with stored summary snapshots, and explicit export/retention controls. Preserve
raw evidence and never delete old experiments automatically without a documented
retention choice. Also review synchronous request waiting when increasing queue
capacity: those `def` handlers occupy the ASGI thread pool while waiting. Prefer
background submissions or an async waiter that does not consume one pool thread
for the whole experiment.

## Suggested implementation order

1. Freeze and finish current model evaluation; do not change its backend midway.
2. In a separate branch, implement provider URL validation, body limits and
   candidly tested total-deadline behavior.
3. Add ASGI byte limits, strict local Host handling and readiness.
4. Run isolated local socket/mocked-provider tests, then existing tests and browser
   checks. Record the source hash of the hardened build separately.
5. Compare the frozen evaluation exports without attributing operational changes
   to model-quality improvements. Repeat model measurements only if an adapter
   change alters generation behavior or measured outcomes.

The current local release remains inspectable and useful. These findings narrow
its operational guarantees; they do not invalidate the already recorded
scenario outcomes or establish production security.
