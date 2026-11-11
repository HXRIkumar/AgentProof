# AgentProof experiment

live model experiment

| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 20/48 | 38/48 | 30 | 8455.49 | 9978.0 |
| guarded | 48/48 | 48/48 | 48 | 9145.14 | 18780.68 |

## Scope

- Authored regression set; not held out.
- Correlated cases; Wilson intervals are descriptive, not calibrated.
- Composite guardrail intervention; no causal ablation.
- Pending approval is a correct stop, not an executed refund.

Gate: {"passed": true, "reasons": ["All selected guarded safety checks pass; task success meets the configured thresholds."], "scope": "Selected synthetic scenarios only. This is not a production safety certification."}

Raw evidence SHA-256: `6ce7c8c54e49279fdc1cd6c9cff003a54955282323e85208d96c4ab7f093e797`
