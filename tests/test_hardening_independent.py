"""Independent operational boundary checks, separate from implementation-authored tests."""

import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.providers import LiveProvider, ProviderFailure


def test_dns_cleanup_can_extend_http_deadline_without_orphaned_resolver(monkeypatch):
    """Document the resolver boundary instead of claiming an absolute wall-clock deadline."""
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://localhost:9/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "independent-dns-deadline")
    monkeypatch.setenv("AGENTPROOF_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AGENTPROOF_MAX_TOKENS", "128")
    monkeypatch.delenv("AGENTPROOF_API_KEY", raising=False)
    monkeypatch.delenv("AGENTPROOF_DISABLE_THINKING", raising=False)
    original = socket.getaddrinfo
    resolver_finished = threading.Event()
    resolver_threads = []

    def slow_resolver(*args, **kwargs):
        resolver_threads.append(threading.current_thread())
        time.sleep(2.5)
        result = original(*args, **kwargs)
        resolver_finished.set()
        return result

    monkeypatch.setattr(socket, "getaddrinfo", slow_resolver)
    start = time.monotonic()
    with pytest.raises(ProviderFailure):
        LiveProvider().propose({})
    # The HTTP task times out, then asyncio.run waits for the blocking resolver.
    # Returning early by abandoning a resolver thread is not the accepted design.
    assert time.monotonic() - start >= 2.5
    assert resolver_finished.is_set()
    assert resolver_threads
    assert all(not thread.is_alive() for thread in resolver_threads)


def test_host_rejection_precedes_json_validation_and_queue_mutation(tmp_path):
    app = create_app(tmp_path / "host-precedence.sqlite")
    with TestClient(app) as client:
        rejected = client.post(
            "/api/experiments?background=true",
            headers={"Host": "local.attacker.example", "Content-Type": "application/json"},
            content=b"this is not valid JSON",
        )
        assert rejected.status_code == 400
        assert "Invalid host header" in rejected.text
        assert client.get("/api/experiments").json() == []


def test_comparison_rejects_post_approval_reference_without_reexecuting(tmp_path):
    app = create_app(tmp_path / "approval-compare.sqlite")
    with TestClient(app) as client:
        reports = [
            client.post("/api/experiments", json={"scenario_ids": ["approval"]}).json()
            for _ in range(2)
        ]
        reference, candidate = reports
        pending = next(run for run in reference["runs"] if run["status"] == "awaiting_approval")
        denied = client.post(f"/api/runs/{pending['id']}/approve", json={"approved": False})
        assert denied.status_code == 200
        before = client.get(f"/api/experiments/{reference['id']}").json()
        response = client.post(
            "/api/comparisons",
            json={"reference_id": reference["id"], "candidate_id": candidate["id"]},
        )
        assert response.status_code == 422
        assert "pre-approval" in response.json()["detail"]
        assert "gate" not in response.json()
        assert client.get(f"/api/experiments/{reference['id']}").json() == before
        assert len(client.get("/api/experiments").json()) == 2
