# Frozen expanded-corpus retrieval stress test

This is a separate **retrieval-only** experiment using 24 already-observed,
answerable questions from the frozen Answer Lab evaluation split. Each question
now has 20 source documents: its original annotated passage and 19 deterministically
selected distractors. The purpose is to test passage selection when the corpus
exceeds the production retrieval cutoff of four chunks.

The main answer suite gives each QA request three short sources. With a cutoff of
four, retrieving its annotated source is trivial. That source-recall result cannot
establish useful retrieval discrimination. This expanded setting addresses that
measurement gap without changing the production retriever or rerunning answer
generation.

**This is not an unseen test set, a new answer-quality benchmark or an official
SQuAD result.** Questions and relevant paragraphs have already been used in the
answer study. No LLM generation, critique, correction or paid API is used here.
The data was frozen before ranking; the dataset card contains no measured result.

## Provenance and construction

- Parent: `examples/answer-suite-v1/evaluation.json`, SHA-256
  `4b2d1c8a6b801175a313bd09bb3e4f2525d5428c68e2aa14beb2262707fdcd99`.
- Frozen retrieval suite: `suite.json`, SHA-256
  `709d0acd3f47da88e0000ca906f3933282f50d942d60a2a12bbfc4b5ea8f0420`.
- Pool: 52 distinct source texts from all QA cases in that parent split; extraction
  documents and development questions are not added.
- Query selection: all 24 parent QA cases labelled answerable. No query was selected
  or removed based on retrieval performance.
- Seed: `20261112`. Each query independently hashes candidate identities to choose
  19 distractors, then uses a separate hash to shuffle all 20 source positions.
- Duplicate text is compared after case folding and whitespace normalization.
  Source identities use text SHA-256 prefixes, avoiding parent source-ID collisions.
- Distractors exclude the annotated source and any normalized substring matching
  any known reference answer. The generator refuses to weaken this exclusion if
  there are too few eligible sources.
- `manifest.json` records suite, archived-generator and per-case hashes.
  `frozen-generator.py.txt` preserves the exact generator used during freezing.

After freezing, the executable runner's final integrity check was strengthened
to revalidate the archived generator too. The frozen files were preserved. Use
the archived script only to reproduce the freeze; run measurements with the
current `scripts/retrieval_benchmark.py`, whose executed hash is recorded.

All sources retain their original text. They fit the existing runtime input limits;
the frozen source documents are shorter than the production chunk size. The runner
still records actual source and chunk counts instead of assuming they are equal.

The sole relevance annotation is the parent gold source. The other documents are
**unjudged distractors**, not independently confirmed irrelevant passages. Exact
answer-string exclusion does not rule out equivalent or alternative evidence and
can make the test easier. The metric therefore measures retrieval of the original
annotated source, not exhaustive relevance across the corpus. It does not measure
answer correctness, evidence sufficiency or retrieval on arbitrary user documents.

The questions and passages derive from SQuAD v2.0 and retain **CC BY-SA 4.0**.
Original question IDs and article attribution remain in each case. See the
[parent dataset card](../answer-suite-v1/README.md) for the upstream data, paper,
license and previous selection changes. Public-training contamination is unknown.

## Reproduce the freeze

From the repository root, write to a new directory:

```sh
uv run python examples/retrieval-suite-v1/frozen-generator.py.txt freeze \
  --parent-suite examples/answer-suite-v1/evaluation.json \
  --output-dir /tmp/agentproof-retrieval-reproduced
```

The suite bytes are deterministic. The manifest's creation timestamp will differ.
Freezing checks the parent hash and does not invoke retrieval or load embeddings.
Existing output directories are never overwritten. Preserve this frozen directory
when changing a future test; create a new version instead.

## Run the separate ranking study

Run only after other local-model experiments finish, to avoid laptop contention.
The embedding model must already be cached at this exact revision:

```sh
uv run --extra embeddings hf download sentence-transformers/all-MiniLM-L6-v2 \
  --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41
```

This is a one-time free model download. The ranking command itself uses cached
weights only, on CPU:

```sh
uv run --extra embeddings python scripts/retrieval_benchmark.py run \
  --suite examples/retrieval-suite-v1/suite.json \
  --output-dir artifacts/retrieval-stress-v1
```

Both arms call the actual production `retrieve()` function with identical query,
source text and source order. **BM25** passes no embedder. **Hybrid** uses the pinned
MiniLM embedding model with the production scoring weights. Gold annotations are
read only after the retriever returns its ranking; they are not passed into scoring.

For the diagnostic full rank, the runner asks the same function for all chunks.
It separately calls the normal cutoff of four and verifies that the resulting
identities match the full ranking's first four entries. Unit tests cover this prefix
property with deterministic fake vectors. No production scoring formula changes.

If embeddings cannot load or an arm falls back to lexical retrieval, the hybrid
trial is an error. The tool never presents that fallback as a measured embedding
result. It retains BM25 rows and failed hybrid coverage but does not publish complete
hybrid aggregate metrics. It also refuses to overwrite an existing result directory.

## Output and interpretation

`raw.json` is checkpointed after each query/arm. It records:

- Suite/manifest, per-query corpus and executed-code hashes; embedding revision,
  installed package versions and configuration hash.
- Full ranked chunk identities, offsets, text hashes and lexical/semantic scores.
- First rank of any chunk belonging to the single annotated source, selected
  source IDs, source/chunk counts, recall at one and four, and reciprocal rank.
- Per-arm aggregates with planned, recorded, ranked and error counts. Incomplete
  arms have null aggregate metrics; failed or interrupted studies retain their rows.
- A final integrity check that the suite, manifest and executed code remained
  unchanged during the study. A changed input or runtime cannot produce a
  `completed` report.

With one annotated relevant source per question, **recall@1** is the fraction of
queries placing it first, **recall@4** is the fraction placing it within the four
production-selected chunks, and **MRR** is the mean reciprocal of its first rank.
For multi-chunk sources, this is source-level recall from chunk rankings, not
localization of the answer span. All frozen documents currently fit in one chunk.

Report both arms even if BM25 matches or beats hybrid. This is a small expanded
setting with reused queries, fixed weights and limited relevance labels. It can
reveal ranking failures; it does not prove that hybrid retrieval generally improves
answer quality. This runner makes no latency or cost-efficiency claim: embedding
warmup and repeated-prefix checks are not a production performance benchmark.
