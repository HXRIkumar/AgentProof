"""Independent cascade guards; in-memory adapters only, no keys or network."""

import test_answers_runtime as cache_fixtures
from test_answer_cascade import answer, critique, request, service

from agentproof.answers import ModelResponse


def test_blocked_initial_critic_stops_before_retry_or_paid_escalation(tmp_path):
    blocked = ModelResponse("", error="Budget denied", request_sent=False,
                            blocked_reason="budget_exhausted", model="reviewer-model")
    runtime = service(tmp_path, [answer(), blocked, answer(), critique()])
    result = runtime.run(request(max_attempts=2))
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "critic"]
    assert result["status"] == "failed"
    assert result["usage"]["actual_calls"] == 1
    assert result["usage"]["blocked_calls"] == 1
    assert result["escalation"]["sent_calls"] == 0


def test_successful_second_local_attempt_exits_before_last_attempt_route(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer(), critique()])
    result = runtime.run(request(max_attempts=3))
    assert result["status"] == "accepted"
    assert result["final_attempt_index"] == 2
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "refine", "critic"]
    assert result["escalation"]["attempts"] == 0


def test_failed_escalation_cannot_replace_better_earlier_candidate(tmp_path):
    runtime = service(tmp_path, [answer(), critique(responsive=False), answer("2024")])
    result = runtime.run(request(max_attempts=2))
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "critic", "escalate"]
    assert result["status"] == "failed" and result["answer"] == "2023"
    assert result["final_attempt_index"] == 1
    assert result["attempts"][0]["generation"]["model"] == "draft-model"
    assert result["attempts"][1]["generation"]["model"] == "reviewer-model"
    assert result["usage"]["calls"] == 3


def test_blocked_semantic_verification_stops_before_fresh_generation(tmp_path):
    blocked = ModelResponse("", error="Budget denied", request_sent=False,
                            blocked_reason="budget_exhausted", model="reviewer-model")
    runtime = cache_fixtures.service(
        tmp_path, [cache_fixtures.answer(), cache_fixtures.critic(), blocked,
                   cache_fixtures.answer(), cache_fixtures.critic()],
        cache_fixtures.ConstantEmbeddings(),
    )
    seed = runtime.run(cache_fixtures.request())
    assert seed["status"] == "accepted"
    paraphrase = cache_fixtures.request().model_copy(
        update={"question": "In which year was the service launched?"}
    )
    result = runtime.run(paraphrase)
    assert [purpose for purpose, _ in runtime.adapter.calls] == ["generate", "critic", "critic"]
    assert result["status"] == "error" and result["cache"]["status"] == "verification_blocked"
    assert result["answer"] == "" and result["attempts"] == []
    assert result["usage"]["actual_calls"] == 0 and result["usage"]["blocked_calls"] == 1
    assert result["cache"]["verification"]["response"]["blocked_reason"] == "budget_exhausted"
    assert result["quality"]["checks"] and any(
        not check["passed"] for check in result["quality"]["checks"]
    )
    assert runtime.run(cache_fixtures.request())["cache"]["status"] == "exact_hit"
    assert len(runtime.adapter.calls) == 3
