"""Selective final-generation routing. Fixtures and mock HTTP only; no model calls."""

import json

import httpx
import pytest

from agentproof.answers import AnswerRequest, AnswerService, ModelResponse, OpenAIAdapter
from agentproof.answers.hosted_budget import BASE_URL, MODEL, BudgetLedger


class NoEmbedding:
    name = "test-lexical"

    def encode(self, texts):
        return None


class Adapter:
    model = "draft-model"
    critic_model = "reviewer-model"
    configured = True
    has_distinct_critic = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def configuration(self):
        return {
            "model": self.model,
            "critic_model": self.critic_model,
            "has_distinct_critic": self.has_distinct_critic,
        }

    def complete(self, messages, *, purpose):
        self.calls.append((purpose, messages))
        response = self.responses.pop(0)
        if isinstance(response, ModelResponse):
            return response
        return ModelResponse(
            json.dumps(response),
            10,
            5,
            1,
            "stop",
            True,
            model=self.critic_model if purpose in {"critic", "escalate"} else self.model,
        )


def answer(value="2023"):
    return {
        "answer": value,
        "data": None,
        "abstained": False,
        "citations": [{"source_id": "record", "quote": "The product opened in 2023."}],
    }


def critique(**values):
    return {
        "supported": True,
        "responsive": True,
        "answerable": True,
        "feedback": "The year directly answers the question.",
        **values,
    }


def request(**values):
    return AnswerRequest(
        question="When did the product open?",
        sources=[{"id": "record", "text": "The product opened in 2023."}],
        use_cache=False,
        **values,
    )


def service(tmp_path, responses, *, enabled=True, distinct=True):
    adapter = Adapter(responses)
    adapter.has_distinct_critic = distinct
    return AnswerService(
        tmp_path / "answers.sqlite3", adapter, NoEmbedding(), escalate_final=enabled
    )


def test_first_pass_success_never_escalates(tmp_path):
    runtime = service(tmp_path, [answer(), critique()])
    result = runtime.run(request())
    assert result["status"] == "accepted"
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "critic"]
    assert result["escalation"]["attempts"] == result["escalation"]["sent_calls"] == 0


def test_last_attempt_only_uses_critic_route_and_still_gets_review(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer("2025"), answer(), critique()])
    result = runtime.run(request(max_attempts=3))
    assert [purpose for purpose, _ in runtime.adapter.calls] == [
        "generate",
        "refine",
        "escalate",
        "critic",
    ]
    assert result["status"] == "accepted"
    assert result["usage"]["calls"] == 4
    assert result["usage"]["total_tokens"] == 60
    assert len(result["attempts"]) == 3
    assert result["attempts"][-1]["generation"]["model"] == "reviewer-model"
    assert result["attempts"][-1]["route"] == "critic_escalation"
    assert "Final permitted" in result["attempts"][-1]["escalation_reason"]
    assert result["escalation"]["sent_calls"] == 1
    # The stronger model is asked to generate a corrected answer, not a critique.
    assert "You answer questions" in runtime.adapter.calls[2][1][0]["content"]
    assert "You review a candidate" in runtime.adapter.calls[3][1][0]["content"]
    feedback = json.loads(runtime.adapter.calls[2][1][1]["content"])
    assert feedback["previous_candidate"]["answer"] == "2025"


@pytest.mark.parametrize(
    "attempts,expected", [(1, ["generate"]), (2, ["generate", "escalate", "critic"])]
)
def test_request_attempt_limit_is_never_increased(tmp_path, attempts, expected):
    runtime = service(tmp_path, [answer("2024"), answer(), critique()])
    result = runtime.run(request(max_attempts=attempts))
    assert [purpose for purpose, _ in runtime.adapter.calls] == expected
    assert len(result["attempts"]) <= attempts
    if attempts == 1:
        assert result["escalation"]["attempts"] == 0


@pytest.mark.parametrize("strategy", ["baseline", "validated"])
def test_other_strategies_never_escalate(tmp_path, strategy):
    runtime = service(tmp_path, [answer("2024"), answer("2025"), answer()])
    result = runtime.run(request(strategy=strategy, max_attempts=3))
    assert "escalate" not in [purpose for purpose, _ in runtime.adapter.calls]
    assert result["escalation"]["attempts"] == 0


@pytest.mark.parametrize("enabled,distinct", [(False, True), (True, False)])
def test_disabled_or_identical_critic_keeps_local_retry_path(tmp_path, enabled, distinct):
    runtime = service(
        tmp_path, [answer("2024"), answer(), critique()], enabled=enabled, distinct=distinct
    )
    result = runtime.run(request(max_attempts=2))
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "refine", "critic"]
    assert result["escalation"]["attempts"] == 0


def test_default_is_off_and_only_explicit_flag_enables_it(tmp_path, monkeypatch):
    monkeypatch.delenv("ANSWER_LAB_ESCALATE_FINAL", raising=False)
    assert not AnswerService(tmp_path / "a.db", Adapter([]), NoEmbedding()).escalate_final
    monkeypatch.setenv("ANSWER_LAB_ESCALATE_FINAL", "true")
    assert not AnswerService(tmp_path / "b.db", Adapter([]), NoEmbedding()).escalate_final
    monkeypatch.setenv("ANSWER_LAB_ESCALATE_FINAL", "1")
    assert AnswerService(tmp_path / "c.db", Adapter([]), NoEmbedding()).escalate_final


def test_escalated_answer_still_requires_deterministic_validation(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer("2025")])
    result = runtime.run(request(max_attempts=2))
    assert result["status"] == "failed"
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "escalate"]
    assert not result["attempts"][-1]["passed"]
    assert result["attempts"][-1]["critic"] is None


def test_escalated_answer_still_requires_critic_acceptance(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer(), critique(responsive=False)])
    result = runtime.run(request(max_attempts=2))
    assert result["status"] == "failed"
    assert result["attempts"][-1]["critic"]["responsive"] is False
    assert result["usage"]["calls"] == 3


def test_critic_rejection_can_trigger_final_generation_escalation(tmp_path):
    runtime = service(tmp_path, [answer(), critique(responsive=False), answer(), critique()])
    result = runtime.run(request(max_attempts=2))
    assert result["status"] == "accepted"
    assert [purpose for purpose, _ in runtime.adapter.calls] == [
        "generate",
        "critic",
        "escalate",
        "critic",
    ]
    assert result["final_attempt_index"] == 2
    assert result["usage"]["calls"] == 4


def test_provider_error_still_stops_without_escalation(tmp_path):
    runtime = service(tmp_path, [ModelResponse("", error="Inference transport error")])
    result = runtime.run(request(max_attempts=3))
    assert result["status"] == "error"
    assert result["escalation"]["attempts"] == 0
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate"]


def test_blocked_budget_retained_as_unsent_attempt_without_extra_review(tmp_path):
    blocked = ModelResponse(
        "",
        error="Budget exhausted",
        request_sent=False,
        blocked_reason="budget_exhausted",
        model=MODEL,
    )
    runtime = service(tmp_path, [answer("2024"), blocked])
    result = runtime.run(request(max_attempts=2))
    assert result["status"] == "failed"
    assert result["escalation"]["attempts"] == 1
    assert result["escalation"]["sent_calls"] == 0
    assert result["usage"]["actual_calls"] == 1
    assert result["usage"]["blocked_calls"] == 1
    assert result["attempts"][-1]["generation"]["blocked_reason"] == "budget_exhausted"
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "escalate"]


def test_shared_initial_stays_shared_and_escalation_adds_only_actual_new_calls(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer(), critique()])
    req = request(max_attempts=2)
    initial = runtime.generate_initial(req)
    baseline = runtime.run(
        req.model_copy(update={"strategy": "baseline"}), initial_response=initial
    )
    adaptive = runtime.run(req, initial_response=initial)
    assert baseline["usage"]["actual_calls"] == 0
    assert adaptive["usage"]["calls"] == 3 and adaptive["usage"]["actual_calls"] == 2
    assert adaptive["attempts"][0]["generation"] == baseline["attempts"][0]["generation"]
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "escalate", "critic"]


def test_policy_flag_participates_in_cache_identity(tmp_path):
    adapter = Adapter([answer(), critique(), answer(), critique()])
    ordinary = AnswerService(tmp_path / "same.db", adapter, NoEmbedding(), escalate_final=False)
    cascade = AnswerService(tmp_path / "same.db", adapter, NoEmbedding(), escalate_final=True)
    req = request().model_copy(update={"use_cache": True})
    first = ordinary.run(req)
    second = cascade.run(req)
    assert first["config_hash"] != second["config_hash"]
    assert second["cache"]["status"] == "miss"


def test_hosted_escalation_uses_critic_pin_budget_and_same_durable_ledger(tmp_path):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "service_tier": "default",
                "choices": [
                    {"message": {"content": json.dumps(answer())}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAIAdapter(
            base_url="http://127.0.0.1:8089/v1",
            model="draft",
            critic_base_url=BASE_URL,
            critic_model=MODEL,
            critic_max_tokens=1536,
            enable_paid=True,
            hosted_key_loader=lambda: "fake-test-key",
            budget_ledger=ledger,
            client=client,
        )
        assert adapter.has_distinct_critic
        output = adapter.complete(
            [{"role": "user", "content": "Return a corrected JSON answer."}], purpose="escalate"
        )
    assert seen[0]["model"] == output.model == MODEL
    assert seen[0]["max_completion_tokens"] == 1536
    assert output.billing["state"] == "settled"
    assert ledger.snapshot()["ceiling_usd"] == 1.5
    assert ledger.snapshot()["reservations"] == 1


def test_same_model_same_endpoint_is_not_a_distinct_route():
    adapter = OpenAIAdapter(base_url="http://localhost/v1", model="one", critic_model="one")
    assert adapter.has_distinct_critic is False
    different = OpenAIAdapter(base_url="http://localhost/v1", model="one", critic_model="two")
    assert different.has_distinct_critic is True
