# Answer reliability: design decisions and evaluation plan

Prepared 12 November 2026 before running the new experiments. This changes the
main product from a refund-specific action laboratory to a reusable answer
reliability runtime. The earlier action laboratory and immutable evidence remain
available as a separate workspace.

## What we are building

An application developer supplies a question, source documents, and optionally a
JSON Schema. The runtime retrieves relevant evidence, generates a grounded answer,
checks its format and citations, obtains a separately prompted critique, and
repairs failures within a fixed budget. It saves accepted results in a scoped
SQLite cache. The console exposes every attempt, source citation, token and timing
measurement, and allows comparisons against the original one-call answer.

Two concrete workloads share the same runtime:

- Answer questions from source documents, with short evidence-backed answers and
  explicit abstention when the documents do not answer the question.
- Extract typed records from incident reports, tickets and reference documents,
  with JSON Schema validation and source citations.

This is inference-time workflow optimization, not training a new foundation model.
Its usefulness must be demonstrated by the quality/cost tradeoff, not by calling
every validator a new AI technique.

## Research translated into implementation

| Primary source | What it contributes | Implementation choice |
| --- | --- | --- |
| [Self-Refine](https://selfrefine.info/) and [reference code](https://github.com/madaan/self-refine) | Generate, give actionable feedback, refine under a bounded loop. | Structured failure feedback with attempt history; stop after passing or exhausting the budget. |
| [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798) | Intrinsic self-correction can fail or degrade answers without external feedback. | Validate against supplied evidence/schema; evaluate the final answer against separate reference labels; count regressions as well as recoveries. |
| [Sentence Transformers semantic similarity](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html) | Embeddings and cosine similarity identify related text. | Use embeddings for retrieval/cache candidates, not as a factual correctness score. |
| [GPTCache configuration](https://gptcache.readthedocs.io/en/latest/configure_it.html) | Separate embedding, storage and similarity evaluation components. | Scope cache by corpus/schema/config; require critic approval for semantic reuse; measure exact replay separately. |
| [SQuAD v2](https://rajpurkar.github.io/SQuAD-explorer/) | Human-written answerable and adversarially unanswerable reading questions with reference answers. | Freeze a seeded public development subset and a separate development split; use exact match and token F1. Retain dataset attribution/license. |
| [Phoenix evaluation metrics](https://arize.com/docs/phoenix/evaluation/pre-built-metrics) | Separate faithfulness, correctness, retrieval relevance and code evaluators. | Keep individual validation checks visible; never turn a passing citation check into a claim of answer correctness. |
| [Langfuse datasets](https://langfuse.com/docs/evaluation/experiments/datasets) | Dataset inputs/references and experiment comparison with trace inspection. | Separate references from inference; console drills from aggregate comparison to individual answer attempts. |

Research above supports design decisions. It does not establish results for this
implementation. Runtime, dependency versions and model snapshots will accompany
the actual reports.

## Experiments declared before results

1. **Shared-initial-answer comparison.** Generate an initial answer once per case.
   Evaluate it directly; reuse the exact same response for validation-only and
   critic-assisted repair. All policies receive the same question and source
   corpus. Logical per-policy cost includes the initial call; physical experiment
   totals count the shared call once. Execution order is seeded and balanced.
2. **Quality.** Report exact match, QA token F1, extraction field accuracy,
   answerability errors, validation false acceptance and mean validation score.
   The validation score is an explicitly defined rubric, not calibrated reliability.
3. **Correction.** Recovery = initially incorrect cases made correct / initially
   incorrect cases. Regression = initially correct cases made incorrect / initially
   correct cases. Retain both counts and paired case-bootstrap confidence intervals.
4. **Efficiency.** Report calls, retries and tokens per query; tokens per correct
   answer; wall-clock p50 and p95. Account for critic and embedding work. No paid
   dollar estimates without a declared real provider price.
5. **Exact cache replay.** Replay accepted requests after population and restart.
   Compare measured warm-request latency to their own cold generation latency.
   Publish counts, hit rate, answer equality, and p50 ratio. Do not describe a warm
   exact hit as faster reasoning on a new question.
6. **Semantic cache challenge.** Include paraphrases and near-miss questions with
   altered numbers, negation and entities. Track false hits and critic overhead.
   Exclude no misses to make the reported speedup look larger.

Development cases may guide prompts. Evaluation cases are frozen before runtime
results and are not used for tuning. Any post-evaluation improvement requires a
new study and explicit designation that the old evaluation set is now observed.
Public SQuAD data may have been in a model's training data; this is not a claim of
unseen general intelligence. Authored extraction cases are reported separately.

## Interface direction

A compact research workspace with a source editor, question composer and answer
inspector. Attempt history is the main visual: see an initial answer, a concrete
failed check, the revised answer, and its cost. Experiment tables show actual
sample counts, failures and deltas. No invented metric cards or decorative AI
gradients. Keep the legacy action laboratory accessible, and protect its tests.
