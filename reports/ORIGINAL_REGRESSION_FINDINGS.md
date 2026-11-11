# Original-suite regression after bounded recovery changes

Both frozen runs used 24 authored scenarios, three repetitions and two strategies
with the same local Qwen3.5-4B configuration. The v0.2 guarded workflow corrected
all six previously failing original-suite trials. This is a development regression
result on known cases, not general model accuracy.

| Guarded metric | v0.1 | v0.2 |
|---|---:|---:|
| Correct outcomes | 66/72 | 72/72 |
| Defined effect invariants | 72/72 | 72/72 |
| Actual model HTTP attempts | 72 | 78 |
| Reported tokens | 28,434 | 31,371 |
| Retries (including tool retries) | 24 | 30 |
| Pending, unexecuted approvals | 3 | 3 |
| Observed p95 trial latency | 8,384.322 ms | 18,101.792 ms |

The affected cases were `amount-injection` and `stale-policy`, three repetitions
each. No guarded case lost correct outcomes or invariant checks. The strict
release comparison passes. The unchanged baseline remained 45/72 correct and
60/72 defined effect invariants, with exactly the same 60 HTTP attempts and
23,514 reported tokens in both versions.

The guarded change added 2,937 reported tokens (10.3%) and six HTTP attempts
(8.3%). Latency must not be attributed entirely to the code change: the Mac also
ran development, tests and unrelated services, and the baseline's p95 increased
from 5,596.743 ms to 9,555.528 ms despite identical outcomes and token counts.
These timing measurements are descriptive, not a controlled speed comparison.

## Evidence

- [Reference raw export](qwen35-4b-live-v1.json), SHA-256
  `3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7`.
- [Candidate raw export](qwen35-4b-live-v02.json), SHA-256
  `2bc665369b0e943663485a3255cb4ddd5c503ff3997b77559c64d0604a985bad`.
- [Strict comparison](original-v1-v02-comparison.md) and
  [machine-readable comparison](original-v1-v02-comparison.json).
- Reference executed source fingerprint:
  `8a995e17a1e487c371d98331dca84d5e94ce2a6b93babae53cdf2ebf30cbc853`.
- Candidate executed source fingerprint:
  `160874be9243d56bfacf04fd43fc36d7b67a5c620c2ee28e6e2b9f4927d0d9c3`.

The reporting client's Git revision is not the API's executed source identity;
use the raw export's `server_metadata.backend_source_sha256` for the latter.
Model revision was recorded as `32f3e8ecf65426fc3306969496342d504bfa13f3`,
temperature zero, thinking disabled, maximum 512 generated tokens, timeout 120
seconds, MLX prompt cache disabled. Repeated temperature-zero trials are correlated.

Read this result alongside the [harder challenge study](CHALLENGE_FINDINGS.md):
the candidate achieved 54/60 there and still failed six trials. A valid pending
approval counts as a correct zero-effect stop, not a completed refund. All orders
and effects are synthetic; no production reliability or customer adoption is implied.
