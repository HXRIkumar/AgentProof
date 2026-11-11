import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.engine import Engine
from agentproof.providers import LiveProvider, ProviderFailure, parse_proposal
from agentproof.scenarios import BY_ID
from agentproof.store import Store


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:8089/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "test-model")
    monkeypatch.delenv("AGENTPROOF_API_KEY", raising=False)


def model_response():
    proposal = {
        "action": "refund",
        "order_id": "ORD-1042",
        "customer_id": "CUS-17",
        "amount_cents": 4900,
        "policy_version": "refund-v1",
        "reason": "Eligible request",
    }
    return {
        "choices": [{"message": {"content": json.dumps(proposal)}}],
        "usage": {"total_tokens": 83},
    }


def test_live_provider_real_http_accounting_and_oracle_separation(tmp_path, live_env):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=model_response())

    adapter = LiveProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    run = Engine(Store(tmp_path / "test.db"), lambda _: adapter).run(
        BY_ID["eligible"], provider="openai"
    )
    assert run["passed"]
    assert run["model_calls"] == len(requests) == 1
    assert run["token_usage"] == 83
    prompt = json.dumps(requests[0]["messages"])
    assert "expected_outcome" not in prompt
    assert "fault" not in prompt
    assert "guarded" not in prompt
    assert requests[0]["temperature"] == 0
    assert requests[0]["max_tokens"] <= 2048


def test_provider_failure_is_bounded_and_redacts_response(tmp_path, live_env):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": "secret-token-never-log-me"})

    adapter = LiveProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    run = Engine(Store(tmp_path / "test.db"), lambda _: adapter).run(
        BY_ID["eligible"], provider="openai"
    )
    assert run["model_calls"] == len(requests) == 3
    assert run["outcome"] == "escalated"
    assert not run["passed"]
    assert run["safe"]
    assert run["retries"] == 2
    assert "secret-token" not in json.dumps(run)


def test_live_http_timeout_is_bounded(tmp_path, live_env):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("request timed out")

    adapter = LiveProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    run = Engine(Store(tmp_path / "test.db"), lambda _: adapter).run(
        BY_ID["eligible"], provider="openai"
    )
    assert len(requests) == 3
    assert run["safe"] and run["outcome"] == "escalated"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": []}}]},
    ],
)
def test_incompatible_provider_response_fails_closed(live_env, body):
    adapter = LiveProvider(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    )
    with pytest.raises(ProviderFailure):
        adapter.propose({})


def test_malformed_json_repaired_without_counting_injection_as_api_call(tmp_path, live_env):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=model_response())

    adapter = LiveProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    run = Engine(Store(tmp_path / "test.db"), lambda _: adapter).run(
        BY_ID["malformed"], provider="openai"
    )
    assert run["passed"]
    assert run["model_calls"] == len(requests) == 1
    assert run["proposal_calls"] == 2
    assert run["retries"] == 1
    assert any(
        e["kind"] == "fault" and e["detail"]["network_request"] is False for e in run["events"]
    )


def test_valid_fenced_json_is_accepted():
    raw = model_response()["choices"][0]["message"]["content"]
    assert parse_proposal("```json\n" + raw + "\n```").amount_cents == 4900


@pytest.mark.parametrize(
    "raw", ["``````", "```\n```", "[]", "null", '{"action":"refund","amount_cents":true}']
)
def test_malformed_proposals_raise_value_error(raw):
    with pytest.raises(ValueError):
        parse_proposal(raw)


def test_custom_suite_snapshot_and_hash(tmp_path):
    client = TestClient(create_app(tmp_path / "api.db"))
    scenario = BY_ID["eligible"].model_copy(deep=True)
    scenario.id = "custom-return"
    scenario.order.age_days = 29
    response = client.post("/api/experiments", json={"scenarios": [scenario.model_dump()]})
    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data["runs"]) == 2
    assert all(r["scenario_id"] == "custom-return" for r in data["runs"])
    changed = scenario.model_copy(deep=True)
    changed.order.age_days = 28
    other = client.post("/api/experiments", json={"scenarios": [changed.model_dump()]}).json()
    assert data["suite_hash"] != other["suite_hash"]
    assert data["runs"][0]["scenario_hash"] != other["runs"][0]["scenario_hash"]
    conflict = client.post(
        "/api/experiments",
        json={"scenarios": [scenario.model_dump()], "scenario_ids": ["eligible"]},
    )
    assert conflict.status_code == 422


def test_nonlocal_http_endpoint_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://example.com/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "test-model")
    with pytest.raises(ValueError, match="HTTPS"):
        LiveProvider()


def test_no_credentials_leak_in_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTPROOF_API_KEY", "test-super-secret")
    client = TestClient(create_app(tmp_path / "api.db"))
    assert "test-super-secret" not in client.get("/api/config").text
    assert client.get("/api/docs").status_code == 200
