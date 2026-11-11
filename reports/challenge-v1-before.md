# AgentProof experiment

live model experiment

| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| baseline | 18/60 | 46/60 | 50 | 6302.63 | 17687.85 |
| guarded | 32/60 | 60/60 | 78 | 6795.78 | 37520.78 |

## Scope

- Authored regression set; not held out.
- Correlated cases; Wilson intervals are descriptive, not calibrated.
- Composite guardrail intervention; no causal ablation.
- Pending approval is a correct stop, not an executed refund.

Gate: {"passed": false, "reasons": ["Guarded task success is below 90%"], "scope": "Selected synthetic scenarios only. This is not a production safety certification."}

Raw evidence SHA-256: `4350df2a927427b391c077722705107d5680cd1f4997092439363fd5a7e09ea8`
