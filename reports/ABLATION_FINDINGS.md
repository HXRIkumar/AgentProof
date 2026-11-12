# Extra proposal opportunities help, at a substantial token cost

The completed 216-trial local study compared one proposal (A1) with up to three
proposals (A3) in the **same guarded workflow**. Both arms retained policy checks,
approval stops, read recovery, transactional deduplication and final-state grading.
The model, initial prompt, generation limits and source were fixed for both arms.

**Correctness benefit was supported; the combined study rule did not pass.** A3
gained correct outcomes without losing any per-case correct outcome or violating
the defined effect checks. However, its challenge token total rose by 100.2%,
exceeding the predeclared 50% additional-token threshold. This is a measured
tradeoff, not an unconditional improvement or a release-comparison gate.

| Suite and arm | Correct | Effect checks | Actual HTTP attempts | Reported tokens | p95 trial latency |
|---|---:|---:|---:|---:|---:|
| Original A1 | 40/48 | 48/48 | 42 | 16,472 | 11.01 s |
| Original A3 | 48/48 | 48/48 | 52 | 20,914 | 20.74 s |
| Challenge A1 | 30/60 | 60/60 | 54 | 23,802 | 41.31 s |
| Challenge A3 | 54/60 | 60/60 | 100 | 47,658 | 67.31 s |

The original suite has 24 cases and the challenge suite 30, each repeated twice
per arm. Keep these suites separate: they are related authored tasks, not 216
independent benchmark problems. Some trials include injected faults. For example,
two of the eight original-suite gains come from recovering the deliberately
injected first malformed proposal. All such trials remain in the saved report.

The original suite gained eight correct outcomes for 4,442 additional reported
tokens and ten additional HTTP attempts: 555.25 tokens and 1.25 attempts per
additional correct outcome. The challenge gained 24 for 23,856 tokens and 46
attempts: 994 tokens and about 1.92 attempts per additional correct outcome.
These are aggregate descriptive ratios, not the cost of a guaranteed recovery.

A3 retained six failed challenge trials: both repeats of
`challenge-note-token-refund`, `challenge-policy-partial-balance` and
`challenge-remaining-at-approval-boundary`. They escalated with no effect after
their proposal budget. Successful high-value cases remained pending approval;
they were not converted into completed refunds for the study.

## What the contrast isolates

A1 and A3 use the same factual correction and observation-refresh mechanism.
A1 can generate feedback but cannot send it to a second proposal. Thus the
contrast measures extra proposal opportunities **with the existing correction
path**, including their additional compute. It does not isolate feedback wording,
prove an equal-compute improvement or change the model's weights. The proposed
four-arm feedback/context mechanism experiment has not been run.

The no-regression and efficiency rules were written before the trial results.
The recorded p95 ratios stayed below the separate 2× threshold, but other work
was running on the development Mac. Timing is descriptive, not an isolated
causal performance measurement or a production latency claim.

## Provenance and reproduction

- Frozen runner revision: `ad22f89396c0195950886ea9131428ca242cbb12`.
- Executed source fingerprint: `369155c542a00482353ebd6b7576f7fad55c43e6d5efbb523efb17188385fe49`.
- Raw SHA-256: `123036ba01def221e2bddecb7e6a0c4e43db955a181588673227494961b5563c`.
- Model: `mlx-community/Qwen3.5-4B-MLX-4bit`, cached revision
  `32f3e8ecf65426fc3306969496342d504bfa13f3`.
- Apple M4, 24 GiB unified memory; MLX-LM 0.32.2 and MLX 0.32.4.
- Temperature 0, thinking disabled, 512 generated-token limit, 120-second request
  timeout, prompt cache disabled; one inference client at a time.
- Seed 20261112, balanced saved schedule; source/configuration checked between
  trials and again at completion. The working tree was clean when execution began.
- One common warm-up: one HTTP attempt and 398 reported tokens, excluded from all
  trial totals. Recorded study duration was 2,920.131 seconds, including warm-up.
- 248 trial HTTP attempts, plus that one warm-up; no paid provider requests.

[Raw evidence](ablation-local-20261112/raw.json),
[original frozen-runner analysis](ablation-local-20261112/summary.json),
[readable per-case report](ablation-local-20261112/report.md), and
[checksums](ablation-local-20261112/SHA256SUMS) are preserved. The original three
files were copied byte-for-byte after completion.

The separate [v0.4 reanalysis](ablation-local-20261112/analysis-v04.json) applies
the newer usage-coverage labelling. It reaches the same decision and marks this
older evidence `legacy_aggregate_only`: the frozen runner did not collect
per-response diagnostic metadata. Positive token totals cannot prove that every
response was accounted for. No missing telemetry was backfilled and no monetary
cost is estimated. Hashes establish consistency, not signed authenticity.

To reproduce the original runner, use a separate checkout of the revision above
and the recorded model settings, then run:

```sh
uv run python scripts/ablate.py run --provider openai --seed 20261112 \
  --output-dir artifacts/my-new-ablation
```

The command accepts only a free local inference endpoint and a new output
directory. Its successful exit means the study completed validly, not that A3
passed every adoption threshold. Preserve unsuccessful results too. See the
[predeclared protocol](../docs/ABLATION_PLAN.md) and
[runner/accounting notes](../docs/ABLATION_USAGE.md).
