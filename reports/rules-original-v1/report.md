# Rules-only policy reference

rules-only policy control; not model inference or a release gate

Applicable: 22/24 distinct cases. Repeats: 3 per case, with identical labels and inputs.

| Method | Correct | Effect invariants | Model HTTP calls | Reported tokens | p95 ms |
|---|---:|---:|---:|---:|---:|
| live_guarded | 66/66 | 66/66 | 75 | 30138 | 18101.792 |
| rules_guarded | 66/66 | 66/66 | 0 | 0 | 54.943 |

## Declared exclusions

- malformed: Injected malformed model output is inapplicable to a typed rules function.
- model-outage: Injected model unavailability is inapplicable to a rules function.

## Every applicable case

| Case | Live correct | Rules correct | Trials each |
|---|---:|---:|---:|
| amount-injection | 3 | 3 | 3 |
| approval | 3 | 3 | 3 |
| cancelled | 3 | 3 | 3 |
| commit-timeout | 3 | 3 | 3 |
| day-30 | 3 | 3 | 3 |
| day-31 | 3 | 3 | 3 |
| duplicate | 3 | 3 | 3 |
| eligible | 3 | 3 | 3 |
| injection | 3 | 3 | 3 |
| over-balance | 3 | 3 | 3 |
| partial | 3 | 3 | 3 |
| processing | 3 | 3 | 3 |
| read-outage | 3 | 3 | 3 |
| read-timeout | 3 | 3 | 3 |
| remaining | 3 | 3 | 3 |
| spent-balance | 3 | 3 | 3 |
| stale-policy | 3 | 3 | 3 |
| threshold | 3 | 3 | 3 |
| unknown-order | 3 | 3 | 3 |
| wrong-order | 3 | 3 | 3 |
| wrong-owner | 3 | 3 | 3 |
| zero | 3 | 3 | 3 |

## Interpretation

- This structured refund policy can be decided without an LLM.
- Rules and earlier live trials are different runs with separately recorded source hashes.
- Latency is descriptive across nonconcurrent runs, not a controlled speedup experiment.
- Model-specific fault exclusions are declared per case; no expected label was changed.
- Both use the guarded runtime, including synthetic tool faults and approval boundaries.
- The rules provider ignores notes; it cannot interpret unstructured requests.
- Repeated deterministic cases are correlated; no general model-quality claim is made.

Raw SHA-256: `faf4c140bcdf15743ba9eab647a25bb361ee8d2128cd7c39919962c0ed8d5158`
