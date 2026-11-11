# Response diagnostics without storing generated text

This change helps distinguish a model's stop condition from the application's
actual parsing result. It does not alter the system prompt, retry feedback,
proposal budget, generation-token limit, policy or grader. No held-out scenarios
or live-model results were used to select it.

## What a proposal event records

For an actual HTTP response, `propose_action.detail.response_diagnostics` contains
only these bounded facts:

| Field | Meaning |
| --- | --- |
| `http_status` | Valid HTTP status code, or null when unavailable. |
| `finish_reason` | `stop`, `length`, `tool_calls`, `content_filter`, `function_call`, `missing`, `unknown` or `unavailable`. Arbitrary provider values become `unknown`. |
| `usage_present` | Whether the decoded provider object contains `usage`; null if that object could not be inspected. |
| `usage_known` | Whether `usage.total_tokens` is present and is a valid nonnegative integer. This validates the reported field, not the provider's accounting accuracy. |
| `usage_status` | `reported`, `missing`, `missing_total_tokens`, `invalid` or `unavailable`. |
| `content_utf8_bytes` | Byte length of the returned content string encoded as UTF-8, before removing whitespace or Markdown fences. |
| `content_sha256` | SHA-256 of those exact UTF-8 content bytes. |
| `parse_category` | `valid`, `empty`, `invalid_json`, `schema_validation` or `not_attempted`. |

If the content is not a string or cannot be encoded as valid UTF-8, its byte count
and fingerprint are null. Characters are not silently replaced to manufacture a
hash. HTTP error bodies are not decoded for diagnostics. A failed connection with
no response, a scripted fixture and an injected provider fault have no response
metadata. This avoids presenting synthetic failures as actual model responses.

`length` is a reported stop reason, not a diagnosis. A length-limited response
can contain a valid proposal; it remains successful if it passes the existing
validator. Conversely, a response ending with `stop` can contain invalid JSON.
The parse category comes from the actual parser outcome: empty content after the
existing whitespace/fence handling, Pydantic's `json_invalid` error code, or a
schema-validation failure. Provider/wrapper failures use `not_attempted` rather
than pretending that proposal parsing occurred. Pydantic error messages and
input values are never copied into this diagnostic object.

## Usage uncertainty remains explicit

The provider still returns `tuple[str, int]`. A missing usage object/count keeps
the existing zero reported-token fallback, but metadata now marks it as unknown.
An explicitly reported zero is distinguishable from a missing count; neither is
evidence of free inference. Actual HTTP attempts continue to count separately.

This change does not retroactively establish complete usage coverage for old
exports or backfill token totals for rejected response wrappers. For example, a
wrapper can expose a valid usage field while its content is invalid; the existing
provider-failure path still returns no tuple. Inspect the response status and
usage fields rather than treating an aggregate zero as measured zero cost.
A later reporting change can use these diagnostics to assess coverage across
individual response events. No monetary cost is inferred here.

## Lifecycle and concurrency

`ResponseDiagnostics` is an immutable dataclass. Each `LiveProvider` stores its
latest response separately for each calling thread using an instance-owned
`threading.local`; there is no process-global last-response variable.

Every `propose()` call clears that thread's previous metadata before doing
anything, including before returning an injected malformed response or raising
an injected outage. The engine consumes the metadata exactly once, immediately
after that call returns or fails, and copies its scalar fields into that attempt's
event. Later retries cannot overwrite a previous event's diagnostic snapshot.
A caller using the provider directly can inspect `response_diagnostics` and then
call `consume_response_diagnostics()`; a second consume returns null.

This preserves the existing provider interface used by the ablation runner.
Its tradeoff is that direct callers must consume metadata on the same thread as
the synchronous call. The property is not a run identifier or a general async
SDK. Production requests continue to own their async HTTP clients; injected
AsyncClients remain a mock-transport testing seam. The thread-isolation test
checks metadata ownership, not the thread safety of arbitrary third-party
connection pools.

## Privacy and limits

Diagnostics do not retain raw completion text, response headers, credentials,
arbitrary provider error bodies, unrecognized finish reasons or usage subfields.
The existing structured proposal trace remains unchanged: a successfully parsed
proposal still has its schema-defined fields for reviewing the action. This
feature adds metadata rather than a second copy of the raw completion.

A content hash is an equality fingerprint, not encryption or anonymization. The
metadata cannot reconstruct the malformed response for a reviewer; it can show
that two failures had identical returned content and distinguish their reported
stop condition, usage presence and parser outcome. More detailed inspection
would require an explicitly designed local capture workflow, which is not added
here.

## Validation

Mock-transport tests cover length stops with valid and invalid proposals, empty
and malformed JSON, schema failures, missing/invalid/zero usage, UTF-8 hashes,
invalid Unicode, redaction, immutable snapshots, consumed/reset state, injected
faults, transport errors, retries and simultaneous callers sharing a provider.
Existing parser exception classes, feedback strings, tuple returns and request
settings are preserved. No real-model calls are required for these checks.
