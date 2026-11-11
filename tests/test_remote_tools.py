"""Actual subprocess/socket tests; assertions independently read the service database."""

import importlib.util
import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from agentproof.remote_client import RemoteRefundClient
from agentproof.remote_service import MAX_BODY_BYTES, RefundRequest

SPEC = importlib.util.spec_from_file_location(
    "remote_lab", Path(__file__).resolve().parents[1] / "scripts" / "remote_lab.py"
)
LAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAB)


@pytest.fixture
def request_data():
    return RefundRequest(
        order_id="ORD-100", customer_id="CUS-17", amount_cents=3100, policy_version="refund-v1"
    )


def test_complete_actual_process_lab(tmp_path):
    report = LAB.run_lab(tmp_path / "lab")
    assert report["passed"]
    assert len(report["cases"]) == 6
    assert report["model_calls"] == 0
    assert all(pid != report["client_pid"] for c in report["cases"] for pid in c["service_pids"])
    with pytest.raises(FileExistsError):
        LAB.run_lab(tmp_path / "lab")


@pytest.mark.parametrize(
    "changed,code",
    [
        ({"customer_id": "CUS-OTHER"}, "customer_mismatch"),
        ({"order_id": "MISSING"}, "order_not_found"),
        ({"order_id": "ORD-OLD"}, "ineligible_order"),
        ({"order_id": "ORD-PROCESS"}, "ineligible_order"),
        ({"policy_version": "refund-v0"}, "stale_policy"),
        ({"amount_cents": 9999}, "insufficient_balance"),
        ({"order_id": "ORD-HIGH", "amount_cents": 10001}, "approval_required"),
    ],
)
def test_authoritative_remote_policy_has_zero_effect(tmp_path, request_data, changed, code):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        request = RefundRequest.model_validate({**request_data.model_dump(), **changed})
        result = RemoteRefundClient(service.base_url).refund("policy-check", request)
        assert result.outcome == "rejected"
        assert result.reason == code
        assert LAB.ledger(service.database)["effect_count"] == 0


@pytest.mark.parametrize(
    "changed",
    [
        {"amount_cents": True},
        {"amount_cents": "3100"},
        {"amount_cents": 3.5},
        {"amount_cents": -1},
        {"amount_cents": 1_000_001},
        {"order_id": "x" * 65},
        {"order_id": "../path"},
        {"approved": True},
    ],
)
def test_invalid_payload_rejected_over_actual_http(tmp_path, request_data, changed):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        response = httpx.post(
            service.base_url + "/refunds",
            json={**request_data.model_dump(), **changed},
            headers={"Idempotency-Key": "typed-check"},
            trust_env=False,
        )
        assert response.status_code == 422
        assert LAB.ledger(service.database)["effect_count"] == 0


def test_actual_body_and_host_limits(tmp_path, request_data):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        response = httpx.post(
            service.base_url + "/refunds",
            content=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Idempotency-Key": "body-limit", "Content-Type": "application/json"},
            trust_env=False,
        )
        assert response.status_code == 413
        response = httpx.post(
            service.base_url + "/refunds",
            json=request_data.model_dump(),
            headers={"Idempotency-Key": "host-check", "Host": "example.com"},
            trust_env=False,
        )
        assert response.status_code == 400
        assert LAB.ledger(service.database)["effect_count"] == 0


def test_chunked_request_rejected_without_mutation(tmp_path):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        port = int(service.base_url.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(
                (
                    f"POST /refunds HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                    "Idempotency-Key: chunked\r\nContent-Type: application/json\r\n"
                    "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
                ).encode()
            )
            assert b"400 Bad Request" in connection.recv(2048)
        assert LAB.ledger(service.database)["effect_count"] == 0


def test_concurrent_different_keys_cannot_overspend(tmp_path, request_data):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        request = request_data.model_copy(update={"amount_cents": 6000})

        def submit(key):
            return RemoteRefundClient(service.base_url).refund(key, request)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, ["different-a", "different-b"]))
        assert sorted(r.outcome for r in results) == ["committed", "rejected"]
        evidence = LAB.ledger(service.database)
        assert evidence["effect_count"] == 1
        assert evidence["total_cents"] == 6000


def test_second_same_key_attempt_after_hidden_receipt_reuses_identity(tmp_path, request_data):
    with LAB.ServiceProcess(tmp_path / "service", drop=1, hide=True) as service:
        result = RemoteRefundClient(service.base_url, max_attempts=2).refund(
            "retry-key", request_data
        )
        assert result.outcome == "committed"
        assert [e["method"] for e in result.events] == ["POST", "GET", "POST"]
        assert {e["operation_key"] for e in result.events} == {"retry-key"}
        assert LAB.ledger(service.database)["effect_count"] == 1


def test_server_unavailable_is_unresolved_and_bounded(tmp_path, request_data):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        url, database = service.base_url, service.database
    result = RemoteRefundClient(url, timeout=0.1, max_attempts=2).refund(
        "unavailable", request_data
    )
    assert result.outcome == "unresolved"
    assert result.reason == "effect_state_unknown"
    assert [e["method"] for e in result.events] == ["POST", "GET", "POST", "GET"]
    assert LAB.ledger(database)["effect_count"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://example.com:8000",
        "http://127.0.0.1:0",
        "http://user:secret@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000?x=1",
        "http://127.0.0.1:8000#fragment",
    ],
)
def test_non_loopback_or_ambiguous_url_refused(url):
    with pytest.raises(ValueError):
        RemoteRefundClient(url)


@pytest.mark.parametrize("attempts", [0, 4, True, 1.5])
def test_attempt_budget_strict(attempts):
    with pytest.raises(ValueError):
        RemoteRefundClient("http://127.0.0.1:8000", max_attempts=attempts)


def test_database_constraints_and_receipts_match_effects(tmp_path, request_data):
    with LAB.ServiceProcess(tmp_path / "service") as service:
        result = RemoteRefundClient(service.base_url).refund("ledger-proof", request_data)
        with sqlite3.connect(service.database) as db:
            receipt = json.loads(db.execute("SELECT receipt FROM operations").fetchone()[0])
            effect = db.execute("SELECT effect_id,amount_cents FROM effects").fetchone()
            assert (receipt["effect_id"], receipt["amount_cents"]) == effect
            assert receipt == result.receipt
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("requested,corrupted", [(3100, 3100.0), (1, True)])
def test_malformed_persisted_receipt_preserves_unknown_effect(tmp_path, requested, corrupted):
    request = RefundRequest(
        order_id="ORD-100",
        customer_id="CUS-17",
        amount_cents=requested,
        policy_version="refund-v1",
    )
    with LAB.ServiceProcess(tmp_path / "malformed-receipt") as service:
        client = RemoteRefundClient(service.base_url, max_attempts=1)
        original = client.refund("malformed-receipt", request)
        assert original.outcome == "committed"
        # Simulate a faulty remote serializer/persisted receipt while retaining the real effect.
        with sqlite3.connect(service.database) as db:
            receipt = {**original.receipt, "amount_cents": corrupted}
            db.execute("UPDATE operations SET receipt=?", (json.dumps(receipt),))
        result = client.refund("malformed-receipt", request)
        assert result.outcome == "unresolved"
        assert result.reason == "effect_state_unknown"
        assert result.receipt is None
        assert LAB.ledger(service.database)["total_cents"] == requested


def test_process_spawn_failure_closes_open_log(tmp_path, monkeypatch):
    service = LAB.ServiceProcess(tmp_path / "spawn-failure")

    def fail_spawn(*args, **kwargs):
        raise OSError("induced process spawn failure")

    with monkeypatch.context() as patch:
        patch.setattr(LAB.subprocess, "Popen", fail_spawn)
        with pytest.raises(OSError, match="induced process spawn failure"):
            service.__enter__()
    assert service.process is None
    assert service.log.closed
    service.__exit__(None, None, None)
