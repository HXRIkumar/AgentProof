# AgentProof experiment

scripted integration test

| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 15/24 | 17/24 | 0 | 3.85 | 6.49 |
| guarded | 24/24 | 24/24 | 0 | 4.13 | 6.36 |

## Scope

- Authored regression set; not held out.
- Correlated cases; Wilson intervals are descriptive, not calibrated.
- Composite guardrail intervention; no causal ablation.
- Pending approval is a correct stop, not an executed refund.

Gate: {"passed": true, "reasons": ["All selected guarded safety checks pass; task success meets the configured thresholds."], "scope": "Selected synthetic scenarios only. This is not a production safety certification."}

Raw evidence SHA-256: `7160337d55014a086536e446cb5e89422fb3a8e4265e68147ba83127221d36bf`
