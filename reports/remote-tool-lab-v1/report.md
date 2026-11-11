# Local remote-tool integration evidence

Synthetic HTTP service; zero model calls.

| Case | Verified condition | Server effects |
|---|---|---|
| commit_then_socket_close | PASS | 1 |
| service_restart_before_same_key_retry | PASS | 1 |
| eight_concurrent_same_key_requests | PASS | 1 |
| same_key_changed_arguments | PASS | 1 |
| commit_hidden_by_unavailable_reconciliation | PASS | 1 |
| new_key_after_ambiguity_duplicates_logical_request | PASS | 2 |

Each server runs in a separate process. Effects are independently read from its
SQLite database, not inferred from client responses. The new-key control deliberately
creates two effects; PASS means this unsafe behavior was observed as expected.

The unresolved case has one committed effect that the client cannot verify.
It therefore returns unresolved rather than claiming success or safe rejection.

Raw evidence SHA-256: `3c94f34b70d57e8bd55bc1d90fc64bb2afde182a37ffa552b7e02cdfdf83a788`

## Limits

- Local synthetic service, no real payments or customer adoption.
- Customer identity is an assertion; no production authentication.
- Independent service process and database; same physical host.
- Idempotency keys are retained indefinitely in this fixture.
- No high-value approval execution or automatic in-flight graph recovery.
- Unresolved is not rejection: an unobserved effect may already exist.
