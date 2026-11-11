# Frozen challenge: recovery improved, failures retained

On 12 November 2026, the same local Qwen3.5-4B model ran the same 30 authored
challenge cases twice under each strategy. Each version therefore produced
120 trials: 60 baseline and 60 guarded. These are 30 distinct cases, not 120
independent tasks. The suite was frozen before the recovery change and before
live evaluation. Its author knew the original implementation and failures;
this is a development challenge set, not a blind public benchmark.

## Observed change

| Guarded workflow | v0.1 reference | v0.2 candidate |
|---|---:|---:|
| Correct task outcomes | 32/60 (53.3%) | 54/60 (90.0%) |
| Defined effect-invariant passes | 60/60 | 60/60 |
| Actual model HTTP attempts | 78 | 100 |
| Reported tokens | 36,708 | 47,658 |
| Correct pending-approval stops | 2 | 8 |
| Recorded p50 trial latency | 6,795.78 ms | 10,016.83 ms |
| Recorded p95 trial latency | 37,520.78 ms | 51,925.78 ms |

Eleven distinct cases improved in both repeats; no guarded case lost a correct
outcome or an effect-invariant pass. The strict release comparison passed at its
pre-existing 90% completion threshold. The unchanged baseline produced 18/60
correct outcomes, 46/60 invariant passes, 50 model calls and 22,232 tokens in
both versions.

The candidate gained 22 correct guarded outcomes while using 10,950 additional
reported tokens (29.8%) and 22 additional model attempts (28.2%). Eight correct
approval stops mean eight zero-effect pauses for human review, not eight paid
refunds. Passing all defined effect checks is not a universal safety guarantee.

## What changed

The initial model prompt and three-proposal budget stayed the same. For an
eligible request rejected or escalated by the model, the guarded validator now
supplies authoritative facts and requests a corrected proposal within that
budget. It also refreshes the structured observed policy version when the
retrieved version is stale. It never manufactures a refund from a refusal.
Every monetary proposal still passes identity, eligibility, exact-amount,
current-policy and approval checks.

These results describe that combined workflow change. The separate one-versus-
three-proposal ablation is needed to study additional retry opportunity; this
before/after experiment does not isolate every component's causal effect.

## Remaining failures

Three cases failed in both candidate repeats, all ending in escalation with no
monetary effect:

- `challenge-note-token-refund`
- `challenge-policy-partial-balance`
- `challenge-remaining-at-approval-boundary`

Each used all three proposal attempts. Their traces are retained. These are real
task failures; a safe stop is not counted as a successful eligible refund.
The reports do not retain complete invalid model responses, so they do not by
themselves establish whether every parse failure came from truncation, formatting
or another generation issue. Do not invent a diagnosis from the aggregate score.

## Method and limits

- Model: `mlx-community/Qwen3.5-4B-MLX-4bit`, cached revision
  `32f3e8ecf65426fc3306969496342d504bfa13f3` verified against the local model ref.
- MLX-LM 0.32.2 / MLX 0.32.4; Apple M4, 24 GB memory, macOS 26.5.1.
- Temperature 0, thinking disabled, maximum 512 output tokens, 120-second HTTP
  inactivity timeout in these measured v0.1/v0.2 builds, prompt cache disabled.
- Version runs were sequential. Baseline/guarded ordering alternated within
  each version. There were no concurrent model evaluations from this project.
- The host also ran development checks and other services. Docker Desktop
  startup restarted existing unrelated containers during the overall session.
  Latency is descriptive, not an isolated hardware comparison or proof that the
  recovery logic alone caused the timing difference. No speedup is claimed.
- Both suites include injected outages and malformed responses that sometimes
  make zero network requests. Count model attempts separately from trials.
- Repeated temperature-zero outcomes are correlated. No statistical-significance
  or unseen-task-generalization claim is made.

## Evidence and reproducibility

- [Reference raw export](challenge-v1-before.json),
  [candidate raw export](challenge-v1-after.json),
  [strict comparison](challenge-v1-comparison.json).
- Reference raw SHA-256:
  `4350df2a927427b391c077722705107d5680cd1f4997092439363fd5a7e09ea8`
- Candidate raw SHA-256:
  `df2f8062a6202444bbfbea908bbaff7a7bf6d5c04e892d6507e5e4610771223f`
- Frozen challenge file SHA-256:
  `77bfa60553343acdff60c1320b5a27650234799152a7d18561a6d88b9d707475`
- Reference server source fingerprint:
  `8a995e17a1e487c371d98331dca84d5e94ce2a6b93babae53cdf2ebf30cbc853`
- Candidate server source fingerprint:
  `160874be9243d56bfacf04fd43fc36d7b67a5c620c2ee28e6e2b9f4927d0d9c3`

The reference API ran from the detached `v0.1.0` worktree; the candidate API ran
from the frozen `e86c058` implementation. Summary `source_revision` identifies
the reporting client's checkout at export time, which can differ from the API
server. Use the raw export's server fingerprint for the executed source snapshot.
Fingerprints and model revision labels support inspection, not cryptographic
attestation of remote execution.

```sh
uv run python scripts/compare.py reports/challenge-v1-before.json \
  reports/challenge-v1-after.json --output artifacts/challenge-comparison
```

Later hardening builds have different backend fingerprints. These results remain
evidence for the measured versions; subsequent code must be verified separately.
