# Use AgentProof SupportDesk

## Start locally

Follow the setup commands in the [README](../README.md), then double-click `scripts/open-supportdesk.command` or run it in Terminal. The Mac launcher needs Apple Silicon and cached model weights. It starts local inference and the application, opens http://127.0.0.1:8010, and disables paid inference. Keep its Terminal window open; Ctrl+C stops only its owned services.

If a service already uses port 8010 or 8089, the launcher stops with an explanation instead of killing it. Open the existing workspace or close the launcher that owns those ports.

For an already running local OpenAI-compatible server:

```sh
export ANSWER_LAB_BASE_URL=http://127.0.0.1:8089/v1
export ANSWER_LAB_MODEL=YOUR_LOCAL_MODEL_NAME
export ANSWER_LAB_DISABLE_THINKING=true
export ANSWER_LAB_MAX_TOKENS=1024
export ANSWER_LAB_ENABLE_PAID=0
export ANSWER_LAB_CRITIC_BASE_URL="$ANSWER_LAB_BASE_URL"
export ANSWER_LAB_CRITIC_MODEL="$ANSWER_LAB_MODEL"
export ANSWER_LAB_CRITIC_DISABLE_THINKING=true
export ANSWER_LAB_ESCALATE_FINAL=false
unset ANSWER_LAB_API_KEY ANSWER_LAB_CRITIC_API_KEY OPENAI_API_KEY
.venv/bin/uvicorn agentproof.api:app --host 127.0.0.1 --port 8010
```

Set `ANSWER_LAB_MODEL_REVISION` to your actual pinned model revision when available. To use pinned local embeddings, set `ANSWER_LAB_EMBEDDING_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41` after downloading the weights. Missing embeddings produce an explicitly labelled lexical fallback. Model options differ by server; the Mac launcher pins the configuration used by the recorded product demo.

## First walkthrough

1. In **Knowledge**, upload the four Markdown files from `examples/supportdesk/knowledge/`. These contain fictional Harbor product rules, not real company policies.
2. In **Work queue → Import**, choose `examples/supportdesk/tickets.csv`. You can also create a ticket manually.
3. Select one or more tickets and start processing. The queue persists independently of the browser. Refresh or reopen the page to reconnect.
4. Select a finished ticket. **Draft** shows the structured assessment and proposed reply; **Evidence** shows quotations and document versions; **Activity** records processing and review actions. **Model trace** shows attempts and usage.
5. Read the evidence yourself. If a reply is supported and approval is available, edit it if needed and approve. Otherwise escalate with a useful note. A completed job is not automatic approval.
6. Click **Export** after review. The JSON contains the reviewed reply or handoff, source versions, reasons and trace IDs. Nothing is sent to a customer.

The supplied four tickets include a normal invitation problem, a webhook failure, a refund request and an underspecified issue. Model outputs may vary. The recorded walkthrough retains an actual webhook citation failure; a different run need not reproduce the exact same outcome.

## Files and limits

- Knowledge: Markdown, TXT, text PDF; up to 5 MiB each, 300,000 extracted characters and 200 PDF pages. Encrypted, unreadable and scanned-only PDFs are rejected; there is no OCR.
- Active knowledge: up to 100 documents, 2 million extracted characters and 2,000 chunks. This is a small-workspace implementation, not an enterprise search index.
- Ticket import: CSV or a JSON list; `title`, `body`, optional `external_id`; up to 50 rows and 1 MiB. Identical external IDs/content are idempotent; conflicting content is rejected before import.
- A ticket can store 20,000 body characters, but inference currently uses a 2,200-character excerpt. Omitted text is recorded and blocks approval; use a concise complete request or escalate.

Uploading a changed file under the same filename creates a new version. Removing a document archives it; historical source records remain readable. Any active-knowledge change marks earlier drafts stale. Regenerate and review before exporting again.

## Queue and review behavior

Queued cancellation is immediate. Running cancellation takes effect after the current bounded model work; it does not pretend to interrupt a provider HTTP request. Actual results and usage remain stored. After a process restart, queued jobs resume automatically; interrupted running jobs are marked failed and the operator chooses whether to retry them.

An idempotency key identifies one logical processing request. Reuse it when investigating an uncertain submission; use a new key for intentional regeneration. The Python SDK has the same behavior as the UI. Review uses optimistic record versions so an old screen cannot silently approve a newly changed ticket.

Human-edited reply text stays separate from model output. Approval does not prove that an arbitrary reviewer edit is correct. Reviewers remain responsible for what they approve.

## Product versus experiments

The default view is SupportDesk. **Reliability experiments** opens the separate answer-engine console. Its frozen 64-case QA/extraction results measure the engine on that specific workload, not ticket resolution or real customer outcomes. Earlier tool-action experiments remain in the legacy workspace.

The public GitHub Pages site uses saved JSON only. It cannot upload documents, run a model or accept reviews. Its sample sources are fictional, model outputs are real recorded results, and reviews were demonstration actions performed by the build agent.

## Integrate or extend

Use the [Python SDK guide](SUPPORT_INTEGRATION.md) and `examples/support_sdk.py`. The REST API is available through `/api/docs` on the local server. The product is single-user and should bind to localhost. Authentication, tenant isolation, external messaging and CRM adapters are future integration work. The latest review is retained separately from immutable model output; previous human reply edits are not yet a versioned review history.
