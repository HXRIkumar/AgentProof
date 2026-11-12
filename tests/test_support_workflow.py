"""Product workflow contracts with a controlled inference adapter; no model/API calls."""

import base64
import io
import json
import threading
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentproof.support import SupportError, SupportService, create_router


def content(text):
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


class ControlledAnswers:
    embedder = None

    def __init__(self, *, block=False, ticket_only=False):
        self.calls = []
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()
        self.ticket_only = ticket_only

    def public_config(self):
        return {
            "configured": True,
            "model": "controlled-test",
            "critic_model": "controlled-test",
            "embedding_status": "unavailable",
        }

    def run(self, request):
        self.calls.append(request)
        self.entered.set()
        if self.block:
            assert self.release.wait(3), "Test did not release inference"
        source = next(
            s for s in request.sources if s.id.startswith("ticket-" if self.ticket_only else "kb-")
        )
        return {
            "id": str(uuid.uuid4()),
            "status": "accepted",
            "data": {
                "summary": "Customer asks how to export records",
                "category": "technical",
                "priority": "normal",
                "next_action": "reply",
                "draft_reply": "Open Settings and choose Export.",
                "follow_up_question": "",
            },
            "citations": [{"source_id": source.id, "quote": source.text}],
            "attempts": [],
            "usage": {"calls": 1, "total_tokens": 25},
        }


def setup(tmp_path, **options):
    answers = ControlledAnswers(**options)
    service = SupportService(tmp_path / "support.sqlite3", answers)
    document = service.add_document(
        "manual.md",
        content(
            "To export your records, open Settings and choose Export. Downloads use CSV format."
        ),
    )
    ticket = service.add_ticket(
        {"title": "Export records", "body": "How can I export my records?", "external_id": "demo-1"}
    )
    return service, answers, document, ticket


def queued(service, ticket, key="job-1"):
    return service.process(ticket["id"], {"idempotency_key": key})


def wait_terminal(service, job):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = service.job(job["id"])
        if value["status"] not in {"queued", "running"}:
            return value
        time.sleep(0.01)
    raise AssertionError("Worker did not finish")


def test_persistent_knowledge_ticket_idempotency_and_atomic_import(tmp_path):
    service, answers, document, ticket = setup(tmp_path)
    assert (
        service.add_document(
            "manual.md",
            content(
                "To export your records, open Settings and choose Export. Downloads use CSV format."
            ),
        )["id"]
        == document["id"]
    )
    assert (
        service.add_ticket(
            {"title": ticket["title"], "body": ticket["body"], "external_id": "demo-1"}
        )["id"]
        == ticket["id"]
    )
    with pytest.raises(SupportError, match="different content"):
        service.add_ticket({"title": "Changed", "body": "Different", "external_id": "demo-1"})
    updated = service.add_document(
        "manual.md", content("The revised export procedure uses Account > Download.")
    )
    assert updated["version"] == 2 and updated["id"] != document["id"]
    assert service.document(document["id"])["active"] is False
    assert "Settings" in service.document(document["id"])["text"]
    csv = (
        "subject,description,external_id\nNew request,Please help,new-1\nChanged,Different,demo-1\n"
    )
    with pytest.raises(SupportError):
        service.import_tickets("tickets.csv", content(csv))
    assert len(service.tickets()) == 1  # conflict rolls back the earlier valid row
    with pytest.raises(SupportError, match="50"):
        service.import_tickets(
            "tickets.json", content(json.dumps([{"title": "A", "body": "B"}] * 51))
        )
    with pytest.raises(SupportError, match="1 MiB"):
        service.import_tickets("oversized.json", content(b" " * (1024 * 1024 + 1)))
    result = service.import_tickets(
        "tickets.csv", content("title,body,external_id\nNew request,Please help,new-1\n")
    )
    assert result["created_count"] == 1
    assert (
        service.import_tickets(
            "tickets.csv", content("title,body,external_id\nNew request,Please help,new-1\n")
        )["duplicate_count"]
        == 1
    )
    reloaded = SupportService(service.store.path, answers)
    assert len(reloaded.tickets()) == 2 and reloaded.documents()[0]["version"] == 2
    assert not answers.calls


def test_document_snapshot_worker_review_and_export_guard(tmp_path):
    service, answers, document, ticket = setup(tmp_path)
    job = queued(service, ticket)
    assert queued(service, ticket)["id"] == job["id"]
    with pytest.raises(SupportError, match="different processing"):
        service.process(ticket["id"], {"idempotency_key": "job-1", "strategy": "baseline"})
    with pytest.raises(SupportError, match="active job"):
        queued(service, ticket, "other-key")
    service.add_document(
        "manual.md", content("New knowledge requires a completely different workflow.")
    )
    service.start()
    try:
        assert wait_terminal(service, job)["status"] == "completed"
        detail = service.ticket(ticket["id"])
        assert detail["status"] == "review" and detail["review"] is None
        assert detail["result"]["stale"]
        assert detail["result"]["sources"][1]["document_id"] == document["id"]
        assert "Settings" in answers.calls[0].sources[1].text
        with pytest.raises(SupportError, match="Knowledge changed"):
            service.review(
                ticket["id"], {"decision": "approve", "expected_revision": detail["revision"]}
            )
        retry = queued(service, ticket, "new-snapshot")
        assert wait_terminal(service, retry)["status"] == "completed"
        current = service.ticket(ticket["id"])
        with pytest.raises(SupportError, match="refresh"):
            service.review(ticket["id"], {"decision": "approve", "expected_revision": 1})
        approved = service.review(
            ticket["id"],
            {
                "decision": "approve",
                "expected_revision": current["revision"],
                "reply": "A human reviewed this response.",
            },
        )
        assert approved["result"]["data"]["draft_reply"] == "Open Settings and choose Export."
        assert approved["review"]["reply"] == "A human reviewed this response."
        exported = service.export(ticket["id"])
        assert exported["reply"] == approved["review"]["reply"]
        assert exported["customer_message_sent"] is False
        assert exported["document_versions"][0]["version"] == 2
        service.archive_document(service.documents()[0]["id"])
        with pytest.raises(SupportError, match="Knowledge changed"):
            service.export(ticket["id"])
    finally:
        service.stop()


def test_queued_cancel_restart_and_single_worker_ownership(tmp_path):
    service, answers, _, ticket = setup(tmp_path)
    cancelled = queued(service, ticket)
    assert service.cancel(cancelled["id"])["status"] == "cancelled"
    interrupted = queued(service, ticket, "interrupted")
    with service.store.connect(write=True) as db:
        db.execute("UPDATE support_jobs SET status='running' WHERE id=?", (interrupted["id"],))
    second = service.add_ticket({"title": "Another export", "body": "Where is export?"})
    durable = queued(service, second, "durable")
    reloaded = SupportService(service.store.path, answers)
    assert reloaded.start()
    try:
        assert not service.start()  # another worker owns this database
        assert wait_terminal(reloaded, durable)["status"] == "completed"
        assert reloaded.job(interrupted["id"])["status"] == "failed"
        assert "not retried automatically" in reloaded.job(interrupted["id"])["error"]
        assert len(answers.calls) == 1
    finally:
        reloaded.stop()


def test_running_cancel_retains_actual_result_and_usage(tmp_path):
    service, answers, _, ticket = setup(tmp_path, block=True)
    job = queued(service, ticket)
    service.start()
    try:
        assert answers.entered.wait(2)
        response = service.cancel(job["id"])
        assert response["status"] == "running" and response["cancel_requested"]
        answers.release.set()
        assert wait_terminal(service, job)["status"] == "cancelled"
        detail = service.ticket(ticket["id"])
        assert detail["result"]["answer_run"]["usage"]["calls"] == 1
        with pytest.raises(SupportError, match="Review"):
            service.export(ticket["id"])
        handoff = service.review(
            ticket["id"],
            {
                "decision": "escalate",
                "expected_revision": detail["revision"],
                "note": "Please inspect the retained draft.",
            },
        )
        assert handoff["status"] == "escalated"
        assert service.export(ticket["id"])["reply"] is None
    finally:
        answers.release.set()
        service.stop()


def test_partial_ticket_and_ticket_only_citation_cannot_be_approved(tmp_path):
    service, answers, _, _ticket = setup(tmp_path, ticket_only=True)
    long = service.add_ticket(
        {
            "title": "Refund question",
            "body": "Please refund my payment. " + "Additional customer details. " * 120,
        }
    )
    service.start()
    try:
        job = queued(service, long)
        assert wait_terminal(service, job)["status"] == "completed"
        detail = service.ticket(long["id"])
        assert detail["status"] == "review"  # no autonomous human decision
        assert len(detail["body"]) > detail["result"]["context"]["ticket_characters_used"]
        assert len(detail["result"]["approval_blockers"]) == 3
        with pytest.raises(SupportError, match="knowledge-document"):
            service.review(
                long["id"], {"decision": "approve", "expected_revision": detail["revision"]}
            )
        assert len(answers.calls) == 1
    finally:
        service.stop()


def test_api_upload_validation_pdf_and_human_review_boundary(tmp_path):
    service, answers, document, ticket = setup(tmp_path)
    app = FastAPI()
    app.include_router(create_router(service))
    with TestClient(app) as client:
        assert client.get("/api/support/config").json()["worker_available"] is False
        assert (
            client.post(
                "/api/support/documents",
                json={"filename": "../bad.txt", "content_base64": content("bad")},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/support/documents",
                json={"filename": "bad.pdf", "content_base64": content("not a PDF")},
            ).status_code
            == 422
        )
        from pypdf import PdfWriter

        pdf = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        response = client.post(
            "/api/support/documents",
            json={"filename": "scan.pdf", "content_base64": content(pdf.getvalue())},
        )
        assert response.status_code == 422 and "OCR" in response.json()["detail"]
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        text_pdf = io.BytesIO()
        text_writer = PdfWriter()
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = text_writer._add_object(font)
        for line in ("Settings and Export download CSV.", "Support hours are Monday to Friday."):
            page = text_writer.add_blank_page(width=300, height=300)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 50 250 Td ({line}) Tj ET".encode())
            page[NameObject("/Contents")] = text_writer._add_object(stream)
        text_writer.write(text_pdf)
        upload = client.post(
            "/api/support/documents",
            json={"filename": "guide.pdf", "content_base64": content(text_pdf.getvalue())},
        )
        assert upload.status_code == 201
        assert upload.json()["page_count"] == upload.json()["chunk_count"] == 2
        detail = client.get(f"/api/support/documents/{upload.json()['id']}").json()
        assert [page["page"] for page in detail["pages"]] == [1, 2]
        assert "Settings" in detail["pages"][0]["text"]
        assert "Monday" in detail["pages"][1]["text"]
        assert client.get(f"/api/support/documents/{document['id']}").json()["text"]
        assert client.get(f"/api/support/tickets/{ticket['id']}/export").status_code == 409
        job = client.post(
            f"/api/support/tickets/{ticket['id']}/process", json={"idempotency_key": "api-job"}
        )
        assert job.status_code == 202 and job.json()["status"] == "queued"
        assert (
            client.post(f"/api/support/jobs/{job.json()['id']}/cancel").json()["status"]
            == "cancelled"
        )
        assert not answers.calls
