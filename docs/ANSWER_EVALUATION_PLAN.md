# Answer Lab: evaluation plan

Plan recorded before the 64-case evaluation split is run. Development and final
evaluation results must remain separate.

## Questions

1. Does deterministic feedback repair malformed, unsupported, or structurally
   invalid answers relative to a single generation?
2. Does a separately prompted critic improve answer correctness and valid
   abstention, or merely increase cost and reject correct outputs?
3. Does an efficient hosted critic improve a small local generator enough to
   justify its latency and API cost?
4. How does that hybrid system compare with using the same efficient hosted model
   for generation directly?
5. Does persistent selective caching reduce identical-query latency without
   returning incorrect answers for changed facts, numbers, entities or negation?

## Frozen data

- Development: `examples/answer-suite-v1/development.json`, 18 cases.
  SHA-256 `93e1310cd634918b76eb86ca648847afe0defc8737b2e196dc5313bf84d14dcf`.
- Evaluation: `examples/answer-suite-v1/evaluation.json`, 64 cases: 48 source-grounded
  QA tasks (24 answerable and 24 unanswerable) and 16 structured extraction tasks.
  SHA-256 `4b2d1c8a6b801175a313bd09bb3e4f2525d5428c68e2aa14beb2262707fdcd99`.
- Cache: `examples/cache-probe-v1.json`; four fixed fictional source groups, exact
  repeats and meaning-changing/paraphrase probes. This is a separate experiment.

The QA portion is derived from public SQuAD 2.0, with distractors. Extraction
records are authored synthetic examples. This is neither the full SQuAD benchmark
nor proof that models have never seen these source paragraphs in training. Gold
references are available only to the offline evaluator, never to the generator,
critic, correction prompts, retriever or cache.

## Compared policies

Each case has one recorded initial generation, reused unchanged across three arms:

- **Baseline:** single generation, output validation, no model retries.
- **Validated:** bounded correction using deterministic failure feedback.
- **Adaptive:** the same checks plus an explicit source-support, responsiveness and
  answerability critic; at most three total generations.

Each policy logically pays the initial generation cost. The actual study counts
that shared generation once. Policy execution order after baseline is seeded per
case. All final-evaluation cases, failures and regressions remain in the report.
Caching is disabled in the answer-quality study.

Configurations: pinned local Qwen3.5-4B 4-bit via MLX, Qwen generation with pinned
GPT-5.4 mini critic, and GPT-5.4 mini generation/critic. The hosted snapshot is
`gpt-5.4-mini-2026-03-17`, reasoning effort `low`, maximum 1,536 output tokens
including reasoning. Local generation uses 768 output tokens with thinking off.
Hybrid retrieval uses pinned `all-MiniLM-L6-v2` embeddings and lexical retrieval.
Exact revisions and every prompt/source-file hash are recorded in each raw report.

Hosted tests are explicitly enabled and use a single persistent US$1.50 client-side
reservation ledger across all experiments. This leaves a buffer within the user's
stated US$2 balance. There are no automatic transport retries. Unknown request
outcomes retain their full reservation. Account billing remains separate from the
application's conservative cost estimate.

## Development decisions

The first development runs identified an extraction wrapper error and an abstention
contract error; both were repaired before evaluation. Raw earlier runs are retained
in `artifacts/answers-dev-*`. A local thinking-critic diagnostic was interrupted
after the abstention defect was identified and a 90-second transport timeout was
observed. Its incomplete results are not used as headline evidence.

After corrected development runs, freeze the runtime and configuration before
running evaluation. A final-evaluation failure may become a future regression test,
but must not prompt a silent change followed by replacement of the same evaluation
report. Any later tuned evaluation must be labelled as such and use a fresh suite
for independent confirmation.

Development extension before any evaluation run: compare the same efficient hosted
mini with low versus medium reasoning, and test optional final-attempt escalation
only after earlier local revisions fail. Both remain within the existing three
generation limit and the shared spending ceiling. These are development hypotheses;
include an escalation candidate in the final comparison only if development results
and regression tests justify it, and record its exact configuration separately.

## Final configuration selection

Selected before evaluation: local-only Qwen; Qwen with mini critic at medium
reasoning; that same hybrid with final-attempt escalation; and all-mini generation
and critique at medium reasoning. Each evaluates all three policies on the same
64 cases. Local models use temperature zero; hosted reasoning calls omit temperature.
The selected cascade reached 15/18 development tasks (direct Qwen 11/18), with four
initial errors recovered and no initial-success regressions. This selection result
is development evidence, not a promised evaluation outcome.

The frozen evaluation checkout retains one exact source revision for all runs.
Local-generator studies execute sequentially against the Mac model server. The
all-hosted study may overlap them but does not call that model server. Machine and
network latency remain descriptive rather than isolated hardware benchmarks.

## Measurements and interpretation

Primary outcome: reference-correct **and delivered** task success. Also report QA
exact match/token F1, typed extraction field accuracy, initial-failure recovery,
regression of initially correct outputs, incorrect-accepted output rate, retries,
logical/actual model calls, known token usage, cost per correct answer, and p50/p95
end-to-end latency. Runtime validation score is not a calibrated probability.

For paired success differences, bootstrap whole cases (2,000 seeded draws), not
individual strategy rows. Call a gain measured on this suite when its point estimate
is positive; only describe statistical evidence of a positive gain if the paired
95% interval excludes zero. Never turn a small-sample result into general model
accuracy. A higher success rate with greater cost is a tradeoff, not automatically
an efficiency gain. Report both outcomes and retain negative findings.

Cache speedups are paired cold-run versus warm identical-query measurements. Keep
the correct-answer-conditioned result separate from all cache hits; report false
hits and changed-query outcomes. Do not apply an exact-repeat speedup to new queries.
Local compute, electricity, machine purchase cost and concurrent development load
are not included in API dollar estimates. Latency is descriptive for this Mac and
network, not a hardware-isolated service-level guarantee.
