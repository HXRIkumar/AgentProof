# Explain AgentProof with evidence

## 45-second introduction

"I built AgentProof to test whether a tool-using AI workflow takes the correct
action, not just whether its answer sounds convincing. It runs a baseline and a
guarded workflow against the same refund scenarios. The guarded workflow checks
identity, amount and policy, pauses for high-value approval, and deduplicates
transaction retries. I built a React console to inspect each trace and the final
ledger. The project includes deterministic fault tests and a separate real-model
adapter, so I can distinguish infrastructure tests from model evaluations."

Use this after you can run the demo and explain the implementation. Do not claim
to have learned every component just because the code exists.

## Five-minute demonstration

1. **Open** the local console. **Show** the provider label. **Say:** "This first
   run is a controlled fault test. It is not a claim about model accuracy."
2. Run the full suite and inspect the paired matrix. **Say:** "Correct completion
   and safe behavior are separate. An agent that escalates everything can be safe
   but useless."
3. Select the commit-then-timeout scenario. Show baseline effects and guarded
   effects. **Say:** "The acknowledgement was lost after the write. A retry with
   the same identity finds the committed effect instead of creating another."
4. Select an approval case. Show the pending state, approve it and inspect the
   ledger. Repeat the approval API call if demonstrating idempotency. **Say:**
   "The approval decision and its effect are committed in one transaction."
5. Show a real-model experiment if one was run. Explain both failures and
   successes. Export JSON and show the scenario hash and checks.

## Architecture questions

**Why LangGraph?** It expresses observation, proposal, validation, execution and
grading as explicit transitions, including bounded feedback. It is not the source
of monetary correctness: the validator and transactional ledger provide that.

**Why not just ask a second model to judge?** A model judge can help assess prose,
but exact properties such as ownership, amount and duplicate effects are better
checked deterministically against actual state.

**What is idempotency?** Repeating the same logical operation has the same effect
as doing it once. Our unique run-and-effect key and SQLite transaction enforce
that property in this sandbox. Conflicting arguments for an existing key are an
error, not a successful cache hit.

**What if the process crashes?** Completed evidence and pending approvals survive
restart. This version does not automatically resume every interrupted graph node.
Fresh-sandbox replay reruns a stored scenario; it is not transparent crash recovery.

**Why SQLite?** It provides real transactions and a reproducible local lab with
low setup cost. For distributed workers I would evaluate Postgres and a durable
job queue, then test transaction isolation and replay before making stronger claims.

**How do you handle injection?** Retrieved notes are untrusted prompt data.
Regardless of model compliance, the execution gate independently checks allowed
monetary effects. This constrains this domain; it is not universal injection prevention.

**How is this an agent?** It is a bounded, tool-grounded workflow: observe state,
propose an action, process validation feedback, execute or escalate. The tool
sequence is constrained, not an unrestricted planner that can execute arbitrary code.

**What does the benchmark prove?** The controlled suite proves tested invariants
under authored failures. A live run measures one provider/configuration on those
tasks. It does not establish broad model superiority. Repeats do not create new
independent scenarios; held-out tasks and ablations would strengthen the evidence.

**What did you deliberately omit?** A vector database for a tiny exact policy,
unnecessary multi-agent personas, and an LLM-generated "reliability score" that
does not correspond to observable correctness.

## Practical exercises before interviews

- Add one valid and one invalid boundary scenario. Predict the ledger before running.
- Change the high-value threshold and identify every place requiring a test update.
- Explain a failed live trial and reproduce it from its stored scenario.
- Find the transaction that atomically records human approval and the effect.
- Explain why a stable key prevents duplicate writes but does not correct a wrong amount.
- Describe how you would add a second domain through typed tools and independent graders.

## Resume wording

Project: **AgentProof — Agent Reliability and Release Testing Workbench**

Stack: **Python, FastAPI, LangGraph, Pydantic, React, TypeScript, SQLite,
OpenTelemetry, Docker, pytest**.

- Built a paired evaluation workbench for policy-gated AI workflows, combining
  fault injection, trace inspection and final-state grading through a React console.
- Implemented bounded proposal correction, transactional refund deduplication and
  persisted approval decisions; tested timeout-after-commit and concurrent delivery.
- Added an OpenAI-compatible model adapter and reproducible JSON evaluation reports
  with separate scripted/live evidence and CI regression gates.

Only add numeric performance bullets from a saved report you can explain. Never
turn scripted pass-rate changes into claims that an LLM became more accurate.
