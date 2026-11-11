# The structured refund decision does not need an LLM

A separately implemented rules function received the same observed order facts
and used the guarded workflow's policy checks, approval stop, tool recovery and
transaction ledger. It ignored untrusted prose and never read case IDs or
expected outcomes. The input to each comparison was a complete frozen live export;
its labels and repeat count were unchanged.

| Applicable set | Guarded model correct | Guarded rules correct | Model HTTP attempts / rules | Reported model tokens / rules |
|---|---:|---:|---:|---:|
| Original: 22 of 24 cases, three repeats | 66/66 | 66/66 | 75 / 0 | 30,138 / 0 |
| Challenge: 28 of 30 cases, two repeats | 50/56 | 56/56 | 100 / 0 | 47,658 / 0 |

Both methods passed every defined effect invariant on their applicable trials.
Both stopped at the same valid pending approvals: three original and eight
challenge trials. The rules method completed all six challenge trials that the
model workflow escalated incorrectly. It neither called a model nor consumed
inference tokens. The model's greater overhead is not needed for this policy.

## Applicability was declared before collecting the rules results

Only `malformed` and `model_outage` faults are excluded because the live adapter
itself injects them. The original excluded IDs are `malformed` and `model-outage`;
the challenge IDs are `challenge-malformed-unauthorized` and
`challenge-model-outage-expired`. Their original input records and labels remain
in each raw reference document. No failing case was deleted to improve a score.

`over_amount` and `wrong_order` alter the scripted fault provider only. They do
not corrupt live responses and remain included in this comparison. Injected
lookup/write failures, stale policy observations and adversarial notes also
remain included. [Protocol and commands](../docs/RULES_REFERENCE.md).

## Evidence and scope

- [Original rules report](rules-original-v1/report.md) and [raw evidence](rules-original-v1/raw.json).
  Raw SHA-256: `faf4c140bcdf15743ba9eab647a25bb361ee8d2128cd7c39919962c0ed8d5158`.
- [Challenge rules report](rules-challenge-v1/report.md) and [raw evidence](rules-challenge-v1/raw.json).
  Raw SHA-256: `3aea13e5b4b280f361fe1e6a84ed4ca38db4351f59c29fea77b67a3e0e35de2c`.
- Rules implementation commit: `cb9f87c`.
  Executed source fingerprint: `fdadeb6d095bebbab3d18b91dc9749b5d2f731180dadb8c2ac48ff854084a7f5`.

The rules runs' observed p95 trial latencies were 54.943 ms and 64.732 ms,
respectively, including the local engine and journal. The matching earlier model
subsets recorded 18,101.792 ms and 53,691.019 ms. These were different runs with
different source snapshots and concurrent host activity, so this is descriptive
evidence and not a controlled speedup ratio. The zero model-call property is
directly established by the rules adapter and tests.

This control exposes an architectural choice. AgentProof is a workbench for
testing consequential actions in model workflows, not evidence that every such
workflow should contain a model. For this fully structured policy, ordinary code
is the better decision mechanism. An unstructured intake or planning task might
benefit from a model, but that would need separate data and evaluation. These
results must not be pooled with live-model accuracy or described as a model upgrade.
