#!/usr/bin/env python3
"""Upload knowledge and draft a ticket; review/export are separate explicit commands."""

import argparse
import json
import sys
from pathlib import Path

from agentproof.client import SupportClient, SupportError


def show(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    actions = parser.add_subparsers(dest="action", required=True)
    draft = actions.add_parser("draft", help="Upload a document, create a ticket and wait for its draft")
    draft.add_argument("--document", required=True, type=Path)
    draft.add_argument("--title", required=True)
    draft.add_argument("--body-file", required=True, type=Path)
    draft.add_argument("--external-id", required=True, help="Stable ID from your source system")
    draft.add_argument("--idempotency-key", required=True, help="Create once with uuid.uuid4(); reuse if retrying")
    draft.add_argument("--strategy", choices=("adaptive", "validated", "baseline"), default="adaptive")
    draft.add_argument("--wait-seconds", type=float, default=180)
    inspect = actions.add_parser("show", help="Read the ticket, citations, immutable output and current revision")
    inspect.add_argument("ticket_id")
    cancel = actions.add_parser("cancel", help="Cancel queued work or request cancellation after current inference")
    cancel.add_argument("job_id")
    review = actions.add_parser("review", help="Record an explicit human decision, then export locally")
    review.add_argument("ticket_id")
    review.add_argument("--decision", required=True, choices=("approve", "escalate"))
    review.add_argument("--expected-revision", required=True, type=int,
                        help="Revision you actually reviewed; stale reviews are rejected")
    review.add_argument("--reply-file", type=Path, help="Optional human-edited reply")
    review.add_argument("--note")
    review.add_argument("--output", required=True, type=Path, help="New local JSON file; existing files are preserved")
    export = actions.add_parser("export", help="Re-export an already reviewed ticket without changing its decision")
    export.add_argument("ticket_id")
    export.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action in {"review", "export"}:
        if args.output.exists():
            parser.error("Output exists; choose a new path")
        if not args.output.parent.is_dir():
            parser.error("Output parent directory does not exist")
    with SupportClient(args.base_url) as client:
        if args.action == "draft":
            body = args.body_file.read_text(encoding="utf-8")
            document = client.upload_document(args.document)
            ticket = client.create_ticket(args.title, body, external_id=args.external_id)
            # Emit identifiers before waiting so a client timeout does not lose the work.
            show({"document_id": document["id"], "ticket_id": ticket["id"],
                  "idempotency_key": args.idempotency_key})
            job = client.process_ticket(ticket["id"], idempotency_key=args.idempotency_key,
                                        strategy=args.strategy)
            show({"job_id": job["id"], "status": job["status"]})
            client.wait_for_job(job["id"], timeout=args.wait_seconds)
            show(client.get_ticket(ticket["id"]))
            print("Draft only. Read its evidence, then use the separate review command.")
        elif args.action == "show":
            show(client.get_ticket(args.ticket_id))
        elif args.action == "cancel":
            show(client.cancel_job(args.job_id))
        else:
            if args.action == "review":
                reply = args.reply_file.read_text(encoding="utf-8") if args.reply_file else None
                client.review_ticket(args.ticket_id, decision=args.decision,
                                     expected_revision=args.expected_revision, reply=reply, note=args.note)
            exported = client.export_ticket(args.ticket_id)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(exported, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            print(f"Saved reviewed export to {args.output}. No customer message was sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SupportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
