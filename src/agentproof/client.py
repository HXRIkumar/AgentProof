"""Small synchronous client for the local SupportDesk workflow.

The client returns the API's dictionaries/lists without duplicating server models.
It never retries a mutation, approves a draft, or contacts a model provider itself.
"""

from __future__ import annotations

import base64
import math
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_IMPORT_BYTES = 1024 * 1024
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}


class SupportError(Exception):
    """Base exception for SupportDesk client failures."""


class SupportAPIError(SupportError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Support API HTTP {status_code}: {detail}")


class SupportConflictError(SupportAPIError):
    """A revision, idempotency key, or workflow state conflicts with the request."""


class SupportTransportError(SupportError):
    """The request outcome may be unknown; the client did not retry it."""


class SupportProtocolError(SupportError):
    """The server response does not match the documented JSON contract."""


class SupportJobTimeout(SupportError):
    def __init__(self, job_id: str, last_job: dict | None):
        self.job_id = job_id
        self.last_job = last_job
        super().__init__(f"Timed out waiting for job {job_id}; the server job was not cancelled")


class SupportJobFailed(SupportError):
    def __init__(self, job: dict):
        self.job = job
        super().__init__(f"Job {job.get('id')} ended with status {job.get('status')}; inspect the retained job and ticket")


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def _identifier(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected a server UUID string")
    try:
        UUID(value)
        return value
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Expected a server UUID") from None


def _file_content(path: str | Path, *, max_bytes=MAX_FILE_BYTES) -> tuple[str, bytes]:
    path = Path(path)
    with path.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"File must not exceed {max_bytes // (1024 * 1024)} MiB")
    return path.name, content


def _upload(filename: str, content: bytes, *, max_bytes=MAX_FILE_BYTES) -> dict:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A filename is required")
    if not isinstance(content, bytes):
        raise TypeError("File content must be bytes")
    if len(content) > max_bytes:
        raise ValueError(f"File must not exceed {max_bytes // (1024 * 1024)} MiB")
    return {"filename": filename, "content_base64": base64.b64encode(content).decode("ascii")}


class SupportClient:
    """Call a running AgentProof server, usually ``http://127.0.0.1:8010``.

    Use as a context manager. An injected ``http_client`` remains caller-owned.
    No credentials or provider configuration are accepted by this SDK.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8010", *,
                 timeout: float = 30.0, http_client: httpx.Client | None = None):
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or not url.host or url.username or url.password:
            raise ValueError("Use an HTTP(S) SupportDesk server URL without embedded credentials")
        if url.query or url.fragment:
            raise ValueError("The server URL must not include a query or fragment")
        self.base_url = str(url).rstrip("/")
        self.timeout = _positive(timeout, "timeout")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(trust_env=False, follow_redirects=False,
                                               timeout=self.timeout)
        self._closed = False

    def __enter__(self):
        if self._closed:
            raise SupportError("The SupportDesk client is closed")
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        if not self._closed and self._owns_client:
            self._http.close()
        self._closed = True

    @staticmethod
    def new_idempotency_key() -> str:
        """Create once per logical processing request; persist and reuse on retry."""
        return str(uuid4())

    def _request(self, method: str, path: str, *, body=None, timeout=None, expected=dict):
        if self._closed:
            raise SupportError("The SupportDesk client is closed")
        try:
            response = self._http.request(
                method, self.base_url + "/api/support" + path, json=body,
                timeout=self.timeout if timeout is None else timeout, follow_redirects=False,
            )
        except httpx.TransportError:
            raise SupportTransportError(
                "Support API request did not complete; its outcome may be unknown. "
                "No retry was made. Reuse the same processing idempotency key when retrying."
            ) from None
        if response.status_code >= 300:
            detail = "Request failed; inspect server workflow state before retrying"
            try:
                value = response.json().get("detail")
                if isinstance(value, str):
                    detail = value[:500]
            except (ValueError, AttributeError):
                pass
            error = SupportConflictError if response.status_code == 409 else SupportAPIError
            raise error(response.status_code, detail)
        if response.status_code == 204 and expected is None:
            return None
        try:
            result = response.json()
        except ValueError:
            raise SupportProtocolError("Support API returned an invalid JSON response") from None
        if expected is not None and not isinstance(result, expected):
            raise SupportProtocolError("Support API returned an unexpected JSON shape")
        return result

    def get_config(self) -> dict:
        return self._request("GET", "/config")

    def list_documents(self) -> list[dict]:
        return self._request("GET", "/documents", expected=list)

    def upload_document(self, path: str | Path) -> dict:
        """Upload a TXT, Markdown or text PDF. PDF extraction happens on the server."""
        return self.upload_document_bytes(*_file_content(path))

    def upload_document_bytes(self, filename: str, content: bytes) -> dict:
        return self._request("POST", "/documents", body=_upload(filename, content))

    def get_document(self, document_id: str) -> dict:
        return self._request("GET", "/documents/" + _identifier(document_id))

    def archive_document(self, document_id: str) -> dict | None:
        """Archive active knowledge; historical citation versions remain readable."""
        return self._request("DELETE", "/documents/" + _identifier(document_id), expected=None)

    def list_tickets(self) -> list[dict]:
        return self._request("GET", "/tickets", expected=list)

    def create_ticket(self, title: str, body: str, *, external_id: str | None = None) -> dict:
        payload = {"title": title, "body": body}
        if external_id is not None:
            payload["external_id"] = external_id
        return self._request("POST", "/tickets", body=payload)

    def import_tickets(self, path: str | Path) -> dict:
        """Import CSV/JSON up to 1 MiB; the server validates at most 50 rows atomically."""
        return self.import_tickets_bytes(*_file_content(path, max_bytes=MAX_IMPORT_BYTES))

    def import_tickets_bytes(self, filename: str, content: bytes) -> dict:
        return self._request("POST", "/tickets/import",
                             body=_upload(filename, content, max_bytes=MAX_IMPORT_BYTES))

    def get_ticket(self, ticket_id: str) -> dict:
        return self._request("GET", "/tickets/" + _identifier(ticket_id))

    def process_ticket(self, ticket_id: str, *, idempotency_key: str,
                       strategy: str = "adaptive") -> dict:
        """Enqueue once. Retrying deliberately requires the SAME caller-retained key."""
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("A stable idempotency_key is required")
        if strategy not in {"baseline", "validated", "adaptive"}:
            raise ValueError("Unknown processing strategy")
        return self._request("POST", f"/tickets/{_identifier(ticket_id)}/process",
                             body={"strategy": strategy, "idempotency_key": idempotency_key})

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", "/jobs/" + _identifier(job_id))

    def cancel_job(self, job_id: str) -> dict:
        """Request cancellation; an active provider request is allowed to finish."""
        return self._request("POST", f"/jobs/{_identifier(job_id)}/cancel")

    def wait_for_job(self, job_id: str, *, timeout: float = 180.0,
                     poll_interval: float = 0.5) -> dict:
        """Poll until complete. Timeout does not cancel; failed/cancelled jobs raise."""
        job_id = _identifier(job_id)
        deadline = time.monotonic() + _positive(timeout, "timeout")
        interval = _positive(poll_interval, "poll_interval")
        latest = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SupportJobTimeout(job_id, latest)
            latest = self._request("GET", f"/jobs/{job_id}", timeout=min(self.timeout, remaining))
            status = latest.get("status")
            if status in TERMINAL_JOB_STATES:
                if status != "completed":
                    raise SupportJobFailed(latest)
                return latest
            if status not in {"queued", "running"}:
                raise SupportProtocolError("Support API returned an unknown job status")
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def review_ticket(self, ticket_id: str, *, decision: str, expected_revision: int,
                      reply: str | None = None, note: str | None = None) -> dict:
        if decision not in {"approve", "escalate"}:
            raise ValueError("Review decision must be approve or escalate")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        payload = {"decision": decision, "expected_revision": expected_revision}
        if reply is not None:
            payload["reply"] = reply
        if note is not None:
            payload["note"] = note
        return self._request("POST", f"/tickets/{_identifier(ticket_id)}/review", body=payload)

    def export_ticket(self, ticket_id: str) -> dict:
        """Export an explicitly reviewed reply or escalation; server rejects unreviewed drafts."""
        return self._request("GET", f"/tickets/{_identifier(ticket_id)}/export")
