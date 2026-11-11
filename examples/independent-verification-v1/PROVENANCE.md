# Independent synthetic verification suite, version 1

This directory contains 24 manually designed synthetic cases for an AI refund
workflow. The sole source was the written policy and JSON schema supplied in
the authoring assignment. The author did not inspect target implementation,
prompts, existing test suites, benchmark reports, Git history, or other agents'
files. No source code was copied from an existing project. No model calls,
network requests, or paid APIs were used to author or validate the suite.

The cases were selected before seeing target execution results. They cover
valid small and large requests, monetary and age boundaries, ownership and
status restrictions, unavailable evidence, recoverable proposals, retry and
duplicate behavior, policy labels, and untrusted retrieved notes. Descriptions
state the policy reason for each expected outcome. Identifiers and customer
notes are fabricated; they are not records of actual customers or incidents.

## Independent interpretation of the supplied policy

Missing order evidence and a permanent read outage require escalation before
other request checks. When authoritative evidence is available, invalid
ownership, delivery status, age, or amount requires rejection. A permanent
model outage escalates an otherwise eligible request, including one whose
amount would ordinarily require approval. Without that outage, an eligible
request above 10000 cents requires approval, and one at or below that threshold
is refunded for the exact requested amount.

A transient read timeout is assumed to receive its specified single retry,
which returns the actual fixture order. Other listed faults are recoverable or
effect-preserving and do not change the desired business outcome. Retrieved
notes and opaque policy version labels do not alter authoritative facts or
eligibility rules; stale policy observations can be refreshed.

## Validation and limitations

`validate.py` uses only Python's standard library. It validates the explicit
fixture fields and types, allowed enum values, 24 unique case IDs, and expected
outcome labels using a separately expressed policy oracle. It rejects boolean
values in integer fields, duplicate JSON keys, and non-JSON numeric constants.
It prints the suite SHA-256 and outcome distribution without modifying files.

This is a small, purposively selected synthetic verification suite. It is not
a public benchmark, a random sample, or evidence of broad generalization.
Passing the local validator establishes fixture consistency only. It does not
show that a target workflow handles these cases, uses the current policy
version, refunds the exact amount, or produces exactly one monetary effect.
Those properties require subsequent evaluation of the frozen target system.
All 24 cases are intended to be retained in that evaluation, including any
failures. No case was selected or revised based on target-system results.

## File freeze

The frozen inputs are `independent-verification-v1.json`, `validate.py`, and
this file. `SHA256SUMS` records their exact byte hashes. The files and manifest
are made read-only after generation. Read-only permissions are a local guard
against accidental edits; the hashes are the evidence for byte identity. Any
later revision must be separately versioned and must not silently replace
this version. Suite contents remain withheld from the implementing agent
until that agent confirms its source is frozen.

To validate without changing any files, run:

```sh
python3 validate.py
shasum -a 256 -c SHA256SUMS
```
