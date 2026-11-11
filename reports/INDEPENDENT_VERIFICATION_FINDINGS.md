# Independently authored verification on a frozen implementation

A separate author received only the JSON schema and written refund policy. It
did not inspect the implementation, prompt, existing suites, model outputs or
reports. It froze 24 synthetic cases with its own schema and policy-label
validator. The implementation had already been committed at
`cf991fbac9bb41e96e73be3c93d7bae63453ca3c` before the suite was authored.
The implementing agent saw only the suite's hash and outcome distribution before
evaluation, and did not inspect its case contents until all 96 trials finished.

| Metric | Baseline | Guarded |
|---|---:|---:|
| Correct outcomes | 20/48 | 48/48 |
| Defined effect invariants | 38/48 | 48/48 |
| Actual model HTTP attempts | 30 | 48 |
| Reported tokens | 12,068 | 20,004 |
| Retries, including tool retries | 2 | 32 |
| Pending approvals, with no executed refund | 0 | 4 |
| Observed p50 trial latency | 8,455.49 ms | 9,145.14 ms |
| Observed p95 trial latency | 9,978.00 ms | 18,780.68 ms |

Each strategy ran two repetitions per case. The 24 cases comprise eight expected
refunds, nine rejections, five escalations and two pending approvals. All cases
and repetitions are retained; none were removed because of results. The guarded
workflow had no incorrect outcomes on this set. Its greater model-call and token
use remains visible rather than being described as a cost-free improvement.

## Reproduce and inspect

- [Frozen suite, provenance and independent validator](../examples/independent-verification-v1/PROVENANCE.md).
- [Raw experiment](independent-verification-v1.json), SHA-256
  `6ce7c8c54e49279fdc1cd6c9cff003a54955282323e85208d96c4ab7f093e797`.
- [Machine-readable summary](independent-verification-v1.summary.json).
- Suite file SHA-256:
  `d8b7352d83565b427bac0931869e056220e6ef0cd24c2633989634e18ef30819`.
- Executed backend source fingerprint:
  `7c4e4df8592047ffc2eaffd41b225e1dc6233cce1e503c33ff6a66e6531c5dba`.
- Experiment ID: `6e0db99350654e47927d34c4f6461c74`.

The tested local model was `mlx-community/Qwen3.5-4B-MLX-4bit`, recorded revision
`32f3e8ecf65426fc3306969496342d504bfa13f3`, temperature zero, thinking disabled,
maximum 512 generated tokens, timeout 120 seconds and prompt cache disabled.
Inference ran on an Apple M4 with 24 GiB RAM, mlx-lm 0.32.2 and mlx 0.32.4.
Other development activity on the Mac limits timing interpretation. No hosted
or paid model calls were used.

To validate the copied suite without running a model:

```sh
python3 examples/independent-verification-v1/validate.py
(cd examples/independent-verification-v1 && shasum -a 256 -c SHA256SUMS)
```

## What this result does and does not establish

This is independently authored verification within a supplied synthetic domain,
not a public benchmark, randomized holdout, adversarial red-team certification
or evidence of broad generalization. Its author knew the same schema and policy
the implementation was designed to support. Two temperature-zero repetitions
are correlated observations, not 48 independent tasks per strategy.

The baseline deliberately lacks the guarded workflow's policy, approval and
idempotency controls. The comparison measures that combined intervention; it
does not isolate retry benefits or establish that the model itself improved.
Some tool/provider failures are deliberately injected and visible in traces;
an injected failure is not counted as an actual model HTTP attempt. A pending
approval is a correct stop, not an executed monetary effect.

The generic exporter labels all synthetic reports as authored regression data.
The specific authoring and freeze protocol above records this suite's stronger
separation from implementation work. Neither hashes nor recorded model revisions
are trusted cryptographic attestations. This suite is now public and must not be
reused as an unseen test set for future changes. No workflow was tuned on these
observed outcomes. Read this beside the [harder development challenge](CHALLENGE_FINDINGS.md),
where six guarded trials still failed.
