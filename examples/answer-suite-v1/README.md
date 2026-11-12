# Frozen answer suite v1

This suite was selected and frozen before any Answer Lab model results. It contains
**18 development cases** (12 QA, 6 extraction) and **64 evaluation cases** (48 QA,
16 extraction). Development is for prompt/runtime diagnosis; report evaluation
results separately. Do not tune on evaluation outcomes and call them unseen.

## Source and attribution

The QA questions, answer references, and passages derive from the Stanford
Question Answering Dataset, SQuAD v2.0 development split, by Pranav Rajpurkar,
Robin Jia, and Percy Liang. See the
[official dataset](https://rajpurkar.github.io/SQuAD-explorer/) and
[paper](https://arxiv.org/abs/1806.03822). SQuAD data is distributed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the derived QA
portion retains that license. Each case keeps its original question ID and article
title. Authored extraction cases are synthetic, distributed under the repository's
MIT license, and labelled separately.

Original download:
`https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json`

Original SHA256:
`80a5225e94905956a6446d296ca1093975c4d3b3260f1d6c8f68bc2ab77182d8`

The extraction cases were written for this project before runtime outputs existed.
They cover incident/support records, corrected values, missing values, numerical
types, ordered arrays, quoted instructions, record selection and avoiding invented
values. They are not real customer records or an established public benchmark.

## Selection and modifications

Selection seed is `20261112`. We sort question IDs by a seed-prefixed SHA256,
cycle through topics, require distinct original paragraphs across both splits,
and restrict original passages to 150–2400 characters. Each split has equal
answerable and unanswerable QA counts. Six of each category go to development;
24 of each go to evaluation.

Each QA request includes its original passage plus two full distractor paragraphs
of 150–650 characters from different topics, and the source order is shuffled.
Known answer strings are excluded from distractors. Original question paragraphs
are not reused as distractors. These additions deliberately change the task:
**this is a SQuAD-derived multi-source subset, not an official SQuAD leaderboard
score.** Alternative answerability after distractor insertion was not independently
relabelled. Public pretraining contamination is unknown. Small subset and laptop
results do not establish general model accuracy.

## Reproduce and verify

The immutable JSON file hashes are in `manifest.json`. The exact generator used
at freeze time is retained byte-for-byte as `frozen-generator.py.txt`; its SHA256
matches `extractor_sha256` in the manifest. The executable script in
`scripts/freeze_answer_suite.py` subsequently received lint-only changes; use the
archived generator to reproduce metadata and output bytes exactly.

```sh
curl -L --fail https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json -o /tmp/squad-dev.json
python examples/answer-suite-v1/frozen-generator.py.txt \
  --upstream /tmp/squad-dev.json \
  --extraction examples/answer-suite-v1/authored-extraction.json \
  --output /tmp/answer-suite-reproduced
```

The generator refuses to overwrite a frozen split. Runtime requests come only
from each case's `request` object through an explicit field allowlist; `gold`
remains in the offline evaluator. Evaluation uses SQuAD normalized exact match and
token F1 for QA. Extraction uses schema validity and typed field accuracy/F1.
The answer validation score is never treated as reference correctness.

```sh
ANSWER_LAB_BASE_URL=http://127.0.0.1:8089/v1 \
ANSWER_LAB_MODEL=your-local-model \
python scripts/answer_benchmark.py run \
  --suite examples/answer-suite-v1/development.json \
  --output-dir artifacts/answer-development-run
```

The CLI permits only local inference endpoints. It preserves every initial
response before policy evaluation, shares that exact initial response among
baseline/validated/adaptive, disables answer caching, records per-policy logical
cost separately from actual study calls, and checkpoints every trial. Model errors
stay in the denominator. An interrupted study is not complete. Changed runtime
files invalidate the complete-study flag. Bootstrapped comparisons resample paired
cases, not repeated calls as independent samples.
