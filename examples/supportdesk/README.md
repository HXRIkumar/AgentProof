# Try the complete support workflow

Harbor API is a fictional product used for this example. These documents and
tickets are authored sample inputs, not customer work or measured business outcomes.
The application also accepts your own TXT/Markdown/PDF documents and CSV/JSON tickets.

1. In **Knowledge**, upload the four Markdown documents in `knowledge/`.
2. Import `tickets.csv` in **Work queue**.
3. Process a ticket and inspect its draft, cited document versions, and model trace.
4. Review the draft: approve a supported reply or escalate with a handoff note.
5. Export the reviewed result for an application or another support operator.

Expected business behavior for a human reviewer:

- Expired invitation: explain the documented 72-hour expiry and ask a workspace
  admin to issue a fresh invitation. Do not request passwords or security codes.
- Webhook 401: explain signature verification and that401 is not retried. Do not
  claim to have inspected the customer's endpoint or account.
- Refund request: escalate to billing; no promise of a refund, amount or timeline.
- Vague failure report: ask for the product action, error and approximate time;
  do not diagnose an outage or classify an unconfirmed issue as a major incident.

These expectations are a demonstration checklist, not benchmark scores. Actual
model outputs may fail; the UI must preserve and surface those failures.

To demonstrate stale-source handling, generate an invitation reply, then change
the invitation-expiry policy and upload the updated file with the same filename.
The draft should show an outdated-knowledge warning and require regeneration
before approval. Existing source versions and model outputs remain inspectable.

Nothing here sends email, changes customer accounts, retries real webhooks, or
issues payments. Export is the explicit handoff boundary. The Python SDK example
shows how another application can submit and inspect the same work.
