import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app, summarize
from agentproof.engine import Engine
from agentproof.providers import LiveProvider, ProviderFailure, ScriptedProvider, parse_proposal
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

    adapter = LiveProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
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

    adapter = LiveProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
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

    adapter = LiveProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
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
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    )
    with pytest.raises(ProviderFailure):
        adapter.propose({})


def test_malformed_json_repaired_without_counting_injection_as_api_call(tmp_path, live_env):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=model_response())

    adapter = LiveProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
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
    with TestClient(create_app(tmp_path / "api.db")) as client:
        scenario = BY_ID["eligible"].model_copy(deep=True)
        scenario.id = "custom-return"
        scenario.order.age_days = 29
        response = client.post("/api/experiments", json={"scenarios": [scenario.model_dump()]})
        assert response.status_code == 201, response.text
        data = response.json()
        assert len(data["runs"]) == 2
        assert data["scenarios"] == [scenario.model_dump()]
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
    with TestClient(create_app(tmp_path / "api.db")) as client:
        assert "test-super-secret" not in client.get("/api/config").text
        assert client.get("/api/docs").status_code == 200


@pytest.mark.parametrize(
    "field,value", [("fault", "commit_timout"), ("expected_outcome", "refundded")]
)
def test_custom_suite_rejects_unknown_fault_and_expected_outcome(tmp_path, field, value):
    with TestClient(create_app(tmp_path / "api.db")) as client:
        scenario = BY_ID["eligible"].model_dump()
        scenario[field] = value
        response = client.post("/api/experiments", json={"scenarios": [scenario]})
        assert response.status_code == 422
        assert client.get("/api/experiments").json() == []


def test_unexpected_failure_persists_failed_partial_experiment_with_redacted_error(tmp_path):
    class ThirdProposalFails(ScriptedProvider):
        calls = 0

        def propose(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("SECRET-provider-token customer-private-text")
            return super().propose(*args, **kwargs)

    adapter = ThirdProposalFails()
    app = create_app(tmp_path / "api.db", provider_factory=lambda _: adapter)
    with TestClient(app) as client:
        response = client.post("/api/experiments", json={"scenario_ids": ["eligible", "partial"]})
        # The experiment resource is created and its execution status explicitly reports failure.
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "failed"
        assert len(data["runs"]) == 2
        assert data["summary"]["expected_runs"] == 4
        assert not data["summary"]["gate"]["passed"]
        assert "SECRET-provider-token" not in response.text
        assert data["error"]["type"] == "RuntimeError"
        assert any("2 of 4" in reason for reason in data["summary"]["gate"]["reasons"])
        persisted = client.get(f"/api/experiments/{data['id']}").json()
        assert persisted["status"] == "failed"
        assert not persisted["summary"]["gate"]["passed"]
        assert not client.get("/api/experiments").json()[0]["summary"]["gate"]["passed"]


def test_running_or_truncated_experiment_cannot_pass_gate(tmp_path):
    engine = Engine(Store(tmp_path / "runs.db"))
    runs = [engine.run(BY_ID["eligible"], variant) for variant in ("baseline", "guarded")]
    assert summarize(runs, "scripted", status="completed", expected_run_count=2)["gate"]["passed"]
    assert not summarize(runs, "scripted", status="running", expected_run_count=2)["gate"]["passed"]
    assert not summarize(runs, "scripted", status="completed", expected_run_count=4)["gate"][
        "passed"
    ]
    runs[1]["status"] = "failed"
    assert not summarize(runs, "scripted", status="completed", expected_run_count=2)["gate"][
        "passed"
    ]


def test_experiment_records_effective_provider_settings_and_safe_server_metadata(
    tmp_path, live_env, monkeypatch
):
    monkeypatch.setenv("AGENTPROOF_MAX_TOKENS", "9000")
    monkeypatch.setenv("AGENTPROOF_TIMEOUT_SECONDS", "900")
    adapter = LiveProvider(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=model_response()))
        )
    )
    with TestClient(
        create_app(tmp_path / "settings.db", provider_factory=lambda _: adapter)
    ) as client:
        response = client.post(
            "/api/experiments", json={"provider": "openai", "scenario_ids": ["eligible"]}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["configuration"]["max_tokens"] == adapter.max_tokens == 2048
        assert data["configuration"]["timeout_seconds"] == adapter.timeout == 120
        metadata = data["server_metadata"]
        assert len(metadata["backend_source_sha256"]) == 64
        assert metadata["python_version"] and metadata["os"] and metadata["architecture"]
        assert "/Users/" not in json.dumps(metadata)
        assert "hostname" not in metadata and "username" not in metadata


@pytest.mark.parametrize("usage", [None, [], "private-provider-response", 5, True])
def test_malformed_usage_is_redacted_provider_failure(live_env, usage):
    body = model_response()
    body["usage"] = usage
    adapter = LiveProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    )
    with pytest.raises(ProviderFailure) as error:
        adapter.propose({})
    assert "private-provider-response" not in str(error.value)


@pytest.mark.parametrize("tokens", [-1, True, False, 1.5, "83", None, [], {}])
def test_token_counts_are_nonnegative_integers_without_coercion(live_env, tokens):
    body = model_response()
    body["usage"] = {"total_tokens": tokens}
    adapter = LiveProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    )
    with pytest.raises(ProviderFailure):
        adapter.propose({})


@pytest.mark.parametrize("usage", ["absent", {}, {"total_tokens": 0}, {"total_tokens": 83}])
def test_absent_usage_or_valid_token_counts_are_supported(live_env, usage):
    body = model_response()
    if usage == "absent":
        body.pop("usage")
    else:
        body["usage"] = usage
    adapter = LiveProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    )
    content, tokens = adapter.propose({})
    assert json.loads(content)["action"] == "refund"
    assert tokens == (83 if usage == {"total_tokens": 83} else 0)
