# Secondary repeat check

Declared on 12 November 2026 after the first all-hosted and local/critic studies
completed, before this repeat is run. It does not replace the primary comparison.

The first all-mini study favoured validation-only correction over adding a critic.
One additional all-mini run checks whether that observation survives ordinary
hosted-output variation. The primary results remain unchanged regardless of the
repeat's outcome. No prompts, runtime parameters, data or scoring rules are tuned.

- Source: frozen commit `4ffa994f70cab27a3c170ba4621e4ff866534d12`.
- Data: the same 64 evaluation cases, SHA-256
  `4b2d1c8a6b801175a313bd09bb3e4f2525d5428c68e2aa14beb2262707fdcd99`.
- Generator and critic: `gpt-5.4-mini-2026-03-17`, medium reasoning, 1,536 maximum
  completion tokens, temperature omitted, no generation escalation.
- Policies: direct, validation-only and critic-assisted; one shared first response
  per case within the repeat, three maximum generations, cache disabled.
- Retrieval: the same pinned MiniLM snapshot and source passages.
- Output: `mini-hosted-repeat-v1`, kept separately and explicitly labelled as a
  secondary repeat of already observed questions, not new independent cases.
- Spending: the existing shared USD 1.50 application-side guard; no increase,
  reset or new ledger. If blocked, preserve and report partial coverage.

The additional study may overlap local-generator work because it makes no local
language-model calls. Each report's `actual_usage` attributes its API spend; a
shared-ledger before/after difference can include the overlapping study.

Report both runs, their success counts, recovery/regressions, calls and costs.
Compare initial-answer text and correctness across runs, but do not treat 128
repeated questions as 128 unique examples. Two runs are a limited repeatability
check, not a precise estimate of model stochastic variance or general accuracy.
Do not select the better run as the primary result.
