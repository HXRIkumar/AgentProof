# AgentProof experiment

live model experiment

| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 45/72 | 60/72 | 60 | 4248.15 | 5596.74 |
| guarded | 66/72 | 72/72 | 72 | 4371.36 | 8384.32 |

## Scope

- Authored regression set; not held out.
- Correlated cases; Wilson intervals are descriptive, not calibrated.
- Composite guardrail intervention; no causal ablation.
- Pending approval is a correct stop, not an executed refund.

Gate: {"passed": true, "reasons": ["All selected guarded safety checks pass; task success meets the configured thresholds."], "scope": "Selected synthetic scenarios only. This is not a production safety certification."}

Raw evidence SHA-256: `3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7`
