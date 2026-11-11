"""Independent remote-lab review checks; no models or external endpoints."""

import contextlib
import importlib.util
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from agentproof.remote_client import RemoteRefundClient
from agentproof.remote_service import RefundRequest, request_hash

SPEC = importlib.util.spec_from_file_location(
    "remote_lab_review", Path(__file__).resolve().parents[1] / "scripts" / "remote_lab.py"
)
LAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAB)


def refund_request(amount=3100):
    return RefundRequest(
        order_id="ORD-100", customer_id="CUS-17", amount_cents=amount, policy_version="refund-v1"
    )


@contextlib.contextmanager
def response_server(payload):
    """Serve a supplied response through an actual numeric-loopback socket."""
    events = []
    encoded = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self):
            if self.command == "POST":
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
            events.append((self.command, self.path, self.headers.get("Idempotency-Key")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(encoded)

        do_GET = respond
        do_POST = respond

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", events
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize("requested,malformed", [(3100, 3100.0), (1, True)])
def test_review_malformed_money_receipt_is_not_accepted(requested, malformed):
    request = refund_request(requested)
    key = "review-strict-receipt"
    receipt = {
        **request.model_dump(),
        "amount_cents": malformed,
        "operation_key": key,
        "request_hash": request_hash(request),
        "status": "committed",
        "effect_id": "synthetic-review-effect",
        "created_at": "2026-11-12T00:00:00+00:00",
    }
    with response_server(receipt) as (base_url, _events):
        result = RemoteRefundClient(base_url, max_attempts=1).refund(key, request)
    assert result.outcome not in {"committed", "reconciled"}
    assert result.receipt is None


def test_review_interrupted_startup_does_not_leak_child_or_log(tmp_path, monkeypatch):
    service = LAB.ServiceProcess(tmp_path / "startup-interrupted")
    actual_clock = LAB.time.monotonic
    calls = 0

    def interrupt_after_spawn():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("independent review startup interruption")
        return actual_clock()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(LAB.time, "monotonic", interrupt_after_spawn)
            with pytest.raises(KeyboardInterrupt):
                service.__enter__()
        assert service.process.poll() is not None, "startup exception leaked a live child"
        assert service.log.closed, "startup exception leaked the log handle"
    finally:
        # Always clean up the process this test created, including on a regression.
        service.__exit__(None, None, None)


def test_review_concurrent_same_key_conflicting_arguments_commit_one_winner(tmp_path):
    barrier = threading.Barrier(2)
    with LAB.ServiceProcess(tmp_path / "conflicting-concurrency") as service:

        def submit(amount):
            barrier.wait(timeout=3)
            return RemoteRefundClient(service.base_url).refund(
                "review-shared-key", refund_request(amount)
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, (1700, 2300)))
        assert sorted(result.outcome for result in results) == ["committed", "conflict"]
        winner = next(result for result in results if result.outcome == "committed")
        evidence = LAB.ledger(service.database)
        assert evidence["effect_count"] == 1
        assert evidence["total_cents"] == winner.receipt["amount_cents"]
        assert evidence["effects"][0]["effect_id"] == winner.receipt["effect_id"]
        assert evidence["operations"] == [
            {"operation_key": "review-shared-key", "request_hash": winner.receipt["request_hash"]}
        ]


def test_review_hard_kill_after_lost_commit_preserves_receipt_and_ledger(tmp_path):
    directory = tmp_path / "hard-kill-restart"
    request = refund_request(2200)
    key = "review-kill-restart"
    with LAB.ServiceProcess(directory, drop=1) as first:
        with pytest.raises(httpx.HTTPError):
            httpx.post(
                first.base_url + "/refunds",
                json=request.model_dump(),
                headers={"Idempotency-Key": key},
                timeout=2,
                trust_env=False,
            )
        before = LAB.ledger(first.database)
        with sqlite3.connect(first.database) as db:
            stored_receipt = json.loads(
                db.execute("SELECT receipt FROM operations WHERE operation_key=?", (key,)).fetchone()[0]
            )
        first_pid = first.pid
        first.process.kill()
        first.process.wait(timeout=5)
    with LAB.ServiceProcess(directory) as restarted:
        result = RemoteRefundClient(restarted.base_url).refund(key, request)
        after = LAB.ledger(restarted.database)
        assert restarted.pid != first_pid
        assert result.outcome == "committed"
        assert result.receipt == stored_receipt
        assert before == after
        assert after["effect_count"] == 1
        assert after["total_cents"] == 2200


def test_review_oversized_responses_exhaust_attempts_without_changing_key():
    key = "review-response-limit"
    with response_server({"padding": "x" * 17000}) as (base_url, events):
        result = RemoteRefundClient(base_url, max_attempts=3).refund(key, refund_request())
    assert result.outcome == "unresolved"
    assert result.reason == "effect_state_unknown"
    assert result.receipt is None
    assert [event[0] for event in events] == ["POST", "GET"] * 3
    assert {event[2] for event in events if event[0] == "POST"} == {key}
    assert {event[1] for event in events if event[0] == "GET"} == {"/operations/" + key}
    assert {event["operation_key"] for event in result.events} == {key}
