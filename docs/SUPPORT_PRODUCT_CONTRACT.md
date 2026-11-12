# AgentProof SupportDesk — product implementation contract

Current user priority: build a meaningful usable product, not more benchmark or
test infrastructure. Existing studies may finish, but do not expand them. The
primary workflow is documentation + incoming tickets -> cited structured drafts
-> human review -> export. The answer runtime remains the reusable reliability
engine. No customer messages are sent automatically. No customer outcomes claimed.

## Scope and ownership

- Backend agent: `src/agentproof/support/`, focused workflow tests. Expose
  `SupportService(db_path, answer_service)` with `.start()`, `.stop()`, and
  `create_router(service)`. Do not edit main API, dependencies or frozen answers.
- Frontend agent: `web/src/SupportDesk*`, `support*`, `main.tsx`, product browser QA.
  Coordinate API changes here. Preserve Answer Lab and legacy workspaces.
- SDK agent: `src/agentproof/client.py`, SDK example and integration guide.
- Root: dependencies/main API mounting, upload body ceiling, real demo execution,
  recorded product packaging, documentation positioning and integration.
- Commit only owned paths (`git commit --only ...` after staging); shared index.

Single-user local app; SQLite persistence, one durable ticket worker. Reuse existing
AnswerService and provider/budget configuration. No LLM calls while the frozen
controller is still running. No new paid configurations or budget increases.

## API contract

All paths start `/api/support`. Errors use FastAPI `{detail: string}` with safe
messages. IDs are server UUIDs. Times ISO8601 UTC. Record versions are integers.

- `GET /config`: `{configured, model, critic_model, embedding_status,
  worker_available, knowledge_revision, max_upload_bytes}`.
- `GET /documents`: array of active Document summaries.
- `POST /documents`: `{filename, content_base64}`; TXT, Markdown, PDF. Maximum
  decoded file 5MiB, extracted text 300000 chars, PDF200 pages, no OCR. Reject
  unreadable/encrypted/no-text files clearly. Root allows this route's JSON body
  up to8MiB; other existing API body ceilings stay unchanged. Server extracts
  PDF text with page metadata; filenames never become filesystem paths.
- `GET /documents/{id}`: Document + full extracted text. Historical versions remain
  readable for existing citations. `DELETE` archives the active document (no
  physical deletion). Duplicate filename+content is idempotent; changed content
  creates next version and archives previous active version atomically.
- `GET /tickets`: array of Ticket summaries, newest first.
- `POST /tickets`: `{title, body, external_id?:string}`. Title max200, body max20000.
- `POST /tickets/import`: `{filename, content_base64}` accepting CSV or JSON list;
  CSV headers `title,body,external_id` (subject/description aliases acceptable).
  At most50 rows and1MiB decoded content (2MiB request-body allowance for base64),
  validate before writes; return `{tickets, created_count,
  duplicate_count}`. Same external ID+content is idempotent; changed content409.
- `GET /tickets/{id}`: Ticket + `result` (nullable), `events`, `active_job` nullable.
- `POST /tickets/{id}/process`: `{strategy?:"adaptive"|"validated"|"baseline",
  idempotency_key:string}`. Return Job. Default adaptive, max3generations. Capture
  document-version snapshot at enqueue. Duplicate key+same request returns same
  job; conflicting key or already-active ticket409. Unconfigured provider503;
  no active knowledge422. Snapshot must remain readable after docs change.
- `GET /jobs/{id}`: Job with progress/state and safe error.
- `POST /jobs/{id}/cancel`: queued job cancels immediately; running job requests
  cancellation after the current bounded ticket inference finishes. Retain any
  actual result/usage; do not claim interruption of an in-flight provider call.
- `POST /tickets/{id}/review`: `{decision:"approve"|"escalate", expected_revision:
  int, reply?:string, note?:string}`. Return updated Ticket detail. Optimistic
  revision check409. Approval requires an accepted runtime result, next_action
  reply, citations and current knowledge revision. Stale drafts409, regenerate.
  Human-edited reply retained separately from immutable model output. Escalation
  preserves reasons and human note; no customer contact.
- `GET /tickets/{id}/export`: approved response or escalated handoff JSON with
  document versions, human decision and trace references. Unreviewed409.

## Shapes

Document: `id, filename, title, version, content_sha256, created_at, active,
page_count, chunk_count, text?`. Stored extracted text/pages are the citation source.
Knowledge revision hashes sorted active document ID/version/content hashes.

Ticket: `id, external_id|null, title, body, status, revision, created_at, updated_at,
category|null, priority|null`. States: `open, queued, processing, review, approved,
escalated, failed, cancelled`. Detail extends with result/events/active_job.

Job: `id,ticket_id,status,created_at,started_at,finished_at,cancel_requested,error`.
States: `queued,running,completed,failed,cancelled`. Restart marks interrupted jobs
failed with an explicit interrupted reason (no silent paid retry); queued jobs
remain durable. Single active worker avoids local-model contention. Stop owned
worker cleanly; no unrelated processes.

Result: `data, answer_run, sources, knowledge_revision, stale, reasons`.
`answer_run` is the actual existing AnswerResult including attempts/usage/citations.
`sources` map runtime source IDs to document ID/version/page/chunk and text.
`data` follows the extraction schema:

```
summary: string
category: technical | account | billing | other
priority: low | normal | high
next_action: reply | clarify | escalate
draft_reply: string
follow_up_question: string
```

Do not invent urgency, policy terms, refund approvals or account-specific facts.
Unknown information -> clarify or escalate. Classifications are assistance for a
human reviewer, not autonomous consequential decisions. Store every failure.

Retrieve relevant chunks from the persistent active-document snapshot (all stored
docs, not only manually pasted sources), using production hybrid retrieval with
explicit lexical fallback, then pass bounded top passages into AnswerService as
extraction evidence. Keep page/version mapping. Bound ingestion/index sizes and
candidate count explicitly; no silent document dropping. Root/agent may choose
SQLite FTS5 prefilter for large corpora; disclose method in result metadata.

## UI

SupportDesk is default live app: Work queue, Knowledge, selected ticket's Draft /
Evidence / Activity. Document upload/remove with confirmation; CSV/JSON import and
manual ticket create; process individual or queue selected tickets; visible async
states/cancel-after-current-ticket; editable reply review; approve/escalate/export.
Show stale knowledge warning and generation errors. Model traces secondary drawer.
No fabricated dashboard numbers, placeholder integrations or automatic sending.

Answer Lab remains at `?workspace=answers` and legacy at `?workspace=legacy`.
Recorded build defaults to a READ-ONLY real saved support demo at
`BASE_URL/support/demo.json`, schema `{format:"agentproof-support-demo-v1",
config,documents,tickets}` (tickets are full details). Clearly label example
documents/tickets and actual recorded model outputs. Disable all mutations. Root
generates this only after a real end-to-end local/model run. Until then show an
honest empty recorded state. Existing answer QA must target `?workspace=answers`.

## Validation

Focused tests for persistence/idempotency, document revision/stale approval,
bounded import, queued cancellation/restart, and real browser workflow. Reuse
existing engine tests; do not add bulk test-count padding or new benchmarks.
Success is a usable end-to-end workflow with real uploaded files and actual model
outputs, plus a client an application developer can call.
