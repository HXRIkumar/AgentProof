# Post-hoc response diagnostic probe

Plan recorded before running this probe. This is selected from known development
failures, not independent verification or a new general benchmark.

The earlier challenge evaluation failed the three cases listed below in both
guarded repeats. Its exports did not retain finish reasons or parse categories.
Observe those facts in a separately frozen, metadata-only implementation without
changing prompts, policy, feedback, generation limits, labels or budgets.

- `eligible`: unchanged original-suite successful control.
- `challenge-note-token-refund`
- `challenge-policy-partial-balance`
- `challenge-remaining-at-approval-boundary`

Input file SHA-256: `12fd24139d79d90d4a7c0c23119e4a6f70d960aa84fefe19f2a5895514a84439`.

Use two repeats and both existing strategies:16 trials, not16 independent tasks.
Retain every result, including success, failure and disagreement with earlier
observations. No human approvals are executed. Keep old reports unchanged.

Implementation source is the response-diagnostics branch at `b00395d`, with
backend SHA-256 `1dbbc1f97be2f52d5de18c4cb632461a4c12a9f2f5050cecbffd3356ed605144`.
This plan/data commit adds no runtime edits. The same local Qwen3.5-4B revision,
temperature0, thinkingfalse, max512, timeout120 and cache0 are retained. Wait until
the ongoing216-trial budget study has completed; never share its inference slot.

Report actual finish_reason, parse_category, usage availability, content hashes,
proposal attempts and final effects. A length stop does not by itself prove a
truncation-related task failure; a valid proposal may also end at the limit.
Likewise invalidJSON can occur with stop. No raw malformed completion is stored,
so the metadata cannot reveal its exact text. If the old failures do not recur,
report that rather than guessing a cause.

Do not adjust token budgets or tune prompts from this probe in place. A proposed
fix must start a separately named study with new controls, preserving this result.
