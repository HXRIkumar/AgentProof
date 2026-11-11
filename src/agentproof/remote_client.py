"""Bounded localhost refund client that preserves operation identity on ambiguity."""

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import Field

from .remote_service import KEY_PATTERN, RefundRequest, request_hash


class RefundReceipt(RefundRequest):
    """The remote wire contract is strict before any equality comparisons."""

    operation_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["committed"]
    effect_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(min_length=1, max_length=64)


@dataclass
class RefundResult:
    outcome: str
    operation_key: str
    receipt: dict | None = None
    reason: str | None = None
    events: list[dict] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


class RemoteRefundClient:
    """No background requests and no automatic new key after an ambiguous response.

    A 404 reconciliation lookup is a point-in-time absence, not proof that a
    previously sent request cannot still commit. Exhaustion returns unresolved.
    """

    def __init__(self, base_url, *, timeout=1.0, max_attempts=2):
        try:
            parsed = urlparse(base_url)
            port = parsed.port
        except ValueError:
            raise ValueError("Use a numeric loopback HTTP service URL") from None
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not port
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Use http://127.0.0.1:PORT with no credentials or path")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be an integer between 1 and 3")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError("timeout must be finite and between 0 and 10 seconds")
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.timeout = timeout

    @staticmethod
    def _read(client, method, path, **kwargs):
        with client.stream(method, path, **kwargs) as response:
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Unexpected response encoding")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=4096):
                if len(data) + len(chunk) > 16_384:
                    raise ValueError("Response exceeds integration fixture limit")
                data.extend(chunk)
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise TypeError("Expected an object response")
            return response.status_code, payload

    @staticmethod
    def _matching_receipt(receipt: RefundReceipt, key, request):
        return (
            receipt.operation_key == key
            and receipt.request_hash == request_hash(request)
            and all(getattr(receipt, k) == v for k, v in request.model_dump().items())
        )

    def refund(self, key: str, request: RefundRequest) -> RefundResult:
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("Invalid operation key")
        if not isinstance(request, RefundRequest):
            raise TypeError("request must be a validated RefundRequest")
        events = []
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=False,
            headers={"Accept-Encoding": "identity"},
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    status, body = self._read(
                        client,
                        "POST",
                        "/refunds",
                        headers={"Idempotency-Key": key},
                        json=request.model_dump(),
                    )
                    events.append(
                        {
                            "method": "POST",
                            "attempt": attempt,
                            "status": status,
                            "operation_key": key,
                        }
                    )
                    if status in (200, 201):
                        receipt = RefundReceipt.model_validate(body)
                        if self._matching_receipt(receipt, key, request):
                            return RefundResult(
                                "committed", key, receipt.model_dump(), events=events
                            )
                    if 400 <= status < 500:
                        outcome = (
                            "conflict" if body.get("code") == "idempotency_conflict" else "rejected"
                        )
                        return RefundResult(
                            outcome, key, reason=body.get("code", "request_rejected"), events=events
                        )
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    events.append(
                        {
                            "method": "POST",
                            "attempt": attempt,
                            "error": type(exc).__name__,
                            "operation_key": key,
                        }
                    )
                # A transport/server/malformed-response failure says nothing about the effect.
                try:
                    status, body = self._read(client, "GET", "/operations/" + key)
                    events.append(
                        {
                            "method": "GET",
                            "attempt": attempt,
                            "status": status,
                            "operation_key": key,
                        }
                    )
                    if status == 200:
                        # A malformed receipt leaves the effect unknown. Only a well-typed
                        # authoritative receipt can establish either success or a conflict.
                        receipt = RefundReceipt.model_validate(body)
                        if self._matching_receipt(receipt, key, request):
                            return RefundResult(
                                "reconciled", key, receipt.model_dump(), events=events
                            )
                        return RefundResult(
                            "conflict", key, reason="receipt_arguments_mismatch", events=events
                        )
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    events.append(
                        {
                            "method": "GET",
                            "attempt": attempt,
                            "error": type(exc).__name__,
                            "operation_key": key,
                        }
                    )
        return RefundResult("unresolved", key, reason="effect_state_unknown", events=events)
