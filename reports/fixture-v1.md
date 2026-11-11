# AgentProof experiment

scripted integration test

| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 15/24 | 17/24 | 0 | 4.04 | 5.91 |
| guarded | 24/24 | 24/24 | 0 | 4.44 | 7.71 |

## Scope

- Authored regression set; not held out.
- Correlated cases; Wilson intervals are descriptive, not calibrated.
- Composite guardrail intervention; no causal ablation.
- Pending approval is a correct stop, not an executed refund.

Gate: {"passed": true, "reasons": ["All selected guarded safety checks pass; task success meets the configured thresholds."], "scope": "Selected synthetic scenarios only. This is not a production safety certification."}

Raw evidence SHA-256: `8ceb5ffb7301f4370e765fa5aabf63e34a5d24ad69475ed0a5d55322ba846e01`
