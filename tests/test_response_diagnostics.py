"""Metadata-only diagnostics; all provider traffic uses local MockTransport."""

import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import httpx
import pytest
from pydantic import ValidationError

from agentproof.engine import Engine
from agentproof.providers import (
    LiveProvider,
    ProviderFailure,
    ResponseDiagnostics,
    ScriptedProvider,
    parse_proposal,
)
from agentproof.scenarios import BY_ID
from agentproof.store import Store

ABSENT = object()


@pytest.fixture(autouse=True)
def provider_configuration(monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "diagnostic-mock")
    monkeypatch.setenv("AGENTPROOF_API_KEY", "PRIVATE-API-KEY")
    monkeypatch.setenv("AGENTPROOF_DISABLE_THINKING", "true")


def completion(content, *, reason="stop", usage=ABSENT, extra=None):
    response = {"choices": [{"finish_reason": reason, "message": {"content": content}}]}
    if usage is not ABSENT:
        response["usage"] = usage
    if extra:
        response.update(extra)
    return response


def valid_proposal():
    return json.dumps(
        {
            "action": "refund",
            "order_id": "ORD-1042",
            "customer_id": "CUS-17",
            "amount_cents": 4900,
            "policy_version": "refund-v1",
            "reason": "Eligible request",
        }
    )


def run_response(tmp_path, response, variant="baseline"):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    )
    adapter = LiveProvider(client)
    try:
        run = Engine(Store(tmp_path / "responses.sqlite"), lambda _: adapter).run(
            BY_ID["eligible"], variant, "openai"
        )
        assert adapter.response_diagnostics is None, "The engine must consume response metadata"
        return run
    finally:
        asyncio.run(client.aclose())


def proposal_event(run):
    return next(event for event in run["events"] if event["name"] == "propose_action")


@pytest.mark.parametrize(
    "content,category",
    [
        ("", "empty"),
        (" \n\t", "empty"),
        ("```json\n\n```", "empty"),
        ('{"action":', "invalid_json"),
        ("PRIVATE-RAW-OUTPUT", "invalid_json"),
        ("{}", "schema_validation"),
        ("[]", "schema_validation"),
        ("null", "schema_validation"),
    ],
)
def test_actual_parse_failure_category_without_storing_raw_text(tmp_path, content, category):
    run = run_response(tmp_path, completion(content, reason="length", usage={"total_tokens": 31}))
    event = proposal_event(run)
    diagnostic = event["detail"]["response_diagnostics"]
    assert event["status"] == "error"
    assert diagnostic["parse_category"] == category
    assert diagnostic["finish_reason"] == "length"
    assert diagnostic["content_utf8_bytes"] == len(content.encode("utf-8"))
    assert diagnostic["content_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert diagnostic["usage_known"] is True
    assert diagnostic["usage_status"] == "reported"
    assert run["token_usage"] == 31
    assert run["model_calls"] == 1
    assert "PRIVATE-RAW-OUTPUT" not in json.dumps(run)
    assert "PRIVATE-API-KEY" not in json.dumps(run)
    assert run["safe"] is True


def test_length_finish_reason_does_not_guess_truncation_or_change_valid_outcome(tmp_path):
    run = run_response(
        tmp_path, completion(valid_proposal(), reason="length", usage={"total_tokens": 31})
    )
    assert run["passed"]
    assert proposal_event(run)["detail"]["response_diagnostics"]["parse_category"] == "valid"
    assert proposal_event(run)["detail"]["response_diagnostics"]["finish_reason"] == "length"


@pytest.mark.parametrize(
    "usage,present,known,status",
    [
        (ABSENT, False, False, "missing"),
        ({}, True, False, "missing_total_tokens"),
        ({"prompt_tokens": 10}, True, False, "missing_total_tokens"),
        ({"total_tokens": 0}, True, True, "reported"),
        ({"total_tokens": 31}, True, True, "reported"),
    ],
)
def test_usage_presence_and_validity_remain_distinct_from_zero(
    tmp_path, usage, present, known, status
):
    run = run_response(tmp_path, completion(valid_proposal(), usage=usage))
    diagnostic = proposal_event(run)["detail"]["response_diagnostics"]
    assert run["passed"] and run["model_calls"] == 1
    assert diagnostic["usage_present"] is present
    assert diagnostic["usage_known"] is known
    assert diagnostic["usage_status"] == status
    assert run["token_usage"] == (31 if usage == {"total_tokens": 31} else 0)


@pytest.mark.parametrize("usage", [None, [], {"total_tokens": True}, {"total_tokens": -1}])
def test_invalid_usage_remains_provider_failure_with_uncertain_metadata(tmp_path, usage):
    run = run_response(tmp_path, completion(valid_proposal(), usage=usage))
    event = proposal_event(run)
    diagnostic = event["detail"]["response_diagnostics"]
    assert event["detail"]["error"] == "ProviderFailure"
    assert diagnostic["usage_present"] is True
    assert diagnostic["usage_known"] is False
    assert diagnostic["usage_status"] == "invalid"
    assert diagnostic["parse_category"] == "not_attempted"
    assert run["token_usage"] == 0
    assert run["passed"] is False


@pytest.mark.parametrize("reason", ["PRIVATE-FINISH-REASON" * 100, {"secret": "PRIVATE"}, 123, []])
def test_arbitrary_finish_reasons_and_response_fields_are_never_copied(tmp_path, reason):
    run = run_response(
        tmp_path,
        completion(
            "PRIVATE-MODEL-TEXT",
            reason=reason,
            usage={"total_tokens": 7, "secret": "PRIVATE-USAGE-FIELD"},
            extra={"debug": "PRIVATE-PROVIDER-FIELD"},
        ),
    )
    diagnostic = proposal_event(run)["detail"]["response_diagnostics"]
    assert diagnostic["finish_reason"] == "unknown"
    assert len(json.dumps(diagnostic)) < 600
    assert "PRIVATE" not in json.dumps(run)


def test_error_status_never_retains_headers_or_provider_error_body(tmp_path):
    response = httpx.Response(
        429, json={"error": "PRIVATE-ERROR-BODY"}, headers={"X-Private": "PRIVATE-HEADER"}
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
    try:
        adapter = LiveProvider(client)
        run = Engine(Store(tmp_path / "error.sqlite"), lambda _: adapter).run(
            BY_ID["eligible"], "baseline", "openai"
        )
        diagnostic = proposal_event(run)["detail"]["response_diagnostics"]
        assert diagnostic == {
            "http_status": 429,
            "finish_reason": "unavailable",
            "usage_present": None,
            "usage_known": False,
            "usage_status": "unavailable",
            "content_utf8_bytes": None,
            "content_sha256": None,
            "parse_category": "not_attempted",
        }
        assert "PRIVATE" not in json.dumps(run)
    finally:
        asyncio.run(client.aclose())


def test_utf8_count_hash_immutability_and_tuple_contract():
    content = '{"text":"é ☕"}'
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=completion(content, usage={"total_tokens": 9}))
        )
    )
    try:
        adapter = LiveProvider(client)
        raw, tokens = adapter.propose({})
        assert (raw, tokens) == (content, 9)
        diagnostic = adapter.response_diagnostics
        assert isinstance(diagnostic, ResponseDiagnostics)
        assert diagnostic.content_utf8_bytes == len(content.encode("utf-8")) > len(content)
        assert diagnostic.content_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
        with pytest.raises(FrozenInstanceError):
            diagnostic.finish_reason = "stop"
        assert adapter.consume_response_diagnostics() is diagnostic
        assert adapter.consume_response_diagnostics() is None
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("fault", ["malformed", "model_outage"])
def test_injected_fault_clears_unconsumed_previous_actual_response(fault):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion(valid_proposal(), usage={"total_tokens": 9}))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = LiveProvider(client)
        adapter.propose({})
        assert adapter.response_diagnostics is not None
        if fault == "model_outage":
            with pytest.raises(ProviderFailure):
                adapter.propose({}, fault=fault)
        else:
            assert adapter.propose({}, fault=fault) == ('{"action":', 0)
        assert adapter.response_diagnostics is None
        assert len(requests) == 1
    finally:
        asyncio.run(client.aclose())


def test_transport_failure_cannot_reuse_last_response_metadata(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=completion(valid_proposal()))
        raise httpx.ReadTimeout("PRIVATE-TRANSPORT-ERROR")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = LiveProvider(client)
        adapter.propose({})
        assert adapter.response_diagnostics is not None
        run = Engine(Store(tmp_path / "stale.sqlite"), lambda _: adapter).run(
            BY_ID["eligible"], "baseline", "openai"
        )
        assert "response_diagnostics" not in proposal_event(run)["detail"]
        assert adapter.response_diagnostics is None
        assert "PRIVATE" not in json.dumps(run)
    finally:
        asyncio.run(client.aclose())


def test_shared_provider_threads_do_not_overwrite_each_others_diagnostics():
    barrier = threading.Barrier(2)

    def handler(request):
        observation = json.loads(json.loads(request.content)["messages"][-1]["content"])
        content = json.dumps({"thread": observation["id"]})
        reason = "stop" if observation["id"] == "first" else "length"
        return httpx.Response(
            200, json=completion(content, reason=reason, usage={"total_tokens": 3})
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = LiveProvider(client)

    def call(identity):
        raw, tokens = adapter.propose({"id": identity})
        barrier.wait(timeout=3)  # Force both responses to exist before either is consumed.
        metadata = adapter.consume_response_diagnostics()
        assert adapter.consume_response_diagnostics() is None
        return identity, raw, tokens, metadata

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(call, ("first", "second")))
        for identity, raw, tokens, metadata in values:
            assert tokens == 3
            assert metadata.content_sha256 == hashlib.sha256(raw.encode()).hexdigest()
            assert metadata.finish_reason == ("stop" if identity == "first" else "length")
        assert adapter.response_diagnostics is None  # Main thread never made a request.
    finally:
        asyncio.run(client.aclose())


def test_failed_then_valid_attempts_keep_separate_fingerprints_and_original_feedback(tmp_path):
    captured = []
    raw_bad = '{"action":'
    raw_good = valid_proposal()

    def handler(request):
        captured.append(json.loads(request.content))
        content = raw_bad if len(captured) == 1 else raw_good
        return httpx.Response(
            200,
            json=completion(
                content,
                reason="length" if len(captured) == 1 else "stop",
                usage={"total_tokens": 13},
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = LiveProvider(client)
        run = Engine(Store(tmp_path / "retry.sqlite"), lambda _: provider).run(
            BY_ID["eligible"], "guarded", "openai"
        )
        events = [event for event in run["events"] if event["name"] == "propose_action"]
        assert run["passed"] and run["proposal_calls"] == run["model_calls"] == 2
        assert run["token_usage"] == 26 and run["retries"] == 1
        assert [event["detail"]["response_diagnostics"]["parse_category"] for event in events] == [
            "invalid_json",
            "valid",
        ]
        assert [event["detail"]["response_diagnostics"]["content_sha256"] for event in events] == [
            hashlib.sha256(raw.encode()).hexdigest() for raw in (raw_bad, raw_good)
        ]
        assert (
            captured[1]["messages"][-1]["content"]
            == "Runtime validation rejected the proposal: Return valid JSON matching the documented schema. Return a corrected JSON proposal."
        )
        assert captured[0]["max_tokens"] == captured[1]["max_tokens"] == provider.max_tokens
    finally:
        asyncio.run(client.aclose())


def test_scripted_trials_do_not_claim_actual_response_metadata(tmp_path):
    run = Engine(Store(tmp_path / "scripted.sqlite"), lambda _: ScriptedProvider()).run(
        BY_ID["malformed"]
    )
    assert run["model_calls"] == 0
    assert all("response_diagnostics" not in event["detail"] for event in run["events"])
    with pytest.raises(ValidationError):
        parse_proposal("{}")


def test_schema_validation_does_not_retain_private_input_or_pydantic_error_messages(tmp_path):
    raw = json.dumps({"PRIVATE-EXTRA-KEY": "PRIVATE-INPUT", "amount_cents": "PRIVATE-MONEY"})
    run = run_response(tmp_path, completion(raw, usage={"total_tokens": 5}))
    detail = proposal_event(run)["detail"]
    assert detail["error"] == "ValidationError"
    assert detail["response_diagnostics"]["parse_category"] == "schema_validation"
    assert "PRIVATE" not in json.dumps(run)


def test_invalid_unicode_is_not_silently_replaced_for_a_fingerprint():
    raw = "\ud800"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=json.dumps(completion(raw, usage={"total_tokens": 1})).encode(),
                headers={"Content-Type": "application/json"},
            )
        )
    )
    try:
        adapter = LiveProvider(client)
        assert adapter.propose({}) == (raw, 1)
        assert adapter.response_diagnostics.content_utf8_bytes is None
        assert adapter.response_diagnostics.content_sha256 is None
    finally:
        asyncio.run(client.aclose())
