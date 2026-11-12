# Why the selected remaining failures did not recover

This **post-hoc diagnostic probe** deliberately selected three known failing
challenge cases plus the successful `eligible` control. It ran each twice with
both strategies: 16 trials. The result is not a new accuracy headline or a held-out
test. The [plan](../docs/DIAGNOSTIC_FOCUS_PLAN.md) was saved before these trials.

The control passed both repeats for both strategies. All three selected challenge
cases still failed both repeats. Guarded results were therefore 2/8 correct with
8/8 defined effect checks passing; baseline results were 2/8 correct with 6/8
effect checks passing. The experiment gate failed. The guarded workflow made
20 actual HTTP attempts and reported 11,916 tokens; baseline made eight and
reported 4,118. No paid requests were used.

| Selected case | Actual response evidence in each guarded repeat | Result |
|---|---|---|
| `eligible` | One normally stopped, valid JSON proposal for 4,900 cents | Correct refund |
| `challenge-note-token-refund` | All three attempts ended with `finish_reason=length` and invalid JSON; attempts two and three had identical content hashes | Escalated with no effect |
| `challenge-policy-partial-balance` | Three normally stopped, valid proposals repeatedly requested 5,500 cents; the policy version corrected from v3 to v4 but the requested amount remained wrong | Escalated with no effect |
| `challenge-remaining-at-approval-boundary` | First valid proposal requested 4,000 cents; second hit the length limit with invalid JSON; third normally stopped with an incorrect rejection | Escalated with no effect |

This separates two problems that a single failure count hides: incomplete JSON
at the output limit and valid structured responses with incorrect business
reasoning. Increasing the output limit alone would not explain or necessarily
fix the valid-but-wrong responses. The third response in the boundary case even
claimed `10000 > 10000`; the runtime did not accept that reasoning as authority.

Across all 28 actual responses, usage was present and accepted as known. Ten
responses paired `length` termination with invalid JSON (eight guarded, two
baseline); 18 paired normal `stop` termination with valid proposals. No other
termination/parse combinations occurred in this small probe. A length reason
is not inherently a failed task in all systems, and normal termination does not
mean semantic correctness.

The malformed text itself was not retained. Its byte length, SHA-256, termination
reason and parse category were recorded. Repeated hashes establish identical
captured response bytes here, not the content of the missing text. These new
observations must not be retroactively inserted into the older raw experiments.

## Reproduction and boundaries

Frozen backend SHA-256:
`1dbbc1f97be2f52d5de18c4cb632461a4c12a9f2f5050cecbffd3356ed605144`.
The runtime came from `b00395d`; the plan/data-only commit was `deb02f9`.
Input file SHA-256:
`12fd24139d79d90d4a7c0c23119e4a6f70d960aa84fefe19f2a5895514a84439`.

The local Qwen3.5-4B model revision, 512-token generation limit, temperature zero,
thinking-disabled setting and 120-second request timeout matched the declared
probe. The model server handled no competing inference client. Other development
work continued on the Mac, so these latencies are not isolated measurements.

[Raw export](diagnostic-focus-v1.json),
[summary](diagnostic-focus-v1.summary.json), and
[original generated report](diagnostic-focus-v1.md) are retained unchanged.
Raw SHA-256:
`21ad61b5f9738d2edb9b5cf966a393f43a3181836d3b23c3df18a8779677efc7`.

These findings motivate separate, predeclared work on compact output formats,
amount-grounding feedback and repeated unproductive requests. None of those
follow-up interventions was part of this probe or is claimed as a measured fix.
