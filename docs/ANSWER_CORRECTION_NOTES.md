# Abstention review and duplicate-key correction

Implementation candidate based on `15e232c`, developed in an isolated checkout.
No evaluation-split outputs were inspected and no model requests were made for
this patch. The original local study remains frozen and unmodified.

## Development evidence

The completed 18-case development v3 run recorded 11/18 delivered successes for
the baseline and 9/18 for adaptive correction. Adaptive output content matched
references on 12/18 cases, but three correct abstentions failed delivery. In those
three cases the critic correctly returned `answerable: false`, while also returning
`supported: false` and `responsive: false`. The previous runtime incorrectly
required all three dimensions to pass even when there was no answer claim.

Adaptive correction consumed 49,788 logical policy tokens versus 16,627 for the
baseline, with median latency approximately 15.00 s versus 6.37 s. These are
small development-set observations, not general model performance. The purpose of
this patch is to correct a contract mismatch and redundant retries, not to imply
that additional critique automatically improves answers.

The same run also repeated a malformed extraction response containing several
`quote` properties in one citation object. Its generic schema error did not tell
the generator what structure to repair. Strict duplicate-key rejection itself is
correct and remains in place.

Development evidence: `artifacts/answers-dev-qwen-v3/raw.json` in the main checkout.
SHA256: `b08dbf550e02ad76bc829b72c51e40c23540a99e3809e6908c90e464d57ba631`.

## Contract change

For an explicit, deterministically valid abstention, source answerability is the
applicable semantic verdict: `answerable: false` approves abstention;
`answerable: true` rejects it. Support and responsiveness are not applicable to an
absent answer. The raw critic verdict is retained unchanged in the trace.

All four critic fields are still required and strictly typed. A malformed,
truncated, incomplete, or transport-failed critique cannot approve a result.
Deterministic abstention checks must still pass first: empty answer, null data,
and no citations. Non-abstaining answers still require support, responsiveness,
and answerability. Abstentions are not inserted into the answer cache.

The critic prompt now describes this interpretation directly. Validation version
is incremented to 4, changing the runtime/cache fingerprint. Generator prompts,
case labels, retrieval, and budgets are unchanged by this patch.

For duplicate JSON properties, a typed `DuplicateJSONKeyError` retains only a
small allowlist of fixed protocol field names. A repeated `quote` receives a
specific instruction to use separate citation objects while retaining extracted
data. Unknown keys and model content are not echoed in the feedback or error.
The parser never selects an arbitrary duplicate value or silently repairs JSON.

## Verification

162 answer-runtime, independent, evaluator, cache, delivery, and new correction
tests passed. New tests cover correct and incorrect abstentions; missing critic
fields; malformed/truncated reviews; invalid abstention shapes; all three checks
for actual answers; cache non-admission of abstentions; and duplicate-key feedback
with a successful deterministic repair. Ruff and diff whitespace checks passed.

This is functional regression evidence, not a new model benchmark. A separately
frozen rerun is required before reporting any recovery, accuracy, token, or latency
improvement from this candidate.
