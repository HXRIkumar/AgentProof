# Published evidence audit

Audited on 12 November 2026 against repository revision `88a3b16`. No numerical,
raw-hash, denominator, exclusion, or historical source-fingerprint discrepancy
was found in the studies below. Existing evidence was not changed. This audit
made no model calls and inspected no ongoing ablation study outcomes.

## Recomputed results

Each B/G pair means baseline/guarded. Calls are the recorded HTTP-attempt counts;
tokens are provider-reported usage, not independently metered inference work.

| Live study | Cases × repeats per strategy | Correct B/G | Effect invariants B/G | Calls B/G | Tokens B/G |
|---|---:|---:|---:|---:|---:|
| Original v1 | 24 × 3 | 45/72; 66/72 | 60/72; 72/72 | 60; 72 | 23514; 28434 |
| Original v02 | 24 × 3 | 45/72; 72/72 | 60/72; 72/72 | 60; 78 | 23514; 31371 |
| Challenge before | 30 × 2 | 18/60; 32/60 | 46/60; 60/60 | 50; 78 | 22232; 36708 |
| Challenge after | 30 × 2 | 18/60; 54/60 | 46/60; 60/60 | 50; 100 | 22232; 47658 |
| Independent verification | 24 × 2 | 20/48; 48/48 | 38/48; 48/48 | 30; 48 | 12068; 20004 |

The 624 live run records have complete scenario/strategy/repeat coverage, unique
run IDs within each export, and no substituted replay or later approval decision.
Audit-side standard-library logic recomputed task dispositions and effect checks
from embedded scenarios and final states without calling the project grader.
Recorded grades, ledger totals, scenario/configuration hashes, provider/prompt
identity, summary counts, retries, pending approvals, and nearest-rank p50/p95
latencies agree. This checks consistency; it is not an external execution attestation.

Both release comparisons match their input hashes and case-level deltas. Original
guarded results improve on two cases, challenge results on eleven; neither has a
case regression. Guarded reported tokens increase by 10.329% and 29.830%,
respectively, matching the rounded findings. The six remaining challenge failures
are retained. The v1 claim of 18 zero-HTTP-attempt runs also matches the raw data.

The rules controls retain the exact earlier live export, scenario labels and
repeat count. Only `malformed` and `model_outage` are excluded: original IDs
`malformed`, `model-outage`; challenge IDs `challenge-malformed-unauthorized`,
`challenge-model-outage-expired`. Original comparison is 66/66 model and 66/66
rules; challenge is 50/56 model and 56/56 rules. All 122 rules runs have zero
recorded model calls and tokens, null prompt hashes, and passing effect checks.
Applicable model totals are 75 calls/30138 tokens and 100 calls/47658 tokens.

The two scripted fixture exports separately contain 48 runs each, with 15/24
baseline and 24/24 guarded correct outcomes, and zero model calls/tokens. They
are not included in live-model denominators.

The remote lab contains six declared socket/process checks and zero model calls.
Independent ledger snapshots have effect counts `1, 1, 1, 1, 1, 2`; effect sums,
order balances, operation identities, concurrent receipts and restart snapshots
are consistent. The unavailable-lookup result is unresolved despite one recorded
effect. The new-key control deliberately records two effects totaling 6200 cents.
Its three source-file hashes match `c0b1fb4`, `2374d36`, and audited HEAD.

## Exact raw file hashes

Paths below are relative to the repository root. SHA-256 values were recomputed
from file bytes and checked against the corresponding summaries/findings or manifest.

| File | SHA-256 |
|---|---|
| reports/qwen35-4b-live-v1.json | `3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7` |
| reports/qwen35-4b-live-v02.json | `2bc665369b0e943663485a3255cb4ddd5c503ff3997b77559c64d0604a985bad` |
| reports/challenge-v1-before.json | `4350df2a927427b391c077722705107d5680cd1f4997092439363fd5a7e09ea8` |
| reports/challenge-v1-after.json | `df2f8062a6202444bbfbea908bbaff7a7bf6d5c04e892d6507e5e4610771223f` |
| reports/independent-verification-v1.json | `6ce7c8c54e49279fdc1cd6c9cff003a54955282323e85208d96c4ab7f093e797` |
| reports/rules-original-v1/raw.json | `faf4c140bcdf15743ba9eab647a25bb361ee8d2128cd7c39919962c0ed8d5158` |
| reports/rules-challenge-v1/raw.json | `3aea13e5b4b280f361fe1e6a84ed4ca38db4351f59c29fea77b67a3e0e35de2c` |
| reports/remote-tool-lab-v1/evidence.json | `3c94f34b70d57e8bd55bc1d90fc64bb2afde182a37ffa552b7e02cdfdf83a788` |
| reports/fixture-v1.json | `7160337d55014a086536e446cb5e89422fb3a8e4265e68147ba83127221d36bf` |
| reports/fixture-v02.json | `894febf70aa095ba74aaf7e7add702dfee64abd9f8e24e2c2083f99003b130a4` |

The frozen challenge suite hash is
`77bfa60553343acdff60c1320b5a27650234799152a7d18561a6d88b9d707475`.
The copied independent suite hash is
`d8b7352d83565b427bac0931869e056220e6ef0cd24c2633989634e18ef30819`;
its independent validator and all three manifest entries pass unchanged.

## Historical source identity

The recorded algorithm hashes each sorted top-level `src/agentproof/*.py` file
as its basename, a NUL byte, then exact contents. Reconstructing those bytes
directly from Git reproduces every stated backend fingerprint:

| Snapshot | Use | Backend SHA-256 |
|---|---|---|
| d24e2aa | Original v1 and challenge before | `8a995e17a1e487c371d98331dca84d5e94ce2a6b93babae53cdf2ebf30cbc853` |
| e86c058 | Original v02 and challenge after | `160874be9243d56bfacf04fd43fc36d7b67a5c620c2ee28e6e2b9f4927d0d9c3` |
| cf991fb | Independent verification | `7c4e4df8592047ffc2eaffd41b225e1dc6233cce1e503c33ff6a66e6531c5dba` |
| cb9f87c | Rules controls | `fdadeb6d095bebbab3d18b91dc9749b5d2f731180dadb8c2ac48ff854084a7f5` |

Reproduce this source check without executing project code:

```sh
python3 - <<'PY'
import hashlib
import subprocess
from pathlib import PurePosixPath

for revision in ('d24e2aa', 'e86c058', 'cf991fb', 'cb9f87c'):
    paths = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', revision, 'src/agentproof'],
        text=True,
    ).splitlines()
    digest = hashlib.sha256()
    for path in sorted(paths):
        item = PurePosixPath(path)
        if item.parent == PurePosixPath('src/agentproof') and item.suffix == '.py':
            contents = subprocess.check_output(['git', 'show', f'{revision}:{path}'])
            digest.update(item.name.encode() + b'\0' + contents)
    print(revision, digest.hexdigest())
PY
```

Summary `source_revision` describes the reporting client's checkout, which can
differ from the evaluated server. The findings correctly use the raw server
fingerprint for execution-source identity. Git reconstruction verifies matching
source bytes, not the historical reporting process or loaded remote machine.

## Interpretation limits

Independent authoring means a separate author used only the supplied synthetic
policy/schema before seeing implementation or results. It does not make these
24 cases a randomized holdout, public benchmark or broad generalization result.
The original and challenge sets are development data; all repeated deterministic
trials are correlated. Correct approval stops have zero executed refunds.

Live-model reports include deliberately injected tool/provider failures. Recorded
HTTP attempts are distinguished from proposals and trials; token totals are
reported usage. No monetary inference cost, controlled latency speedup, model
weight improvement, production safety or real-payment reliability follows from
these results. Historical findings retain their measured timeout semantics and
host-activity caveats. Hashes identify bytes; they do not prove authenticity,
model identity, lack of omitted outside experiments, or independent execution.
