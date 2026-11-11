"""Local-only operational boundaries: actual socket deadline, bounded bodies and readiness."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.middleware import MAX_REQUEST_BYTES
from agentproof.providers import LiveProvider, ProviderFailure


@pytest.fixture
def provider_env(monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "local-test")
    monkeypatch.setenv("AGENTPROOF_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AGENTPROOF_MAX_TOKENS", "128")
    monkeypatch.delenv("AGENTPROOF_DISABLE_THINKING", raising=False)
    monkeypatch.delenv("AGENTPROOF_API_KEY", raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost/v1",
        "file://localhost/v1",
        "localhost/v1",
        "http:///v1",
        "http://localhost:bad/v1",
        "http://localhost:0/v1",
        "http://localhost:70000/v1",
        "http://user:SECRET@127.0.0.1/v1",
        "http://127.0.0.1/v1?SECRET=value",
        "http://127.0.0.1/v1#SECRET",
        "http://127.0.0.1/v1?",
        "http://127.0.0.1/v1#",
        "http://bad host/v1",
        "http://[::1/v1",
        "http://localhost.evil.example/v1",
    ],
)
def test_invalid_urls_fail_before_request_without_echoing_secrets(provider_env, monkeypatch, url):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", url)
    with pytest.raises(ValueError) as error:
        LiveProvider()
    assert "SECRET" not in str(error.value)
    assert url not in str(error.value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1", "SECRET"])
def test_nonpositive_nonfinite_or_invalid_timeout_is_rejected(provider_env, monkeypatch, value):
    monkeypatch.setenv("AGENTPROOF_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError) as error:
        LiveProvider()
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "SECRET"])
def test_invalid_token_limit_is_rejected(provider_env, monkeypatch, value):
    monkeypatch.setenv("AGENTPROOF_MAX_TOKENS", value)
    with pytest.raises(ValueError) as error:
        LiveProvider()
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize(
    "url", ["http://localhost:123/v1", "http://127.0.0.1/v1", "http://[::1]:123/v1"]
)
def test_exact_loopback_urls_work_without_credentials(provider_env, monkeypatch, url):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", url)
    assert LiveProvider().is_loopback


def test_remote_https_requires_separate_api_key(provider_env, monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "https://model.example/v1")
    with pytest.raises(ValueError, match="AGENTPROOF_API_KEY"):
        LiveProvider()
    monkeypatch.setenv("AGENTPROOF_API_KEY", "not-a-real-key")
    assert LiveProvider().is_loopback is False


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def invoke_mock(stream, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers=headers, stream=stream)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ProviderFailure):
            LiveProvider(client).propose({})
    finally:
        asyncio.run(client.aclose())
    assert stream.closed
    assert requests[0].headers["accept-encoding"] == "identity"


def test_oversized_stream_stops_before_consuming_remainder(provider_env):
    stream = TrackingStream([b"x" * 16_384] * 100)
    invoke_mock(stream)
    assert stream.read_count == LiveProvider.MAX_RESPONSE_BYTES // 16_384 + 1


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "gzip, identity"])
def test_compression_is_rejected_before_read_or_decode(provider_env, encoding):
    # A compressed/decompression-bomb stream cannot allocate its payload: never iterated.
    stream = TrackingStream([b"not-read"])
    invoke_mock(stream, {"Content-Encoding": encoding})
    assert stream.read_count == 0


def test_declared_oversize_response_is_rejected_before_read(provider_env):
    stream = TrackingStream([b"not-read"])
    invoke_mock(stream, {"Content-Length": str(LiveProvider.MAX_RESPONSE_BYTES + 1)})
    assert stream.read_count == 0


def test_numeric_loopback_slow_drip_is_cancelled_and_connection_closed(provider_env, monkeypatch):
    disconnected = threading.Event()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100")
            self.end_headers()
            try:
                # Progress every150ms avoids the one-second inactivity timeout. Without
                # the total deadline, this response would take15seconds.
                for _ in range(100):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AGENTPROOF_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    # A loopback model request must not accidentally use an inherited proxy.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        start = time.monotonic()
        with pytest.raises(ProviderFailure, match="TimeoutError"):
            LiveProvider().propose({"observation": "synthetic"})
        elapsed = time.monotonic() - start
        assert 0.8 <= elapsed < 2.0
        assert disconnected.wait(2), "The timed-out request left a connection running"
        assert received[0]["temperature"] == 0
        assert received[0]["max_tokens"] == 128
        assert received[0]["response_format"] == {"type": "json_object"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("host", ["untrusted.example", "localhost.evil.example", "www.localhost"])
def test_untrusted_hosts_are_rejected_before_api_execution(tmp_path, host):
    with TestClient(create_app(tmp_path / "host.db")) as client:
        response = client.post(
            "/api/experiments", headers={"Host": host}, json={"scenario_ids": ["eligible"]}
        )
        assert response.status_code == 400
        assert client.get("/api/experiments").json() == []


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:8010", "127.0.0.1:8010", "[::1]:8010", "testserver"]
)
def test_local_hosts_and_ports_are_accepted(tmp_path, host):
    with TestClient(create_app(tmp_path / "host.db")) as client:
        assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_exact_byte_limit_works_and_one_extra_byte_creates_no_job(tmp_path):
    with TestClient(create_app(tmp_path / "body.db")) as client:
        base = b'{"scenario_ids":["eligible"]}'
        body = base + b" " * (MAX_REQUEST_BYTES - len(base))
        assert (
            client.post(
                "/api/experiments", content=body, headers={"Content-Type": "application/json"}
            ).status_code
            == 201
        )
        response = client.post(
            "/api/experiments", content=body + b" ", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
        assert len(client.get("/api/experiments").json()) == 1


@pytest.mark.parametrize("declared", [None, "1"])
def test_actual_chunked_body_bytes_enforced_without_trusting_header(tmp_path, declared):
    app = create_app(tmp_path / "chunked.db")
    read_count = 0

    async def exercise():
        nonlocal read_count

        async def chunks():
            nonlocal read_count
            # ASCII is not required: the cap measures bytes, not decoded characters.
            yield b'{"name":"'
            for _ in range(80):
                read_count += 1
                yield "é".encode() * 8192
            yield b'","scenario_ids":["eligible"]}'

        headers = {"Content-Type": "application/json"}
        if declared:
            headers["Content-Length"] = declared
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1"
        ) as client:
            return await client.post("/api/experiments", content=chunks(), headers=headers)

    with TestClient(app) as client:
        response = asyncio.run(exercise())
        assert response.status_code == 413, response.text
        assert read_count < 80
        assert client.get("/api/experiments").json() == []


def test_readiness_distinguishes_worker_and_database_from_liveness(tmp_path):
    path = tmp_path / "ready.db"
    app = create_app(path)
    with TestClient(app) as client:
        assert client.get("/api/ready").json() == {
            "status": "ready",
            "worker_available": True,
            "database_available": True,
        }
        app.state.worker.stop()
        assert client.get("/api/health").status_code == 200
        stopped = client.get("/api/ready")
        assert stopped.status_code == 503
        assert stopped.json()["worker_available"] is False
        path.unlink()
        missing = client.get("/api/ready")
        assert missing.status_code == 503
        assert missing.json()["database_available"] is False
        assert not path.exists(), "Readiness recreated a deleted database"
        assert str(tmp_path) not in missing.text


def test_deadline_cancels_request_then_worker_executes_next_queued_experiment(
    tmp_path, provider_env
):
    requests = 0
    interrupted = threading.Event()
    started = threading.Event()

    async def response(request):
        nonlocal requests
        requests += 1
        if requests == 1:
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                interrupted.set()
                raise
        proposal = {
            "action": "refund",
            "order_id": "ORD-1042",
            "customer_id": "CUS-17",
            "amount_cents": 4900,
            "policy_version": "refund-v1",
            "reason": "Eligible",
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(proposal)}}],
                "usage": {"total_tokens": 20},
            },
        )

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    adapter = LiveProvider(transport_client)
    app = create_app(tmp_path / "timeout-queue.db", lambda _: adapter)
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/experiments?background=true",
                json={"provider": "openai", "scenario_ids": ["eligible"]},
            ).json()
            assert started.wait(2)
            second = client.post(
                "/api/experiments?background=true",
                json={"provider": "openai", "scenario_ids": ["eligible"]},
            ).json()
            assert second["status"] == "queued"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                final = client.get(f"/api/experiments/{second['id']}").json()
                if final["status"] == "completed":
                    break
                time.sleep(0.02)
            assert final["status"] == "completed"
            assert final["summary"]["gate"]["passed"]
            assert interrupted.is_set()
            previous = client.get(f"/api/experiments/{first['id']}").json()
            assert previous["status"] == "completed"
            baseline = next(run for run in previous["runs"] if run["variant"] == "baseline")
            assert baseline["model_calls"] == 1
            assert baseline["passed"] is False
            assert requests == 4
            assert client.get("/api/ready").status_code == 200
    finally:
        asyncio.run(transport_client.aclose())
