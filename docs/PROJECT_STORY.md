# Why I built AgentProof

## The problem, in one example

Imagine a small SaaS product with documentation for invitations, webhooks and billing. A customer says their invitation expired. A teammate searches the guide, checks the expiry rule, asks an administrator to send another invitation and writes a reply. The next customer reports a webhook failure. This time the teammate searches a different guide. A refund request needs a human decision rather than a confident AI promise.

A generic chat window can generate text, but the application still needs to answer: Which document version did this come from? What happens if a quotation is wrong? Did the worker finish after the browser closed? Has someone approved this exact draft? Is the policy still current when we export it?

**AgentProof makes that document-to-resolution workflow explicit and reusable.** It is intended for a developer or small internal support team; actual adoption and time savings have not been measured.

## A natural 60-second interview explanation

> I built AgentProof to turn product documentation and support tickets into evidence-backed drafts that people can actually review and use. The problem is that an LLM can write a convincing answer while using an outdated rule, quoting a passage incorrectly or promising an action it cannot perform.
>
> I built a FastAPI service and React workspace with document versions, a persistent ticket queue, hybrid retrieval and structured LLM output. The runtime checks schemas and citations, uses specific feedback for bounded correction, and retains failures. A reviewer can edit a supported reply or escalate it; changing the underlying knowledge makes old drafts stale.
>
> Developers can use the same workflow through a Python SDK. I also evaluated the answer engine separately: on a frozen 64-case workload, a local model with a hosted critic and selective escalation improved delivered correctness from 59.4 to 78.1 percent. I kept the regressions and cost tradeoffs visible rather than claiming the system always fixes the model.

Do not memorize every word. Remember **problem → workflow → engineering → evidence → limits**.

## Where it is useful

| User / situation | What they can do now | Why it helps |
|---|---|---|
| Developer maintaining a SaaS product | Upload support guides, import exported tickets, review drafts | One place for the request, documentation, draft and handoff. |
| Internal technical-support teammate | Inspect a source passage and version before approving a response | Makes the reasoning evidence available during the decision. |
| Developer integrating AI into an existing tool | Submit documents/tickets through the SDK and consume reviewed JSON | Reuses queueing, correction and provenance without rebuilding each piece. |
| AI engineer choosing a generation policy | Compare direct, validation-only and critic-assisted results in the experiment view | Shows whether extra model calls justify their cost on a stated workload. |

A company already using a mature support platform may be better served by that platform. This project is a focused implementation to learn from, extend, or embed; it does not claim commercial superiority.

## Five-minute demonstration

1. **Knowledge:** open the invitation guide and show the 72-hour policy. Explain that these are fictional sample documents.
2. **Invitation ticket:** read the customer request, show the actual local-model draft and its source quotation. Show the separately stored reviewer edit and exported JSON.
3. **Failed webhook ticket:** open its model trace. The model combined source sentences into a non-verbatim quotation, exhausted its attempts and was escalated. Do not describe this as a successful automatic repair.
4. **Refund and vague tickets:** show the human handoff and clarification request. The system neither issued a refund nor invented an account-specific diagnosis.
5. **Developer usage:** open `examples/support_sdk.py`. Point out the persistent job ID, idempotency key and separate review command. Finish with the published engine findings, clearly separate from the ticket walkthrough.

The public website is a read-only recording. To demonstrate uploading new files and model generation, run the local application. Review actions in the published sample were performed by the build agent for demonstration; they are not customer activity.

## Questions worth preparing for

**Why not just use a prompt?**
A prompt produces an answer. An application also needs persistence, progress, versioned evidence, failure handling, concurrency control and a review/export boundary. Those are implemented around the model.

**Is this just RAG?**
Retrieval is one stage. The product also manages document versions, queued work, typed output, bounded correction, reviewer edits and stale-knowledge checks. RAG retrieves context; it does not by itself provide the rest of that workflow.

**What exactly is self-correction?**
The runtime returns specific validation or critic feedback to another generation attempt, within a fixed attempt budget. It stops on acceptance or exhaustion. Correction can fail or make a correct answer worse, which is why the evaluation reports regressions.

**What is your strongest measured result?**
On 64 fixed QA/extraction cases, the local-generator cascade improved delivered correctness from 38 to 50 cases. Thirteen initially unsuccessful tasks recovered and one initially successful task regressed. This is not general model accuracy or a support-ticket success rate.

**Why have a local model if the hosted model did better?**
The project supports different deployment constraints. The local workflow works without paid inference; hybrid inference explores selective use of a stronger model. The primary experiment showed that a simple hosted validation policy was a better cost/latency tradeoff for that workload. I would choose based on data rather than insist on the more complicated pipeline.

**Does a citation prove the reply is correct?**
No. Exact matching checks that quoted text exists. It does not prove the interpretation is correct or the source is authoritative. The critic is fallible too; evidence and human review remain visible.

**What happens when the policy changes?**
Uploading a changed document creates a new version. The previous passage remains available for history, but old results become stale. Approval/export requires current knowledge, so the operator must regenerate and review.

**Can it send replies or issue refunds?**
No. It exports a reviewed reply or handoff JSON. External sending, authentication, permissions and account actions need a separate integration. Detected financial/account-changing requests, such as the recorded refund request, are blocked from reply approval. The current keyword guard and model do not guarantee detection of every possible wording.

**What would you do next for production?**
First secure a specific deployment: tenant isolation, authentication, retention controls and access checks. Then pilot on representative, permissioned tickets with human-reviewed labels, measuring factual errors, review time and acceptance rate. Add a helpdesk adapter only for that real workflow. Those are future requirements, not completed features.

## Resume wording supported by the work

**AgentProof SupportDesk | Python, FastAPI, React, SQLite, Sentence Transformers**

- Built a document-grounded support workspace and Python SDK with versioned PDF/Markdown ingestion, durable ticket processing, cited structured drafts, reviewer edits and stale-knowledge export checks.
- Engineered hybrid retrieval and bounded schema/citation/critic correction; a local-generator cascade improved delivered correctness from **59.4% to 78.1% on 64 frozen QA/extraction cases**, recovering 13 initial task failures with one regression.
- Implemented idempotent job submission, cancellation, retained model traces and a scoped persistent response cache; published raw outputs and cost/latency comparisons, including failed corrections and missing usage.

Only use this wording after you can demonstrate and explain those components. Do not add users, revenue, hours saved, production uptime, calibrated reliability percentages or customer-resolution rates: those have not been established. Keep the source reports available when discussing the numerical result.
