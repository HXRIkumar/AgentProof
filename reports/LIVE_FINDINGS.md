# First live-model evaluation

Executed 12 November 2026 on Apple M4 with 24 GB memory. This checkpoint predates
any changes motivated by its observed failures. The raw result is retained.

## Configuration

- Model: `mlx-community/Qwen3.5-4B-MLX-4bit`.
- Model revision: `32f3e8ecf65426fc3306969496342d504bfa13f3`.
- Local inference: MLX LM 0.32.2, MLX 0.32.4; temperature 0, thinking disabled,
  max 512 output tokens, prompt cache disabled. Warm-up/download excluded.
- 24 authored scenarios, three repetitions, two strategies: 144 runs.
- Baseline: typed schema only. Guarded: policy enforcement, bounded correction,
  approval and transactional idempotency. Same initial model prompt.
- 132 actual local model HTTP attempts, 51,948 provider-reported tokens.
  Eighteen runs made no model request because injected failures prevented one.

The API provider key is named `openai` because it uses that compatible protocol.
The model used here is Qwen, not an OpenAI model. No paid API was called.

## Measured outcomes

| Measure | Baseline | Guarded |
|---|---:|---:|
| Correct task outcomes | 45/72 (62.5%) | 66/72 (91.7%) |
| Passed defined effect invariants | 60/72 | 72/72 |
| Actual model requests | 60 | 72 |
| Reported tokens | 23,514 | 28,434 |
| p50 run latency | 4.248 s | 4.371 s |
| p95 run latency | 5.597 s | 8.384 s |
| Correct pending approval stops | 0 | 3 |

Correct outcomes increased by **29.2 percentage points** on this authored suite.
The gain came with approximately 21% more tokens and 50% higher p95 latency.
These are local descriptive measurements, not service-level guarantees.

The six guarded failures were all refusals of valid tasks: three repetitions of
the misleading amount-note case, and three of the stale-policy case. The model
treated confusing context or policy correction as grounds to refuse. We retain
these failures rather than redefine the labels or report only successful cases.

## Interpretation limits

- These are 24 distinct task types, not 144 independent tasks. Repeated
  temperature-zero outcomes were correlated.
- The suite includes deliberate tool and provider faults. It is a development
  regression suite, not blind held-out data or real customer traffic.
- Passing effect invariants is narrower than full policy correctness. A baseline
  partial refund of an invalid oversized request passed bounded-money checks but
  failed the task's expected rejection. Read both metrics together.
- Pending human approval is a correct stop with zero effects, not a completed refund.
- This compares a composite runtime intervention with a deliberately weaker
  baseline. It does not show improved model weights or isolate each guardrail.
- The CLI reports a dirty reporting working tree because evidence/documentation
  were being written. The loaded backend source fingerprint was fixed at
  `8a995e17a1e487c371d98331dca84d5e94ce2a6b93babae53cdf2ebf30cbc853`.
  No engine or prompt tuning occurred during these trials.

## Evidence

- [Raw experiment, including exact scenarios and traces](qwen35-4b-live-v1.json)
- [Machine-readable analysis](qwen35-4b-live-v1.summary.json)
- [Scripted integration suite](fixture-v1.md)

Raw live JSON SHA-256:
`3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7`.

## Resume wording supported by this run

"Evaluated a policy-gated Qwen3.5-4B workflow across 24 authored refund scenarios
and three repeats, improving correct outcomes from 45/72 to 66/72 while passing
all defined effect-invariant checks in 72 guarded runs."

Keep the baseline, synthetic domain and evaluation scope in the project README.
Do not shorten this to "improved LLM accuracy to 92%" or "100% safe AI."
