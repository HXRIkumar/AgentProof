"""SDK contract checks with mock HTTP only; no worker, model, keys or network."""

import base64
import json

import httpx
import pytest

from agentproof import client as module
from agentproof.client import (
    MAX_FILE_BYTES,
    SupportClient,
    SupportConflictError,
    SupportError,
    SupportJobFailed,
    SupportJobTimeout,
    SupportProtocolError,
    SupportTransportError,
)

TICKET = "12345678123456781234567812345678"
JOB = "abcdefab-cdef-abcd-efab-cdefabcdefab"
DOCUMENT = "87654321876543218765432187654321"


def test_document_ticket_job_flow_never_reviews_or_exports_implicitly(tmp_path):
    document = tmp_path / "guide.md"
    document.write_text("# Account access\nUse the password reset link.")
    seen = []
    states = iter(["queued", "running", "completed"])

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, path, body))
        if path.endswith("/documents"):
            assert base64.b64decode(body["content_base64"]) == document.read_bytes()
            return httpx.Response(201, json={"id": DOCUMENT, "version": 1})
        if path.endswith("/tickets/import"):
            assert body["filename"] == "tickets.csv"
            return httpx.Response(200, json={"tickets": [], "created_count": 0, "duplicate_count": 0})
        if path.endswith("/process"):
            assert body == {"strategy": "adaptive", "idempotency_key": "caller-saved-request-1"}
            return httpx.Response(200, json={"id": JOB, "status": "queued"})
        if "/jobs/" in path:
            return httpx.Response(200, json={"id": JOB, "status": next(states)})
        if request.method == "POST":
            assert body["external_id"] == "source-1042"
            return httpx.Response(201, json={"id": TICKET, "status": "open", "revision": 1})
        return httpx.Response(200, json={"id": TICKET, "status": "review", "revision": 3,
                                       "result": {"data": {"next_action": "reply"}}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with SupportClient(http_client=transport) as client:
            assert client.upload_document(document)["id"] == DOCUMENT
            client.import_tickets_bytes("tickets.csv", b"title,body,external_id\n")
            ticket = client.create_ticket("Reset help", "Email missing", external_id="source-1042")
            job = client.process_ticket(ticket["id"], idempotency_key="caller-saved-request-1")
            assert client.wait_for_job(job["id"], poll_interval=.001)["status"] == "completed"
            assert client.get_ticket(TICKET)["status"] == "review"
        assert not transport.is_closed
        with pytest.raises(SupportError, match="closed"):
            client.get_config()
    assert not any("review" in path or "export" in path for _, path, _ in seen)
    assert seen[3][1] == f"/api/support/tickets/{TICKET}/process"  # hex UUID preserved


def test_process_transport_failure_is_one_request_and_retry_keeps_explicit_key():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            raise httpx.ReadTimeout("private-transport-detail", request=request)
        return httpx.Response(200, json={"id": JOB, "status": "queued"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        SupportClient(http_client=transport) as client,
    ):
        key = client.new_idempotency_key()
        with pytest.raises(SupportTransportError) as failure:
            client.process_ticket(TICKET, idempotency_key=key)
        assert len(seen) == 1 and "private-transport-detail" not in str(failure.value)
        client.process_ticket(TICKET, idempotency_key=key)  # Deliberate caller retry
    assert seen[0] == seen[1]


def test_review_requires_explicit_revision_and_conflict_does_not_export():
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(409, json={"detail": "Knowledge changed; process the ticket again"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        SupportClient(http_client=transport) as client,
    ):
        with pytest.raises(ValueError):
            client.review_ticket(TICKET, decision="approve", expected_revision=True)
        assert not seen
        with pytest.raises(SupportConflictError) as failure:
            client.review_ticket(TICKET, decision="approve", expected_revision=3,
                                 reply="Human-edited response", note="Checked source")
    assert failure.value.status_code == 409 and len(seen) == 1
    assert seen[0][1]["expected_revision"] == 3
    assert seen[0][1]["reply"] == "Human-edited response"


def test_poll_timeout_does_not_cancel_until_explicit_request(monkeypatch):
    now, seen = [0.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": JOB, "status": "cancelled" if request.method == "POST" else "queued"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        SupportClient(http_client=transport) as client,
    ):
        with pytest.raises(SupportJobTimeout) as failure:
            client.wait_for_job(JOB, timeout=.15, poll_interval=.1)
        assert failure.value.job_id == JOB and failure.value.last_job["status"] == "queued"
        assert [r.method for r in seen] == ["GET", "GET"]
        assert all(r.extensions["timeout"]["read"] <= .15 for r in seen)
        assert client.cancel_job(JOB)["status"] == "cancelled"
    assert seen[-1].url.path.endswith("/cancel")


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_job_failure_retains_actual_job(status):
    job = {"id": JOB, "status": status, "error": "Retained safe worker reason"}
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=job))) as transport,
        SupportClient(http_client=transport) as client,
        pytest.raises(SupportJobFailed) as failure,
    ):
        client.wait_for_job(JOB)
    assert failure.value.job == job


def test_bounded_uploads_and_malformed_responses_do_not_expose_body(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text="private unexpected response body")

    oversized = tmp_path / "large.txt"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_FILE_BYTES + 1)
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        SupportClient(http_client=transport) as client,
    ):
        with pytest.raises(ValueError, match="5 MiB"):
            client.upload_document(oversized)
        assert not seen
        with pytest.raises(SupportProtocolError) as failure:
            client.get_config()
        assert "private unexpected" not in str(failure.value)


def test_owned_client_closes_and_redirect_is_not_followed():
    client = SupportClient()
    client.close()
    assert client._http.is_closed
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://example.invalid/elsewhere"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as transport,
        SupportClient(http_client=transport) as api,
        pytest.raises(module.SupportAPIError) as failure,
    ):
        api.get_config()
    assert failure.value.status_code == 307 and len(seen) == 1
