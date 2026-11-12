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
5. Open **Recorded evidence → Challenge suite · v0.2**. These are saved real-model
   trials and require no model server. Show both a failure and a success. Download
   the original JSON and expand **Recorded provenance** to show the suite and
   executed-source hashes. Historical approvals have no action buttons.
6. Open `reports/RULES_REFERENCE_FINDINGS.md`. **Say:** "I also tested the simpler
   alternative. For this fully structured policy, ordinary code was better than
   the model and made no inference calls. That is a useful finding, not something
   I hid to make the project look more AI-heavy."

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
independent scenarios. A separate author created 24 verification cases after the
implementation was frozen and without seeing the existing implementation,
prompts or results. That reduces one source of bias; the small synthetic set is
not evidence of general reliability. It is now public and cannot remain unseen
for future development.

**Why use an LLM when rules can solve this?** The workbench studies how to test a
model workflow and constrain its effects. The rules-only control shows that this
specific structured decision should use ordinary code. I would use models for
ambiguous language tasks only when an evaluation demonstrates enough value to
justify their cost and remaining errors. The current project does not claim to
solve that broader language task.

**What makes the service-boundary test different?** The regular workflow uses a
local transactional ledger. A separate executable lab starts another process
with its own database and sends real HTTP requests. The server can commit and
then close its socket before the response arrives. The client must reconcile
using the same key. That lab is tested evidence for this protocol, not an
integration with a real payment provider or the default model workflow.

**How did you prevent a misleading release gate?** A comparison requires complete
compatible reports, regrades the final ledger, and checks every guarded case.
One regressed case fails even when the aggregate improves. The browser displays
the exact captured snapshots used by the comparison, so a later approval cannot
silently change the evidence shown beside the decision.

**What if usage is missing?** A missing token count is unknown, not free. New
response diagnostics distinguish reported usage from unavailable usage. An
efficiency analysis cannot approve a cost claim when any actual model response
has unknown accounting. Older exports are explicitly labelled as aggregate-only
evidence; their absent details cannot be reconstructed.

**Did you test whether retries help?** Yes: a separate study kept the guarded
workflow fixed and compared one versus up to three proposals. Challenge correct
outcomes rose from 30/60 to 54/60, but reported tokens rose from 23,802 to 47,658.
That violated the predeclared token-efficiency threshold. It supports a bounded
correctness benefit, not a claim that more retries are always worth their cost.
It also does not isolate wording from the opportunity to try again.

**What does tracing add?** One run span contains its stage spans, and the saved
run includes the same trace and span IDs received by a real OTLP collector in
tests. Span status OK means the evaluation finished; task correctness is a
separate attribute. An interrupted evaluation does not export the run object's
initial safety flag as a verified result.

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

## The numbers you should be able to explain

All model results below used a local quantized Qwen3.5-4B model. The orders,
customers and effects are synthetic. Model-provider and tool faults were also
deliberately injected in some scenarios. Read each report's fault mapping.

The later [Phi portability study](../reports/MODEL_PORTABILITY_FINDINGS.md)
is separate: 46/48 guarded original outcomes and 60/60 guarded challenge outcomes.
Two exact-threshold failures remain. Explain this as a second-family workflow
check, not proof that one model is generally better. Both models ran locally on
the Mac without paid inference.

| Comparison | Correct guarded outcomes | What to explain |
|---|---:|---|
| Original suite, v0.1 → v0.2 | 66/72 → 72/72 | 24 cases repeated three times; 10.3% more reported tokens |
| Challenge suite, v0.1 → v0.2 | 32/60 → 54/60 | 30 cases repeated twice; six failures remain; 29.8% more reported tokens |
| Independent verification, frozen v0.3 | 48/48 | 24 independently authored cases, two repeats; small synthetic verification |
| Applicable challenge control | Model 50/56; rules 56/56 | Two provider-fault cases excluded explicitly; rules made zero model requests |

Do not combine these denominators into one accuracy claim. Suites overlap,
repetitions are correlated, and the controls answer a different question.
All defined guarded effect checks passed in these studies, but passing the checks
does not establish correctness beyond what those checks cover. Latencies were
measured on a development Mac with other work running, not an isolated benchmark.

**A useful failure to discuss:** on `challenge-note-token-refund`, the guarded
workflow still escalated after its proposal budget in the published v0.2 study.
The safe ledger had no unauthorized effect, but the valid task was not completed.
Open its trace rather than guessing why the model failed. A safe refusal is not
automatically a successful task.

## Learn the code in 45 minutes

1. **10 minutes — run and inspect.** Open recorded challenge evidence, identify
   one correct and one failed trial, and explain each final ledger in one sentence.
2. **10 minutes — follow one request.** Read `api.py`, then the worker in
   `jobs.py`, then `Engine.run` in `engine.py`. Identify where the scenario enters
   the graph and where completed evidence is saved.
3. **10 minutes — explain one guarantee.** Read the effect transaction and
   approval handling in `store.py`/`engine.py`. Explain why a key must stay the
   same after an ambiguous response, and why it must reject conflicting arguments.
4. **10 minutes — explain evaluation.** Read `grading.py` and one case in
   `examples/challenge-suite-v1.json`. Point out that the expected outcome belongs
   to the evaluator and is excluded from the model observation.
5. **5 minutes — rehearse honestly.** Give the introduction, one failure, one
   measured improvement, the rules-only finding and one limitation without reading.

Terms: a **trace** is the record of a run's steps; a **span** is one timed part of
that trace; an **invariant** is a property that must remain true; an **ablation**
changes one component to measure its contribution; **idempotency** keeps repeated
delivery of one logical operation from creating another effect.

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

Optional measured bullet, after you can explain the linked study:

- Improved guarded task completion from 32/60 to 54/60 on a frozen 30-case
  synthetic refund challenge using bounded factual correction and policy refresh;
  preserved all defined effect checks, with 29.8% more reported tokens and six
  remaining failures on a local Qwen3.5-4B model.

Only add numeric performance bullets from a saved report you can explain. Never
turn scripted pass-rate changes into claims that an LLM became more accurate.
