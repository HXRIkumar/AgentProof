# A second model family on the frozen workflow

The Mac completed a second free local-model study using Phi-4-mini-instruct,
community 4-bit conversion, without changing the workflow or prompt in response
to its outputs. Both predeclared suites completed. This checks adapter and
workflow portability on existing synthetic cases; it is not a model leaderboard
or a blind benchmark. [Plan](../docs/MODEL_PORTABILITY_PLAN.md).

| Suite / strategy | Correct outcomes | Defined effect checks | HTTP attempts | Reported tokens | Pending approval |
|---|---:|---:|---:|---:|---:|
| Original / baseline | 14/48 | 38/48 | 40 | 13308 | 0 |
| Original / guarded | 46/48 | 48/48 | 64 | 22150 | 2 |
| Challenge / baseline | 16/60 | 34/60 | 50 | 17554 | 0 |
| Challenge / guarded | 60/60 | 60/60 | 72 | 26062 | 8 |

The original suite contains 24 cases repeated twice per strategy; the challenge
contains 30 cases repeated twice. Repeats are correlated. Both ordinary experiment
gates pass the configured 90% guarded-correctness threshold and all defined effect
checks. A passing gate does not mean that every original task succeeded.
Pending approvals are correct stops with no refund yet executed.

## Retain the failure and the extra work

Both guarded original failures are `threshold`: a valid request for exactly
10,000 cents. Each run proposed 8,000 cents, then 5,000 cents twice. The gate
refused those incorrect amounts and escalated after three proposals. The last
two captured content hashes match. No effect was written, but the valid request
was not completed. These failures remain in the raw export.

Every actual Phi response ended with `stop`, and all 226 trial responses had
present, accepted usage. Normal termination did not imply a usable proposal:
50 responses failed schema validation (38 original, 12 challenge); 176 parsed
successfully. Schema failures are retained as failed attempts, not silently
repaired. Raw invalid completion text was not retained, so a schema category
alone does not establish which field was wrong.

Guarded execution used more requests and tokens than the one-proposal baseline:
64 versus 40 requests on the original suite and 72 versus 50 on the challenge.
The two strategies deliberately have different recovery opportunities. This is
a composite workflow comparison, not an equal-compute model-quality test.

## Reproduction and provenance

- Model: `mlx-community/Phi-4-mini-instruct-4bit`, revision
  `ac1c269cb4222a4e136a3d09edad301056c1f36a`.
- Local Apple M4 / 24 GiB, MLX-LM 0.32.2 / MLX 0.32.4, Python 3.12.13.
  No paid or hosted inference requests were made.
- Temperature 0, 512-token output limit, 120-second timeout, prompt cache zero.
  No Qwen-specific thinking override was sent.
- The MLX server loaded a relative local symlink to the exact cached snapshot
  with Hugging Face/Transformers offline flags. The matching relative model name
  was used in requests. Model identity is operator-recorded, not independently
  attested by the provider.
- Runtime from `c015617`; pre-study plan commit `c133ade`. Executed backend
  SHA-256: `669224b930a1aebcd80e2f711c405ef303be157cf14bbec3d33ee7d3b92458fb`.
  No source, prompt or label tuning occurred between or during these suites.
- One common warm-up was excluded: one HTTP attempt, 328 reported tokens,
  normal termination with schema validation failure. Its metadata is retained
  in [the warm-up record](phi4-mini-warmup-v1.json).
- Original experiment `a5e10eea32bc4236a8e34cefab0a6eb6`; challenge experiment
  `e31eb2da09704429a675494b4bb4c125`. All results were exported before approval
  decisions or replay. The reporting checkout's dirty flag is retained: the
  exporter had written untracked reports. Backend identity is checked separately.

[Original raw JSON](phi4-mini-original-v1.json),
[original summary](phi4-mini-original-v1.summary.json),
[challenge raw JSON](phi4-mini-challenge-v1.json),
[challenge summary](phi4-mini-challenge-v1.summary.json), and
[exact file hashes](phi4-mini-SHA256SUMS).

A separate [read-only consistency audit](phi4-mini-independent-check.json)
recomputed all 216 trial records and reconciled 226 trial HTTP attempts plus the
excluded warm-up against the local server log. It found no discrepancies in
ledger grades, counts, hashes or usage totals. This is an audit of saved evidence,
not independent attestation of model identity or generalization.

Original raw SHA-256:
`c5ca8558567aba63c2fad3502025de8d45a4ba2b65afc1b796e75e7ee650f642`.
Challenge raw SHA-256:
`86d311ecf849fec1b1037b44c4f24f25757984a7c5f984374890773cb18394e0`.

The study does not establish that Phi is generally better than Qwen. The model,
template/runtime snapshot and generation settings differ from earlier studies;
no strict cross-model release comparison was run. Development activity on the
Mac also prevents isolated performance claims. The rules-only control remains
the simpler answer for this fully structured policy. The public evidence viewer
currently contains the five earlier Qwen archives; these additional Phi reports
are downloadable from the repository rather than presented as those archives.
