# Use SupportDesk from Python

`SupportClient` connects an application to a running AgentProof server. Upload product documentation, submit tickets, wait for a cited draft, and record a human review before exporting. The SDK does not call an LLM provider directly or send customer messages.

Start the AgentProof API using the project's server instructions. Provider/model settings belong to that server. The Python package already includes `httpx`; after `uv sync`, use `uv run python` from this checkout or install the package into your application environment. The default server URL is `http://127.0.0.1:8010` (the server root, without `/api/support`). This release is a single-user local application; the SDK does not add a remote authentication system.

## Create a draft

```python
from agentproof.client import SupportClient

with SupportClient() as client:
    config = client.get_config()
    if not config["configured"] or not config["worker_available"]:
        raise RuntimeError("Configure and start the server's worker first")

    document = client.upload_document("product-guide.md")
    ticket = client.create_ticket(
        "Reset email has not arrived",
        "I requested a password reset ten minutes ago. What should I try?",
        external_id="helpdesk-1042",
    )

    key = client.new_idempotency_key()
    # Save key and ticket['id'] in your application BEFORE making the POST.
    job = client.process_ticket(ticket["id"], idempotency_key=key)
    print("Keep this job ID:", job["id"])
    client.wait_for_job(job["id"], timeout=180)
    draft = client.get_ticket(ticket["id"])
    print(draft)
    # Stop here. A person reviews the reply and cited document versions.
```

Responses are the API's dictionaries/lists. A ticket detail contains `result`, `events`, and `active_job`; the result contains structured `data`, `sources`, `knowledge_revision`, `stale`, `reasons`, and the actual `answer_run` trace. A completed processing job means work finished, **not** that the answer was approved or that every runtime check passed. Inspect the ticket's status and result before deciding what to do.

`process_ticket` requires an explicit idempotency key. Create one UUID per logical request, persist it, and reuse it if you intentionally retry after a connection failure. Repeating the same key/request returns the same job; conflicting use returns HTTP 409. The SDK never automatically retries a POST. Ticket creation/import supports stable external IDs, and duplicate document filename+content uploads are idempotent.

## Review, then export

After a person checks the actual draft and citations, submit the revision they reviewed:

```python
with SupportClient() as client:
    reviewed = client.review_ticket(
        ticket_id,
        decision="approve",                 # Explicit human decision
        expected_revision=reviewed_revision, # Taken from the displayed ticket
        reply=human_edited_reply,            # Optional; original output is retained
        note="Checked the cited password-reset instructions.",
    )
    export = client.export_ticket(ticket_id)
```

Do not fetch the latest revision silently and approve it on behalf of a reviewer. An intervening edit or knowledge change must cause a fresh review. Approval requires an accepted runtime result, a reply action, citations, and the current knowledge revision. Stale drafts are rejected with 409 and need processing again using a new request key. Choose `decision="escalate"` with a human note when appropriate; the export then contains a handoff rather than an approved response. An unreviewed ticket cannot be exported. Export returns JSON; it does not send email, update a CRM, or contact a customer.

## Files, imports, and cancellation

```python
with SupportClient() as client:
    # Documents are bounded to 5 MiB; ticket imports to 1 MiB.
    client.upload_document("manual.pdf")
    client.upload_document_bytes("quickstart.md", b"# Sign-in\nUse the reset link.")
    imported = client.import_tickets("tickets.csv")
    client.cancel_job(job_id)
```

Knowledge supports TXT, Markdown, and text PDFs; encrypted/unreadable/scanned-only PDFs are rejected. The server preserves document versions for citations. `archive_document(id)` removes active knowledge without deleting historical evidence. A changed file version may make an existing draft stale.

Ticket imports accept a CSV or JSON list with `title`, `body`, and optional `external_id`, up to **50 rows and 1 MiB of decoded file content**. Both path-based and bytes-based client methods reject oversized imports before making a request; document uploads retain their separate 5 MiB limit. Validation occurs before writes. Repeating an external ID with identical content is idempotent; conflicting content is rejected. The client also offers `list_documents`, `get_document`, `list_tickets`, `get_ticket`, and `get_job`.

Queued jobs cancel immediately. A running job requests cancellation after its current bounded inference finishes; the client does not pretend to interrupt a provider request. `wait_for_job` polls GET endpoints with a deadline and bounds each request timeout by the remaining time. Network timeout limits apply to HTTP phases; it is not a hard real-time scheduler. A wait timeout leaves the server job running. Call `cancel_job` explicitly if cancellation is intended.

## Errors and ownership

| Exception | Meaning / next action |
|---|---|
| `SupportConflictError` | HTTP 409: inspect revision, active job, knowledge freshness or idempotency conflict. |
| `SupportAPIError` | Safe server error with `status_code` and `detail`; e.g. 422 invalid input/no knowledge, 503 unconfigured provider. |
| `SupportTransportError` | Outcome may be unknown. No automatic retry; preserve the processing key and inspect server state. |
| `SupportJobTimeout` | Polling deadline reached; exposes `job_id` and `last_job`. No automatic cancellation. |
| `SupportJobFailed` | Job ended failed/cancelled; exposes the complete `job` dictionary. Inspect retained ticket evidence. |
| `SupportProtocolError` | Unexpected JSON or job state; check client/server compatibility. |

All extend `SupportError`. Context-manager exit closes SDK-owned connections. An injected `httpx.Client` remains caller-owned. The SDK does not accept provider keys, follow redirects, log document contents, or hide retry attempts.

## Runnable example

The example makes drafting and review separate commands. Supply real local knowledge and a ticket body file:

```sh
uv run python examples/support_sdk.py draft \
  --document product-guide.md --title "Reset email has not arrived" \
  --body-file ticket.txt --external-id helpdesk-1042 \
  --idempotency-key YOUR_SAVED_UUID

uv run python examples/support_sdk.py show TICKET_UUID

# Only after reviewing the displayed evidence and revision:
uv run python examples/support_sdk.py review TICKET_UUID \
  --decision approve --expected-revision 3 \
  --reply-file reviewed-reply.txt --output approved-ticket.json
```

Use `review --decision escalate --note "..."` for an explicit handoff, `cancel JOB_UUID` to request cancellation, or `export TICKET_UUID --output new-export.json` to re-export an already reviewed ticket. Exports refuse to overwrite an existing file. `--base-url` goes before the subcommand when connecting to a different server.
