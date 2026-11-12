# Answer Lab v1 implementation contract

New work on `codex/answer-reliability-v2`, preserving all v0.4 source and evidence.
Purpose: improve and measure grounded LLM answers and structured extraction, with
bounded correction, a separately prompted critic, hybrid retrieval, selective
cache, and reproducible evaluation. The answer runtime never receives gold labels.

## Runtime request

`POST /api/answers/run` (synchronous; local single-user application):

```json
{"question":"When was the service launched?","sources":[{"id":"doc-1","title":"Launch notes","text":"The service launched in 2023."}],"task":"qa","schema":null,"strategy":"adaptive","max_attempts":3,"use_cache":true,"namespace":"workspace"}
```

Tasks: `qa` (short extractive answer or abstention), `extraction` (JSON Schema).
Strategies: `baseline` (one generation), `validated` (deterministic feedback only),
`adaptive` (deterministic feedback plus an independent critic prompt; retry only
after failed checks). Max attempts 1–3. Sources and question bounded. Schema is
optional for QA, required for extraction; schema keyword uses alias if needed.
Only caller-supplied sources are used, no network tools or generated-code execution.

## Runtime result

```json
{"id":"uuid","created_at":"ISO8601","task":"qa","strategy":"adaptive","question":"When?","status":"accepted","answer":"2023","data":null,"abstained":false,"citations":[{"source_id":"doc-1","quote":"The service launched in 2023."}],"quality":{"score":1.0,"checks":[{"name":"schema","passed":true,"detail":"Valid response"}],"label":"Validation score, not probability"},"attempts":[],"cache":{"status":"miss","similarity":null},"usage":{"calls":2,"prompt_tokens":100,"completion_tokens":50,"total_tokens":150,"known":true},"latency_ms":1000,"model":"local-model","source_hash":"hex","config_hash":"hex"}
```

Statuses: `accepted`, `abstained`, `failed`, `error`. Abstention is not an error;
only offline reference grading determines whether it was correct. Each attempt:
`index`, `answer`, `data`, `abstained`, `citations`, `checks`, `critic` (null or
structured critique), `latency_ms`, `usage`, `feedback`, `output_text` (bounded).
Runtime output includes a validation score, never a claim of correctness.
Every actual model call including critics counts in usage and latency.

`GET /api/answers/config`: `configured`, `model`, `embedding_model`, `strategies`,
`max_attempts`, `provider_kind`. No API keys or base URLs returned.
`GET /api/answers/runs`: array of recent result objects.
`GET /api/answers/runs/{id}`: full saved result.
`GET /api/answers/reports`: array of `{id,title,model,created_at,summary}`.
`GET /api/answers/reports/{id}`: exact saved benchmark JSON.
No fabricated demo metrics. Example inputs allowed; saved results must be real.

## Cache / retrieval

SQLite cache stores only adaptive outputs accepted by deterministic validation
AND critic. Namespace, source corpus hash, schema, task, model and prompt/config
fingerprints scope cache. TTL. Exact hits need no model call; semantic candidates
use local sentence embeddings, conservative number/negation compatibility, and a
fresh critic on the new question before serving. Similarity is not correctness.
Track misses, exact/semantic hits, rejected candidates, calls and tokens separately.
Sentence-transformer is optional and lazy loaded; lexical retrieval remains usable
when unavailable. Never silently represent lexical retrieval as embedding inference.

## Evaluation

Freeze a seeded, balanced SQuAD v2 development subset (with provenance and license)
plus separately authored extraction cases BEFORE runtime results. Public subset,
not unseen model training data. Gold only reaches offline evaluator. Shared initial
answers for paired policies avoid baseline drift. Run at least baseline, validated,
adaptive; retain errors and failed trials. Warm-cache latency is a separate replay
study, never compared to cold improvement trials as one general speedup.
Report exact match, token F1, schema/field accuracy, initial-to-final recovery,
regression rate, validation false accepts, retries/query, calls/query, tokens per
correct answer, p50/p95 latency, cache hit rate, semantic false-hit rate, and exact
warm-cache speedup with sample counts. Paired case bootstrap intervals for deltas.
Null denominators stay null. Never fabricate a percentage or model result.

## Ownership

Runtime agent owns `src/agentproof/answers/` and `tests/test_answers_runtime.py`.
Evaluation agent owns `src/agentproof/answer_eval.py`, `scripts/answer_benchmark.py`,
`scripts/freeze_answer_suite.py`, `examples/answer-suite-v1/`, matching eval tests.
Frontend agent owns `web/src/AnswerLab*`, `web/src/answer*`, new answer browser QA.
Root owns API mounting, main entry routing, dependencies, integration, live studies,
research/decision notes and review. Coordinate contract changes before editing.
