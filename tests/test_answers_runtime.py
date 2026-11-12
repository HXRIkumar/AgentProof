import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentproof.answers import (
    AnswerRequest,
    AnswerService,
    ModelResponse,
    OpenAIAdapter,
    RuntimeBusy,
    create_router,
)
from agentproof.answers.models import parse_json
from agentproof.answers.retrieval import cosine, critical_signature, retrieve


class NoEmbeddings:
    name = "disabled-for-test"

    def encode(self, texts):
        return None


class ConstantEmbeddings:
    name = "test-vector"

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


class Adapter:
    model = "test-model"
    configured = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def configuration(self):
        return {"model": self.model, "revision": "test"}

    def complete(self, messages, *, purpose):
        self.calls.append((purpose, messages))
        response = self.responses.pop(0)
        if isinstance(response, ModelResponse):
            return response
        return ModelResponse(json.dumps(response), 20, 10, 5, "stop", True)


def answer(text="2023", quote="The service launched in 2023.", **kwargs):
    return {
        "answer": text,
        "data": None,
        "abstained": False,
        "citations": [{"source_id": "doc", "quote": quote}],
        **kwargs,
    }


def critic(**kwargs):
    return {
        "supported": True,
        "responsive": True,
        "answerable": True,
        "feedback": "The answer is directly supported.",
        **kwargs,
    }


def request(**kwargs):
    return AnswerRequest(
        question="When did the service launch?",
        sources=[
            {
                "id": "doc",
                "title": "Launch",
                "text": "The service launched in 2023. Revenue was 50.",
            }
        ],
        **kwargs,
    )


def service(tmp_path, responses, embedder=None):
    return AnswerService(tmp_path / "answers.db", Adapter(responses), embedder or NoEmbeddings())


def test_adaptive_accepts_only_after_accounted_critic(tmp_path):
    runtime = service(tmp_path, [answer(), critic()])
    result = runtime.run(request())
    assert result["status"] == "accepted"
    assert result["usage"] == {
        "calls": 2,
        "actual_calls": 2,
        "reused_calls": 0,
        "prompt_tokens": 40,
        "completion_tokens": 20,
        "total_tokens": 60,
        "actual_total_tokens": 60,
        "known": True,
        "unknown_calls": 0,
    }
    assert result["quality"]["score"] == 1
    assert "not probability" in result["quality"]["label"]
    assert runtime.store.get(result["id"]) == result
    assert [x[0] for x in runtime.adapter.calls] == ["generate", "critic"]


def test_deterministic_feedback_repairs_without_unnecessary_critic(tmp_path):
    runtime = service(tmp_path, [answer("2024"), answer(), critic()])
    result = runtime.run(request())
    assert result["answer"] == "2023"
    assert result["retries"] == 1
    assert result["usage"]["calls"] == 3
    assert [x[0] for x in runtime.adapter.calls] == ["generate", "refine", "critic"]
    refinement = json.loads(runtime.adapter.calls[1][1][1]["content"])
    assert "exact span" in refinement["feedback"]
    assert refinement["previous_candidate"]["answer"] == "2024"


def test_semantically_wrong_span_receives_critic_correction(tmp_path):
    runtime = service(
        tmp_path,
        [
            answer("50", "Revenue was 50."),
            critic(responsive=False, feedback="Question asks for launch year."),
            answer(),
            critic(),
        ],
    )
    result = runtime.run(request())
    assert result["answer"] == "2023"
    assert result["usage"]["calls"] == 4
    assert result["final_attempt_index"] == 2
    assert result["attempts"][0]["critic"]["responsive"] is False


def test_worse_refinement_does_not_replace_valid_original(tmp_path):
    runtime = service(tmp_path, [answer(), critic(responsive=False), answer("never", "fake")])
    result = runtime.run(request(max_attempts=2))
    assert result["status"] == "failed"
    assert result["final_attempt_index"] == 1
    assert result["answer"] == "2023"
    assert len(result["attempts"]) == 2


@pytest.mark.parametrize("strategy,expected_calls", [("baseline", 1), ("validated", 1)])
def test_nonadaptive_does_not_invent_critic_or_cache(tmp_path, strategy, expected_calls):
    runtime = service(tmp_path, [answer()])
    result = runtime.run(request(strategy=strategy))
    assert result["status"] == "accepted"
    assert result["usage"]["calls"] == expected_calls
    assert result["cache"]["status"] == "disabled"
    assert result["attempts"][0]["critic"] is None
    assert not runtime.store.candidates("ignored", 86400)


def test_shared_initial_has_separate_actual_and_logical_cost(tmp_path):
    runtime = service(tmp_path, [answer(), critic()])
    req = request(use_cache=False)
    initial = runtime.generate_initial(req)
    baseline = runtime.run(
        req.model_copy(update={"strategy": "baseline"}), initial_response=initial, persist=False
    )
    adaptive = runtime.run(req, initial_response=initial, persist=False)
    assert len(runtime.adapter.calls) == 2
    assert baseline["usage"]["calls"] == 1
    assert baseline["usage"]["actual_calls"] == 0
    assert adaptive["usage"]["calls"] == 2
    assert adaptive["usage"]["actual_calls"] == 1
    assert adaptive["usage"]["total_tokens"] == 60
    assert adaptive["usage"]["actual_total_tokens"] == 30
    assert adaptive["latency_ms"] >= adaptive["wall_latency_ms"] + 4.9
    assert runtime.store.recent() == []


def test_shared_initial_rejects_other_input(tmp_path):
    runtime = service(tmp_path, [answer()])
    initial = runtime.generate_initial(request())
    with pytest.raises(ValueError, match="does not match"):
        runtime.run(
            request().model_copy(update={"question": "What is revenue?"}), initial_response=initial
        )


def test_explicit_abstention_requires_critic_agreement(tmp_path):
    abstention = {"answer": "", "data": None, "abstained": True, "citations": []}
    runtime = service(tmp_path, [abstention, critic(answerable=False)])
    result = runtime.run(request())
    assert result["status"] == "abstained"
    assert result["abstained"] is True
    runtime.adapter.responses = [abstention, critic(answerable=False)]
    second = runtime.run(request())
    assert second["cache"]["status"] == "miss"


def test_malformed_empty_output_is_not_abstention(tmp_path):
    runtime = service(tmp_path, [ModelResponse("", 2, 0, 1, "stop", True)])
    result = runtime.run(request(strategy="baseline"))
    assert result["status"] == "failed"
    assert not result["abstained"]


def test_unknown_critic_usage_is_preserved(tmp_path):
    runtime = service(tmp_path, [answer(), ModelResponse("", error="Inference HTTP 500")])
    result = runtime.run(request(max_attempts=1))
    assert result["status"] == "failed"
    assert result["usage"]["calls"] == 2
    assert not result["usage"]["known"]
    assert result["usage"]["unknown_calls"] == 1
    assert result["attempts"][0]["critic_response"]["error"] == "Inference HTTP 500"


def test_exact_cache_hits_without_model_and_with_source_identity(tmp_path):
    runtime = service(tmp_path, [answer(), critic()])
    first = runtime.run(request())
    second = runtime.run(request())
    assert second["cache"]["status"] == "exact_hit"
    assert second["cache"]["source_run_id"] == first["id"]
    assert second["usage"]["calls"] == 0
    assert second["attempts"] == []
    assert second["answer"] == first["answer"]
    assert len(runtime.adapter.calls) == 2


@pytest.mark.parametrize("change", ["namespace", "source", "model"])
def test_cache_isolation(tmp_path, change):
    runtime = service(tmp_path, [answer(), critic(), answer(), critic()])
    runtime.run(request())
    req = request()
    if change == "namespace":
        req = request(namespace="other")
    elif change == "source":
        req.sources[0].text += " Updated."
    else:
        runtime.adapter.model = "another-model"
    result = runtime.run(req)
    assert result["cache"]["status"] == "miss"
    assert result["usage"]["calls"] == 2


def test_semantic_cache_requires_fresh_critic(tmp_path):
    runtime = service(tmp_path, [answer(), critic(), critic()], ConstantEmbeddings())
    runtime.run(request())
    req = request().model_copy(update={"question": "In which year was the service launched?"})
    result = runtime.run(req)
    assert result["cache"]["status"] == "semantic_hit"
    assert result["usage"]["calls"] == 1
    assert result["cache"]["verification"]["critic"]["responsive"] is True
    assert [x[0] for x in runtime.adapter.calls] == ["generate", "critic", "critic"]


def test_semantic_false_candidate_rejected_and_new_answer_generated(tmp_path):
    runtime = service(
        tmp_path,
        [answer(), critic(), critic(responsive=False), answer("50", "Revenue was 50."), critic()],
        ConstantEmbeddings(),
    )
    runtime.run(request())
    req = request().model_copy(update={"question": "What revenue did the service earn?"})
    result = runtime.run(req)
    assert result["cache"]["status"] == "miss"
    assert result["cache"]["rejected_candidates"] == 1
    assert result["answer"] == "50"
    assert result["usage"]["calls"] == 3


def test_cache_negation_mismatch_does_not_call_verifier(tmp_path):
    runtime = service(tmp_path, [answer(), critic(), answer(), critic()], ConstantEmbeddings())
    runtime.run(request())
    req = request().model_copy(update={"question": "When did the service not launch?"})
    result = runtime.run(req)
    assert result["cache"]["rejected_candidates"] == 1
    assert result["usage"]["calls"] == 2


def test_cache_expiry(tmp_path):
    runtime = service(tmp_path, [answer(), critic(), answer(), critic()])
    runtime.run(request())
    with runtime.store.connect() as db:
        db.execute("UPDATE answer_cache SET created_at=0")
    assert runtime.run(request())["cache"]["status"] == "miss"


def test_cache_does_not_cross_embedding_availability(tmp_path):
    class StatefulEmbeddings(ConstantEmbeddings):
        status = "loaded"

    embedder = StatefulEmbeddings()
    runtime = service(tmp_path, [answer(), critic(), answer(), critic()], embedder)
    runtime.run(request())
    embedder.status = "unavailable"
    assert runtime.run(request())["cache"]["status"] == "miss"


def test_exact_cache_timing_includes_populating_write(tmp_path, monkeypatch):
    import time

    runtime = service(tmp_path, [answer(), critic()])
    original = runtime.store.cache

    def slow_cache(*args):
        time.sleep(0.015)
        return original(*args)

    monkeypatch.setattr(runtime.store, "cache", slow_cache)
    assert runtime.run(request())["latency_ms"] >= 15


def test_explicit_empty_provider_configuration_does_not_use_environment(monkeypatch):
    monkeypatch.setenv("ANSWER_LAB_BASE_URL", "http://localhost/v1")
    monkeypatch.setenv("ANSWER_LAB_MODEL", "elsewhere")
    assert not OpenAIAdapter(base_url="", model="").configured
    with pytest.raises(ValueError):
        OpenAIAdapter(timeout=0)
    with pytest.raises(ValueError):
        OpenAIAdapter(max_tokens=0)


def test_failed_outputs_never_cached(tmp_path):
    runtime = service(tmp_path, [answer(), critic(responsive=False), answer(), critic()])
    runtime.run(request(max_attempts=1))
    result = runtime.run(request())
    assert result["cache"]["status"] == "miss"


def test_extraction_schema_feedback_and_repair(tmp_path):
    schema = {
        "type": "object",
        "properties": {"year": {"type": "integer"}},
        "required": ["year"],
        "additionalProperties": False,
    }
    wrong = answer("", data={"year": "2023"})
    correct = answer("", data={"year": 2023})
    runtime = service(tmp_path, [wrong, correct, critic()])
    req = request(task="extraction", schema=schema)
    result = runtime.run(req)
    assert result["data"] == {"year": 2023}
    assert result["retries"] == 1
    assert "year: type" in result["attempts"][0]["feedback"]


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "http://127.0.0.1:9999/private"},
        {"type": "object", "properties": {"field": {"$dynamicRef": "#a"}}},
        {"type": "string", "pattern": "(a+)+$"},
        {"type": "made-up"},
    ],
)
def test_unsafe_or_invalid_schema_is_rejected(schema):
    with pytest.raises(ValidationError):
        request(task="extraction", schema=schema)


def test_gold_cannot_enter_runtime_request():
    with pytest.raises(ValidationError):
        request(expected_answer="2023")


@pytest.mark.parametrize("bad", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}'])
def test_duplicate_and_nonfinite_json_rejected(bad):
    with pytest.raises(ValueError):
        parse_json(bad)


def test_truncated_json_not_accepted_even_if_parseable(tmp_path):
    response = ModelResponse(json.dumps(answer()), 20, 10, 1, "length", True)
    runtime = service(tmp_path, [response])
    result = runtime.run(request(strategy="baseline"))
    assert result["status"] == "failed"
    assert result["attempts"][0]["generation"]["finish_reason"] == "length"


def test_lexical_fallback_and_selected_passages_are_explicit():
    req = request()
    retrieved = retrieve(req.question, req.sources, NoEmbeddings())
    assert retrieved["method"] == "bm25"
    assert retrieved["embedding_model"] is None
    assert retrieved["selected"][0]["source_id"] == "doc"


def test_hybrid_retrieval_and_invalid_vectors():
    req = request()
    retrieved = retrieve(req.question, req.sources, ConstantEmbeddings())
    assert retrieved["method"] == "hybrid_bm25_embeddings"
    assert retrieved["selected"][0]["semantic_score"] == 1
    assert cosine([1], [1, 2]) == 0
    assert cosine([float("nan")], [1]) == 0
    assert critical_signature("Before 2023?") != critical_signature("After 2023?")


def test_service_rejects_parallel_execution(tmp_path):
    runtime = service(tmp_path, [])
    runtime._lock.acquire()
    try:
        with pytest.raises(RuntimeBusy):
            runtime.run(request())
        with pytest.raises(RuntimeBusy):
            runtime.generate_initial(request())
    finally:
        runtime._lock.release()


def test_unconfigured_api_returns_actual_error_not_demo(tmp_path):
    runtime = AnswerService(
        tmp_path / "answers.db", OpenAIAdapter(base_url="", model=""), NoEmbeddings()
    )
    result = runtime.run(request())
    assert result["status"] == "error"
    assert result["usage"]["calls"] == 0


def test_routes_history_report_and_reject_gold(tmp_path):
    runtime = service(tmp_path, [answer(), critic()])
    app = FastAPI()
    app.include_router(create_router(runtime, tmp_path / "reports"))
    with TestClient(app) as client:
        result = client.post("/api/answers/run", json=request().model_dump(by_alias=True)).json()
        assert client.get("/api/answers/runs").json()[0]["id"] == result["id"]
        assert client.get(f"/api/answers/runs/{result['id']}").json() == result
        assert client.get("/api/answers/runs/missing").status_code == 404
        assert client.get("/api/answers/reports").json() == []
        assert client.get("/api/answers/reports/not-there").status_code == 404
        body = request().model_dump(by_alias=True)
        body["expected_answer"] = "2023"
        assert client.post("/api/answers/run", json=body).status_code == 422


def test_adapter_accounts_usage_and_uses_separate_purposes():
    seen = []

    def handle(req):
        seen.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = OpenAIAdapter(
            base_url="http://localhost:8089/v1", model="local", client=client, disable_thinking=True
        )
        response = adapter.complete([{"role": "user", "content": "hello"}], purpose="critic")
    assert response.usage_known and response.prompt_tokens == 4
    assert seen[0]["temperature"] == 0
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_critic_can_use_different_model_budget_and_thinking_same_endpoint():
    seen = []

    def handle(req):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = OpenAIAdapter(
            base_url="http://localhost:8089/v1",
            model="draft",
            client=client,
            max_tokens=512,
            disable_thinking=True,
            critic_model="reviewer",
            critic_max_tokens=2048,
            critic_disable_thinking=False,
        )
        initial = adapter.complete([], purpose="generate")
        review = adapter.complete([], purpose="critic")
    assert seen[0][0] == seen[1][0] == "http://localhost:8089/v1/chat/completions"
    assert seen[0][1]["model"] == initial.model == "draft"
    assert seen[0][1]["max_tokens"] == 512
    assert seen[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[1][1]["model"] == review.model == "reviewer"
    assert seen[1][1]["max_tokens"] == 2048
    assert seen[1][1]["chat_template_kwargs"] == {"enable_thinking": True}
    assert adapter.configuration()["critic_thinking_override"] is True


def test_critic_defaults_match_generator_and_config_changes_are_fingerprinted(tmp_path):
    base = OpenAIAdapter(
        base_url="http://localhost/v1", model="draft", max_tokens=512, disable_thinking=True
    )
    assert base.critic_model == base.model
    assert base.critic_max_tokens == base.max_tokens
    assert base.critic_disable_thinking == base.disable_thinking
    other = OpenAIAdapter(
        base_url="http://localhost/v1",
        model="draft",
        max_tokens=512,
        disable_thinking=True,
        critic_max_tokens=2048,
    )
    left = AnswerService(tmp_path / "a.db", base, NoEmbeddings())
    right = AnswerService(tmp_path / "b.db", other, NoEmbeddings())
    assert left.configuration() != right.configuration()


def test_critic_environment_override_is_explicit(monkeypatch):
    monkeypatch.setenv("ANSWER_LAB_CRITIC_MODEL", "critic-local")
    monkeypatch.setenv("ANSWER_LAB_CRITIC_MAX_TOKENS", "2048")
    monkeypatch.setenv("ANSWER_LAB_CRITIC_DISABLE_THINKING", "false")
    adapter = OpenAIAdapter(base_url="http://localhost/v1", model="draft", disable_thinking=True)
    assert adapter.critic_model == "critic-local"
    assert adapter.critic_max_tokens == 2048
    assert adapter.critic_disable_thinking is False
    assert adapter.configuration()["critic_thinking_override"]


@pytest.mark.parametrize("span", ["23", "he"])
def test_substring_inside_word_or_number_is_not_grounded(tmp_path, span):
    runtime = service(tmp_path, [answer(span)])
    result = runtime.run(request(strategy="baseline"))
    assert result["status"] == "failed"


def test_false_premise_feedback_can_recover_to_explicit_abstention(tmp_path):
    refusal = {"answer": "", "data": None, "abstained": True, "citations": []}
    runtime = service(
        tmp_path,
        [
            answer(),
            critic(
                supported=False,
                responsive=False,
                answerable=False,
                feedback="The source gives a launch, not a closure.",
            ),
            refusal,
            critic(answerable=False),
        ],
    )
    req = request().model_copy(update={"question": "When did the service close?"})
    result = runtime.run(req)
    assert result["status"] == "abstained"
    assert result["usage"]["calls"] == 4
    refinement = json.loads(runtime.adapter.calls[2][1][1]["content"])
    assert "not a closure" in refinement["feedback"]
    assert refinement["previous_candidate"]["answer"] == "2023"


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 2},
        {"prompt_tokens": 2},
        {"prompt_tokens": -1, "completion_tokens": 2},
    ],
)
def test_adapter_missing_or_invalid_usage_is_unknown(usage):
    def handle(req):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": usage,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        response = OpenAIAdapter(
            base_url="http://localhost/v1", model="test", client=client
        ).complete([], purpose="generate")
    assert not response.usage_known
    assert response.prompt_tokens is None


def test_provider_does_not_leak_error_body_or_api_key():
    def handle(req):
        return httpx.Response(401, text="private-secret-key")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        response = OpenAIAdapter(
            base_url="http://localhost/v1", model="test", api_key="top-secret", client=client
        ).complete([], purpose="generate")
    assert response.error == "Inference HTTP 401"
    assert "secret" not in repr(response)


@pytest.mark.parametrize("field,value", [("usage", [10]), ("finish_reason", {})])
def test_adapter_malformed_metadata_is_bounded(field, value):
    body = {
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1},
    }
    if field == "usage":
        body["usage"] = value
    else:
        body["choices"][0][field] = value
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        response = OpenAIAdapter(
            base_url="http://localhost/v1", model="test", client=client
        ).complete([], purpose="generate")
    assert not response.usage_known
    if field == "finish_reason":
        assert response.error
