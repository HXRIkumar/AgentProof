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

## Completed ablation and diagnostic follow-up audit

Audited separately on 12 November 2026 against revision `c63e907`. This appendix
leaves the earlier audit above intact. It covers only the completed
[216-trial proposal-budget study](../reports/ABLATION_FINDINGS.md) and
[16-trial diagnostic probe](../reports/DIAGNOSTIC_FINDINGS.md). No model calls
were made and no ongoing model-portability outcomes were inspected.

Independent standard-library calculations read the raw JSON without importing
the runtime, grader or analysers. They checked unique trial IDs, complete
case/arm/repeat coverage, typed monetary effects, policy-derived expected
dispositions, pending-proposal validity, recorded grades, ordered attempt events,
injected versus HTTP attempts, retries, tokens and nearest-rank percentiles.
All 232 trial records agree with those calculations. No numerical, gate,
source-fingerprint or copied-file discrepancy was found.

| Study / arm | Correct | Effect checks | HTTP attempts | Reported tokens | Retries | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Original A1 | 40/48 | 48/48 | 42 | 16472 | 6 | 11011.135 |
| Original A3 | 48/48 | 48/48 | 52 | 20914 | 20 | 20742.278 |
| Challenge A1 | 30/60 | 60/60 | 54 | 23802 | 6 | 41308.020 |
| Challenge A3 | 54/60 | 60/60 | 100 | 47658 | 56 | 67313.212 |
| Diagnostic baseline | 2/8 | 6/8 | 8 | 4118 | 0 | 46708.074 |
| Diagnostic guarded | 2/8 | 8/8 | 20 | 11916 | 12 | 141365.303 |

These rows remain separate studies and suites, not a pooled accuracy claim.

### Ablation reconciliation

Seed `20261112` reconstructs the exact saved 216-item schedule, including each
case's reversed A1/A3 ordering on its second repeat. Both arms retain the same
model, initial prompt, source and configuration fingerprints; each run records
the declared one- or three-proposal budget. Suite, configuration, schedule and
per-run scenario hashes agree. The original embedded cases match the earlier
original-suite export; the challenge file matches the frozen Git bytes and hash.

All 54 per-case comparisons agree with both analyses and the readable report.
The original gains eight outcomes on four cases (`remaining`, `amount-injection`,
`stale-policy`, `malformed`); the challenge gains 24 on twelve cases. Neither
suite loses a correct per-case outcome. The three reported remaining challenge
failures each occur twice under A3, with no effect. Correct approval stops are
2/2 in the original A1/A3 arms and 2/8 in the challenge A1/A3 arms; all retain
zero effects and valid pending proposals.

Original tokens increase by 26.966974%; challenge tokens by 100.226872%.
The p95 ratios are respectively 1.883755 and 1.629543. Thus the predeclared
correctness conditions pass, the challenge's additional-token rule fails, and
neither p95 ratio crosses 2. Both saved analyses correctly report that the
combined study rules fail. Incremental tokens/calls per additional correct
outcome are 555.25/1.25 and 994/about 1.916667, as stated in the findings.

There are 248 recorded trial HTTP attempts. The separate common warm-up records
one attempt and 398 reported tokens, excluded from those totals. No trial has
per-response usage diagnostics: the newer analysis correctly identifies
`legacy_aggregate_only` and leaves accounted/incomplete-attempt coverage null.
Its zero counters do not establish complete usage telemetry. The reanalysis
file's analyser hash matches `src/agentproof/ablation.py` at its stated
`e08008a` revision; original metrics and the adoption decision remain unchanged.

### Diagnostic reconciliation

The four input cases match the plan's committed file exactly. Both repeats of
`eligible` pass for both strategies; every selected challenge repeat fails.
The saved experiment gate correctly fails the 90% guarded-correctness rule.
All 28 actual response events have HTTP 200 and accepted, present usage fields:
ten are `length` with `invalid_json` (eight guarded, two baseline), and eighteen
are `stop` with `valid` (twelve guarded, six baseline). No other combination is
recorded. The summary's descriptive interval arithmetic also agrees; this does
not make correlated trials independent observations.

The two guarded note-token traces each contain three invalid JSON responses;
attempts two and three have equal captured-content hashes. Both partial-balance
traces request 5500 cents three times while policy changes from v3 to v4. Both
approval-boundary traces request 4000 cents, then return length/invalid JSON,
then reject with the recorded `10000 > 10000` reasoning. These observations
support the precise distinctions in the findings. Malformed response text was
not retained, so its claimed content cannot be reconstructed from its hash.

### Byte preservation and Git source identity

All three original ablation outputs (`raw.json`, `summary.json`, `report.md`)
are byte-identical to the completed outputs in the frozen `ad22f89` worktree.
The diagnostic raw, summary and Markdown files likewise match the completed
`deb02f9` worktree outputs byte for byte. All four ablation `SHA256SUMS` entries
match. Raw evidence and earlier reports were not changed by this audit.

| Additional file | SHA-256 |
|---|---|
| reports/ablation-local-20261112/raw.json | `123036ba01def221e2bddecb7e6a0c4e43db955a181588673227494961b5563c` |
| reports/ablation-local-20261112/summary.json | `56f05441a1df98899cd2d235cf0624db9cab5b5af102a1c6adac8ff7f4458f2b` |
| reports/ablation-local-20261112/report.md | `5bc2b37f8500bd3ad12d09df648d0490f4923b02936b193c202af902e7ad00f7` |
| reports/ablation-local-20261112/analysis-v04.json | `eddec856123f3940de7dc571dbb5c343d6f5340fa598395e9b20748ede6db01f` |
| reports/diagnostic-focus-v1.json | `21ad61b5f9738d2edb9b5cf966a393f43a3181836d3b23c3df18a8779677efc7` |
| reports/diagnostic-focus-v1.summary.json | `4c52fc2dc8a6f6ab496e3110d9eb91fef6e0f6041dffff7ddac944174b16aaeb` |
| reports/diagnostic-focus-v1.md | `0ee1db36e63cca56ad506d239c54478c027f7b11ab16dfe554207a92cba67a07` |

Reconstructing sorted top-level backend Python files from Git, hashing each
basename, NUL and contents as above, yields diagnostic fingerprint
`1dbbc1f97be2f52d5de18c4cb632461a4c12a9f2f5050cecbffd3356ed605144` at both
`b00395d` and the plan/data-only `deb02f9`. The ablation algorithm additionally
appends `scripts/ablate.py` using that same framing; at `ad22f89` it yields
`369155c542a00482353ebd6b7576f7fad55c43e6d5efbb523efb17188385fe49`.
Literal system-prompt bytes at both executed revisions reproduce the common
recorded prompt hash. The committed plan/input hashes agree and their recorded
Git commit times precede their respective study starts.

This remains a consistency audit of saved evidence. It does not independently
attest historical HTTP traffic, model weights, hardware isolation, reported
token accuracy or the absence of unrecorded experiments. The diagnostic report's
dirty reporting-checkout flag is retained; executed backend identity is checked
from its separate server fingerprint, not inferred from that flag.
