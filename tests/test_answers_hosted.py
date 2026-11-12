"""No network or real credentials: hosted transport and budget invariants use mock HTTP."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agentproof.answers import OpenAIAdapter
from agentproof.answers.hosted_budget import (
    BASE_URL,
    MAX_BUDGET_NANOUSD,
    MODEL,
    BudgetError,
    BudgetLedger,
    estimate_nanodollars,
    input_token_bound,
    load_openai_key,
)
from agentproof.answers.provider import usage_for

MESSAGES = [
    {"role": "system", "content": "Return JSON."},
    {"role": "user", "content": "Check the cited answer."},
]


def response_body(*, prompt=100, completion=20, model=MODEL, tier="default"):
    return {
        "model": model,
        "service_tier": tier,
        "choices": [{"message": {"content": '{"supported":true}'}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_tokens_details": {"cached_tokens": 50},
            "completion_tokens_details": {"reasoning_tokens": 10},
        },
    }


def make_adapter(tmp_path, handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    return (
        OpenAIAdapter(
            base_url=BASE_URL,
            model=MODEL,
            enable_paid=True,
            client=client,
            budget_ledger=ledger,
            hosted_key_loader=lambda: "unit-test-not-real",
            **kwargs,
        ),
        client,
        ledger,
    )


def test_reservations_survive_restart_and_known_usage_releases_only_unused_bound(tmp_path):
    path = tmp_path / "budget.sqlite3"
    ledger = BudgetLedger(path)
    reserved = ledger.reserve(MESSAGES, 1536, "critic")
    restarted = BudgetLedger(path)
    assert restarted.snapshot()["accounted_usd"] == reserved["reserved_usd"]
    assert restarted.snapshot()["unresolved_reservations"] == 1
    settled = restarted.settle(
        reserved["reservation_id"],
        prompt_tokens=100,
        completion_tokens=20,
        response_model=MODEL,
        service_tier="default",
    )
    expected = estimate_nanodollars(100, 20) / 1e9
    assert settled["estimated_cost_usd"] == expected
    assert restarted.snapshot()["accounted_usd"] == expected
    assert restarted.snapshot()["unresolved_reservations"] == 0
    assert ledger.snapshot()["ceiling_usd"] == 1.5


def test_unknown_outcome_remains_charged_and_cannot_be_released_later(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    reserved = ledger.reserve(MESSAGES, 1536, "critic")
    uncertain = ledger.settle(reserved["reservation_id"])
    assert uncertain["state"] == "uncertain"
    later = ledger.settle(
        reserved["reservation_id"],
        prompt_tokens=1,
        completion_tokens=1,
        response_model=MODEL,
        service_tier="default",
    )
    assert later == uncertain
    assert ledger.snapshot()["accounted_usd"] == reserved["reserved_usd"]


def test_ceiling_can_only_decrease_across_instances(tmp_path):
    path = tmp_path / "budget.sqlite3"
    original = BudgetLedger(path)
    lowered = BudgetLedger(path, ceiling_nanodollars=500_000_000)
    assert lowered.snapshot()["ceiling_usd"] == 0.5
    assert original.snapshot()["ceiling_usd"] == 0.5
    assert BudgetLedger(path).snapshot()["ceiling_usd"] == 0.5
    with pytest.raises(BudgetError):
        BudgetLedger(path, ceiling_nanodollars=MAX_BUDGET_NANOUSD + 1)


def test_threads_cannot_reserve_past_shared_ceiling(tmp_path):
    price = estimate_nanodollars(input_token_bound(MESSAGES), 1536)
    ledger = BudgetLedger(tmp_path / "budget.sqlite3", ceiling_nanodollars=price * 3)

    def reserve(_):
        try:
            ledger.reserve(MESSAGES, 1536, "critic")
            return True
        except BudgetError:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = list(pool.map(reserve, range(20)))
    assert sum(accepted) == 3
    assert ledger.snapshot()["accounted_usd"] == price * 3 / 1e9


def test_processes_share_one_ledger_and_do_not_reset_it(tmp_path):
    path = tmp_path / "budget.sqlite3"
    price = estimate_nanodollars(input_token_bound(MESSAGES), 1536)
    ledger = BudgetLedger(path, ceiling_nanodollars=price * 4)
    code = """
import json,sys
from agentproof.answers.hosted_budget import BudgetLedger,BudgetError
ledger=BudgetLedger(sys.argv[1]); messages=json.loads(sys.argv[2]); accepted=0
for _ in range(4):
    try: ledger.reserve(messages,1536,'critic'); accepted+=1
    except BudgetError: pass
print(accepted)
"""
    jobs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path), json.dumps(MESSAGES)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    outputs = [job.communicate(timeout=30) for job in jobs]
    assert all(job.returncode == 0 for job in jobs), outputs
    assert sum(int(stdout.strip()) for stdout, _ in outputs) == 4
    assert ledger.snapshot()["reservations"] == 4


def test_deleted_ledger_fails_closed_without_recreation(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    ledger.path.unlink()
    with pytest.raises(BudgetError):
        ledger.reserve(MESSAGES, 1536, "critic")
    assert not ledger.path.exists()


def test_paid_opt_in_blocks_before_key_read_or_network(tmp_path):
    called = []
    adapter = OpenAIAdapter(
        base_url=BASE_URL,
        model=MODEL,
        enable_paid=False,
        hosted_key_loader=lambda: called.append("key"),
    )
    result = adapter.complete(MESSAGES, purpose="critic")
    assert not result.request_sent and result.error
    assert result.blocked_reason == "paid_disabled"
    assert called == []
    assert usage_for([(result, False)])["actual_calls"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com.evil/v1",
        "http://api.openai.com/v1",
        "https://api.openai.com:443/v1",
        "https://api.openai.com/v1/other",
        "https://other.example/v1",
    ],
)
def test_unapproved_hosted_endpoints_rejected(url):
    with pytest.raises(ValueError):
        OpenAIAdapter(base_url=url, model=MODEL, enable_paid=True)


def test_only_pinned_priced_model_allowed():
    with pytest.raises(ValueError, match="priced"):
        OpenAIAdapter(base_url=BASE_URL, model="gpt-5.4-mini", enable_paid=True)


def test_hosted_payload_is_bounded_text_only_and_conservatively_priced(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=response_body())

    adapter, client, ledger = make_adapter(tmp_path, handler, critic_max_tokens=1536)
    try:
        result = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    payload = json.loads(seen[0].content)
    assert str(seen[0].url) == BASE_URL + "/chat/completions"
    assert payload["model"] == MODEL
    assert payload["max_completion_tokens"] == 1536
    assert payload["reasoning_effort"] == "low"
    assert payload["service_tier"] == "default" and payload["n"] == 1
    assert payload["store"] is False and payload["stream"] is False
    assert "temperature" not in payload and "max_tokens" not in payload
    assert "chat_template_kwargs" not in payload
    assert result.reasoning_tokens == 10
    assert result.completion_tokens == 20  # Reasoning is included, not added a second time.
    assert result.billing["state"] == "settled"
    assert result.billing["estimated_cost_usd"] == estimate_nanodollars(100, 20) / 1e9
    assert ledger.snapshot()["reported_usage_estimate_usd"] == result.billing["estimated_cost_usd"]
    assert "unit-test-not-real" not in json.dumps(adapter.configuration())


def test_hybrid_routes_local_and_hosted_keys_separately(tmp_path):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json=response_body())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIAdapter(
            base_url="http://127.0.0.1:8089/v1",
            model="local-draft",
            api_key="local-test-key",
            critic_base_url=BASE_URL,
            critic_model=MODEL,
            enable_paid=True,
            hosted_key_loader=lambda: "hosted-test-key",
            budget_ledger=BudgetLedger(tmp_path / "budget.sqlite3"),
            client=client,
        )
        local = adapter.complete(MESSAGES, purpose="generate")
        hosted = adapter.complete(MESSAGES, purpose="critic")
    assert seen == [
        ("http://127.0.0.1:8089/v1/chat/completions", "Bearer local-test-key"),
        (BASE_URL + "/chat/completions", "Bearer hosted-test-key"),
    ]
    assert local.billing is None and hosted.billing["state"] == "settled"


@pytest.mark.parametrize("status", [301, 307, 401, 429, 500])
def test_errors_and_redirects_retain_reservation_without_retry(tmp_path, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, text="do-not-print-secret", headers={"location": "https://evil.example"}
        )

    adapter, client, ledger = make_adapter(tmp_path, handler)
    try:
        result = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    assert len(requests) == 1
    assert result.billing["state"] == "uncertain"
    assert ledger.snapshot()["accounted_usd"] == result.billing["reserved_usd"]
    assert "secret" not in repr(result)


def test_timeout_keeps_full_reservation_across_restart(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("private request details", request=request)

    adapter, client, ledger = make_adapter(tmp_path, handler)
    try:
        result = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    assert result.request_sent and not result.usage_known
    assert result.billing["state"] == "uncertain"
    assert BudgetLedger(ledger.path).snapshot()["accounted_usd"] == result.billing["reserved_usd"]
    assert "private request" not in repr(result)


@pytest.mark.parametrize("change", ["model", "tier", "output", "input"])
def test_provider_mismatch_freezes_further_spend(tmp_path, change):
    body = response_body()
    if change == "model":
        body["model"] = "different-model"
    if change == "tier":
        body["service_tier"] = "priority"
    if change == "output":
        body["usage"]["completion_tokens"] = 5000
    if change == "input":
        body["usage"]["prompt_tokens"] = input_token_bound(MESSAGES) + 1
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=body)

    adapter, client, ledger = make_adapter(tmp_path, handler)
    try:
        first = adapter.complete(MESSAGES, purpose="critic")
        second = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    assert first.billing["state"] == "overrun" and first.error
    assert ledger.snapshot()["frozen"]
    assert second.request_sent is False and len(seen) == 1


def test_missing_usage_keeps_unknown_cost_distinct_from_reported_tokens(tmp_path):
    body = response_body()
    body.pop("usage")
    adapter, client, ledger = make_adapter(tmp_path, lambda _: httpx.Response(200, json=body))
    try:
        result = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    usage = usage_for([(result, False)])
    assert not result.usage_known and usage["cost_known"] is False
    assert usage["estimated_cost_usd"] is None
    assert usage["actual_accounted_cost_usd"] == result.billing["reserved_usd"]
    assert not ledger.snapshot()["frozen"]


def test_malformed_content_keeps_observed_usage_and_cost(tmp_path):
    body = response_body()
    body["choices"] = []
    adapter, client, _ = make_adapter(tmp_path, lambda _: httpx.Response(200, json=body))
    try:
        result = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    assert result.error and result.usage_known
    assert result.prompt_tokens == 100 and result.completion_tokens == 20
    assert result.billing["state"] == "settled"


def test_shared_initial_cost_is_attributed_but_not_double_charged(tmp_path):
    adapter, client, ledger = make_adapter(
        tmp_path, lambda _: httpx.Response(200, json=response_body())
    )
    try:
        initial = adapter.complete(MESSAGES, purpose="generate")
        review = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    usage = usage_for([(initial, True), (review, False)])
    assert usage["paid_calls"] == 2 and usage["actual_paid_calls"] == 1
    assert usage["accounted_cost_usd"] == 2 * initial.billing["accounted_usd"]
    assert usage["actual_accounted_cost_usd"] == review.billing["accounted_usd"]
    assert ledger.snapshot()["reservations"] == 2


def test_private_key_file_and_environment_without_real_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    key = tmp_path / "fake-key"
    key.write_text("fake-key-for-test\n")
    key.chmod(0o600)
    assert load_openai_key(key) == "fake-key-for-test"
    key.chmod(0o644)
    with pytest.raises(BudgetError, match="private"):
        load_openai_key(key)
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(BudgetError):
        load_openai_key(link)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-fake")
    assert load_openai_key(tmp_path / "missing") == "environment-fake"


def test_budget_status_never_reads_key_and_ignores_per_run_reset_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("ANSWER_LAB_BUDGET_DB", str(tmp_path / "unused-reset.sqlite3"))
    adapter = OpenAIAdapter(
        base_url=BASE_URL,
        model=MODEL,
        enable_paid=True,
        hosted_key_loader=lambda: pytest.fail("Do not inspect credentials"),
    )
    assert adapter.budget_status()["ceiling_usd"] == 1.5
    assert (tmp_path / ".config/agentproof/hosted-budget.sqlite3").exists()
    assert not (tmp_path / "unused-reset.sqlite3").exists()


def test_key_failure_does_not_consume_budget_or_expose_error(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")

    def failure():
        raise BudgetError("secret material must not be returned")

    adapter = OpenAIAdapter(
        base_url=BASE_URL,
        model=MODEL,
        enable_paid=True,
        hosted_key_loader=failure,
        budget_ledger=ledger,
    )
    result = adapter.complete(MESSAGES, purpose="critic")
    assert not result.request_sent
    assert result.blocked_reason == "credentials"
    assert "secret material" not in result.error
    assert ledger.snapshot()["reservations"] == 0


def test_exhaustion_blocks_before_http(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.sqlite3", ceiling_nanodollars=1)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("No request allowed"))
    ) as client:
        adapter = OpenAIAdapter(
            base_url=BASE_URL,
            model=MODEL,
            enable_paid=True,
            hosted_key_loader=lambda: "fake",
            budget_ledger=ledger,
            client=client,
        )
        result = adapter.complete(MESSAGES, purpose="critic")
    assert not result.request_sent and ledger.snapshot()["reservations"] == 0
    assert result.blocked_reason == "budget_exhausted"


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "user", "content": [{"type": "image"}]}],
        [{"role": "user", "content": "text", "tools": []}],
        [{"role": "tool", "content": "text"}],
    ],
)
def test_non_text_or_unpriced_request_forms_blocked(messages):
    with pytest.raises(BudgetError):
        input_token_bound(messages)


def test_utf8_bytes_are_counted_and_framing_is_reserved():
    content = [{"role": "user", "content": "தமிழ் 🌱"}]
    encoded = len(json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode())
    assert input_token_bound(content) == encoded + 2048 + 256
