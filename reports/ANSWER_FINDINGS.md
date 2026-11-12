# Answer Lab: measured findings

The strongest improvement to the local generator was selective final-attempt escalation: **38/64 to 50/64 correctly delivered tasks**, from 59.4% to 78.1%. It used the hosted model for 10 final generation attempts after earlier checks failed. A stronger hosted base model with simpler validation-only retries reached **53/64** in the primary study, with lower latency and lower API cost than the hybrid configurations. More orchestration was not consistently better.

These are results on one frozen, small, public-derived workload—not general model accuracy, a calibrated reliability probability, or a production service-level guarantee. Every result below retains failures and regressions.

## Fixed protocol and evidence

- Frozen runtime: `4ffa994f70cab27a3c170ba4621e4ff866534d12`.
- [Evaluation suite](../examples/answer-suite-v1/evaluation.json): 64 unique cases: 24 answerable QA, 24 unanswerable QA, and 16 authored structured-extraction cases. SHA-256: `4b2d1c8a6b801175a313bd09bb3e4f2525d5428c68e2aa14beb2262707fdcd99`.
- QA is a modified [SQuAD 2.0](https://rajpurkar.github.io/SQuAD-explorer/) public-development subset with two distractor sources per question. Extraction cases are synthetic. The [suite manifest](../examples/answer-suite-v1/manifest.json) records selection, source hashes, and provenance. This is not the official SQuAD task or an unseen-training-data claim.
- Prompt and routing choices were developed on a separate 18-case [development set](answer-development/README.md). The four primary configurations were then evaluated without changing the frozen runtime, cases, or grading.
- Each study compares three policies on exactly the same first response for each case. **Baseline** makes one generation and applies deterministic checks. **Validated** permits up to three generations with deterministic feedback. **Adaptive** also asks a critic to review valid candidates. The cascade configuration replaces only the final permitted adaptive generation with the stronger model after earlier failure; it does not add an attempt.
- Response caching is disabled for quality measurements. Gold answers and reference fields stay in the offline evaluator. The runtime receives only the question, sources, and optional output schema.
- Local model: `mlx-community/Qwen3.5-4B-MLX-4bit`, recorded revision `32f3e8ecf65426fc3306969496342d504bfa13f3`, thinking disabled, 768 maximum generation tokens. Hosted model: `gpt-5.4-mini-2026-03-17`, medium reasoning, 1,536 maximum completion tokens including reasoning. Embeddings: pinned `all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.

An [independent offline auditor](../scripts/audit_answer_evidence.py), which imports neither the runtime nor the production grader, verified frozen case coverage, shared-response bindings, reference grading, physical versus logical calls/tokens, paid reservation uniqueness, costs, and frozen source bytes. The [audits](answer-audits/) identify the exact raw-report SHA-256. A passing audit means the recorded measurements reconcile; it does not certify every model answer as semantically true.

## Primary comparison

**Delivered correctness** requires a reference-correct answer or exact schema-valid extraction **and** an accepted/abstained runtime status. QA uses standard normalized exact match. Raw-answer correctness, independent of acceptance, is a separate metric.

| Configuration | Baseline | Validated | Adaptive | Adaptive change vs its baseline |
|---|---:|---:|---:|---:|
| [Local generator + local critic](answers/qwen-local-v1.json) | 38/64 · 59.4% | 39/64 · 60.9% | 41/64 · 64.1% | +4.7 pp; 95% CI −3.1 to +12.5 pp |
| [Hosted generator + hosted critic](answers/mini-hosted-v1.json) | 48/64 · 75.0% | **53/64 · 82.8%** | 52/64 · 81.3% | +6.3 pp; 95% CI +1.6 to +12.5 pp |
| [Local generator + hosted critic](answers/qwen-mini-critic-v1.json) | 38/64 · 59.4% | 39/64 · 60.9% | 47/64 · 73.4% | +14.1 pp; 95% CI +4.7 to +25.0 pp |
| [Local + hosted critic + final escalation](answers/qwen-mini-cascade-v1.json) | 38/64 · 59.4% | 39/64 · 60.9% | **50/64 · 78.1%** | **+18.8 pp; 95% CI +9.4 to +29.7 pp** |

Intervals are paired case-bootstrap intervals with 2,000 resamples of this same 64-case workload. They do not establish performance on other distributions. The local-critic interval includes zero. All three local-generator studies produced byte-identical initial response text on **64/64** cases; their baseline and validated results also matched. The hosted primary and local initial responses matched on 30/64 cases and use different generators.

The following adaptive breakdown prevents the balanced no-answer subset from hiding answerable-question failures:

| Adaptive configuration | Answerable QA correct / 24 | Unanswerable QA correct / 24 | Extraction correct / 16 | Mean QA token F1 / 48 |
|---|---:|---:|---:|---:|
| Local/local | 14 | 13 | 14 | 0.6663 |
| Hosted/hosted | 18 | 18 | 16 | 0.8227 |
| Local/hosted critic | 15 | 18 | 14 | 0.7898 |
| Local/hosted cascade | 17 | 18 | 15 | 0.8041 |

Mean QA F1 measures overlap with reference spans, not embedding similarity or a critic's confidence. The overall 64-case score depends on this particular mix of answerable, unanswerable, and extraction tasks.

## Recovery, regressions, and acceptance

| Adaptive configuration | Initially reference-wrong answers corrected **and delivered** | Initially undelivered/incorrect tasks recovered | Correctly delivered tasks regressed | Reference-incorrect accepted outputs |
|---|---:|---:|---:|---:|
| Local/local | 5/23 | 5/26 | 2/38 | 17/58 |
| Hosted/hosted | 1/12 | 4/16 | 0/48 | 10/62 |
| Local/hosted critic | 10/23 | 10/26 | 1/38 | 11/58 |
| Local/hosted cascade | **10/23 · 43.5%** | **13/26 · 50.0%** | **1/38** | 11/61 |

These denominators answer different questions. Cascade recovered 13 task failures, but only 10 were initially wrong reference answers; the other three were initially correct answers that had not passed the delivery contract. Its net gain is 13 recoveries minus one regression, or 12 additional successes. Raw-answer regressions were 2/41 for local/local and 1/41 for each hybrid configuration.

“Reference-incorrect accepted” is **not a hallucination count**. For example, the hosted adaptive answer `oscillating cylinder steam engine` fails exact match against `oscillating cylinder`, even though it may express the intended answer. Another case asks about a country's authority over **no** others; an accepted answer `sovereignty` conflicts with the frozen unanswerable label. The metric combines span mismatch, missed abstention, false abstention, and substantive answer errors. Scores were not relabeled after observing these examples.

## Efficiency and API accounting

Policy totals below are **logical standalone usage**: each policy includes the shared first generation it would need when run alone. Call counts include critic calls. Local compute and electricity are not priced as API charges.

| Policy/configuration | Model calls / 64 queries | Recorded token usage | p50 / p95 latency | API estimate for that policy |
|---|---:|---:|---:|---:|
| Local/local adaptive | 149 | 152,329 | 18.06 / 37.09 s | No paid API |
| Hosted validated | 71 | 78,840 | **1.76 / 4.37 s** | **$0.119404** |
| Hosted adaptive | 137 | 155,958 | 3.51 / 9.20 s | $0.234276 |
| Local/hosted critic adaptive | 161 | 179,655 | 10.77 / 30.66 s | $0.142346 |
| Local/hosted cascade adaptive | 170 | **Unknown total**; 189,427 observed | 10.58 / 33.82 s | **Unknown**; $0.198216 conservatively accounted |

Cascade made 29 retry generations across 64 queries, or **0.453 retries/query**. Ten final generations used the hosted model. Compared with local/local adaptive, it produced more correctly delivered answers with a lower measured median latency in these runs. These were separate periods on the same development machine, not isolated hardware latency experiments. Other development activity and hosted-service variation may affect timing. Latencies include retrieval, validation, inference, and attributed shared inference time; models and embeddings were already warm.

Actual experiment usage counts each shared first generation only once:

| Primary study | Actual model calls | Actual paid calls | Actual token total | API estimate / conservative accounting |
|---|---:|---:|---:|---:|
| Local/local | 164 | 0 | 169,047 | No paid API |
| Hosted/hosted | 144 | 144 | 164,911 | $0.248588 estimated and accounted |
| Local/hosted critic | 176 | 70 | 196,373 | $0.142346 estimated and accounted |
| Local/hosted cascade | 185 | 87 | Unknown; 206,145 observed | Unknown estimate; $0.198216 accounted |

Cascade retained two critic transport/response failures with unknown usage. Their unresolved reservations are $0.01232775 and $0.01200075. Unknown totals and cost-per-correct remain `null`; the project does not replace missing usage with zero or claim the reservation as the invoice charge. The application uses one cumulative USD 1.50 reservation guard across processes. That is an application-side guard, not a hard cap on unrelated account activity. Prices use full standard input/output rates without claiming cached-input discounts.

## Secondary hosted repeat

The [repeat plan](../docs/ANSWER_REPLICATION_PLAN.md) was recorded before the additional run. It reuses the same 64 questions, frozen code and hosted settings. It is neither 64 new cases nor permission to select whichever run looks better.

| Hosted run | Baseline | Validated | Adaptive | Actual paid calls | Study API estimate / accounting |
|---|---:|---:|---:|---:|---:|
| Primary | 48/64 | 53/64 | 52/64 | 144 | $0.248588 estimated |
| [Secondary repeat](answers/mini-hosted-repeat-v1.json) | 48/64 | 52/64 | 53/64 | 158 | Unknown estimate; $0.328519 accounted |

The one-case ordering between validated and adaptive **reversed**. Two runs do not establish a stable hosted accuracy advantage for either policy. Validation-only remained less expensive and faster in both runs; this supports exposing a policy choice instead of always enabling the critic.

Initial response text matched on 45/64 questions across the hosted runs. Reference correctness agreed on 57/64: 49 were correct in both, eight wrong in both, three correct only in the primary, and four correct only in the repeat. Identical baseline delivered totals therefore do not mean identical outputs.

The repeat retained one critic transport/response failure with an unresolved $0.0122715 reservation. Its 189,953 observed tokens are a lower-bound observation, not a known total. Adaptive recovered 3/11 initially reference-wrong answers and 6/16 task failures, with one regression. Concurrent ledger deltas can include another running study; each report's audited `actual_usage` is the attribution source.

## Persistent cache measurements

The separate [cache probe](answers-cache/qwen-cache-v1.json) completed four synthetic seed groups, five exact replays per seed, and 12 paraphrase/near-miss queries. All four cold seed answers and all 20 exact replays were reference-correct; every exact replay hit, with zero model calls on those replays. The service was reconstructed against the same SQLite database before replays, while retaining the adapter and embedding object.

For the **four correctly admitted seed groups**, the median per-group cold/replay-median ratio was **8,233.5×**. Across those groups, median uncached service time was 13,453.04 ms and median exact replay time was 1.564 ms; their pooled-median ratio is a different statistic, 8,601.7×. Neither figure measures speed on new questions. Timing covers `service.run`, including result persistence; model/embedding startup and service reconstruction are excluded. This is service reconstruction inside one Python process, not measured whole-process startup.

Semantic reuse hit on **2/12** query variants, both reference-correct. There were no negative-query hits, but only **10/12** variant answers were correct overall: exception and number-swap cases still failed. Therefore zero false hits does not mean all cache-workload queries succeeded. The entire 36-request probe made 34 model calls and recorded 21,617 tokens. Its audit regraded source/reference integrity and independently recomputed answer correctness, raw usage, and the conditional per-group speedup. It makes no broad throughput or arbitrary-paraphrase safety claim.

## Boundaries and future evaluation

All 48 QA requests in the primary suite contain three sources, with at most 2,085 characters per source; each therefore forms one chunk. Retrieval selects up to four chunks and selected all three in every measured QA case. Recall of 1.0 here is mechanically expected and **not evidence of selective retrieval quality**. The runtime implements lexical/embedding ranking, but these answer studies mostly test generation, checking, and correction.

Only the original QA source was independently annotated in SQuAD. Added distractors were filtered against known answer strings, but answerability was not human-rechecked over every expanded source set. Public benchmark exposure, synthetic extraction cases, small samples, balanced no-answer prevalence, and strict reference spans limit generalization.

Useful next work requires fresh evaluation material: adjudicated answer equivalence and false-premise cases; richer conflicting-source extraction; and corpora with more than the retrieval limit of competing passages. Keep those measurements separate from these frozen scores. A critic agreeing with an answer, or a validation score of 1.0, must never be presented as a calibrated probability of correctness.
