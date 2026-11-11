# Does this workflow need a model?

The refund decision in this laboratory does **not** require an LLM. Identity,
delivery status, age, balance and requested amount are already structured.
A small policy function can decide it. AgentProof studies the reliability and
cost of an LLM workflow when one is used; it does not claim that an LLM is the
best implementation of this business rule.

## Predeclared comparison

Run a separately labelled rules-only provider through the same guarded engine,
approval boundary, read recovery, current-policy refresh and transaction ledger.
The decision function accepts observed facts only, rejects extra oracle fields,
ignores retrieved prose, and never receives evaluation labels or case IDs.
It makes zero model requests. This is different from the scripted fault provider,
which intentionally corrupts proposals to test infrastructure.
Rules runs record `prompt_hash: null`: no model prompt was executed. Their policy
implementation is covered by the recorded source fingerprint.

Before running, mark only `model_outage` and `malformed` as inapplicable: the live
provider explicitly injects an outage or malformed output for these cases.
Keep their original IDs and reasons visible; never change expected labels.
The `over_amount` and `wrong_order` switches corrupt only the scripted provider;
they do not corrupt live-model outputs, so their live tasks remain applicable.
Direct rules-engine calls also refuse the two inapplicable fault types, preventing
traces from claiming a model fault was injected when no model was called.
Injection notes also remain applicable as irrelevant untrusted text. Read failures, duplicate
delivery, lost acknowledgements, stale policy and human approval remain active.

For each supplied complete live export, reuse exactly its scenario values and
repeat count. Compare rules results with only the corresponding guarded live
trials; report both denominators and every exclusion. Keep suites separate.
Use the same engine default proposal budget (three). Do not approve pending
requests. A source fingerprint records the current rules run; the earlier live
export retains its own fingerprint. They are not falsely labelled the same build.

```sh
uv run python scripts/rules_reference.py reports/qwen35-4b-live-v02.json \
  --output-dir reports/rules-original-v1
uv run python scripts/rules_reference.py reports/challenge-v1-after.json \
  --output-dir reports/rules-challenge-v1
```

The command refuses an existing output directory and validates the input export
with the strict release-report validator. It saves the exact input SHA-256,
applicability decisions, raw runs, separate SQLite ledger and a readable report.
Current exports with later human approval actions are refused.

Correct outcomes and effect invariants are graded against the original labels.
Latency is descriptive: the older model run and this local rules run occurred at
different times, so do not advertise a controlled speedup. Zero model requests
and zero model tokens are direct properties of this policy adapter. Deterministic
repeats are correlated and do not expand the number of distinct tasks.

This comparator is a CLI research control, not an additional web-console provider.
Its purpose is to expose the simpler alternative and an engineering tradeoff,
including findings that favor ordinary code. It is not a release gate or a claim
about general agent tasks. An unstructured intake task might justify inference,
but it would need its own dataset, evaluation and evidence.
