"""Regression tests for abstention semantics and actionable strict JSON feedback."""

import json

import pytest

from agentproof.answers import AnswerRequest, AnswerService, ModelResponse
from agentproof.answers.models import DuplicateJSONKeyError, parse_json


class NoEmbeddings:
    name = "test-disabled"
    status = "unavailable"

    def encode(self, texts):
        return None


class IdenticalEmbeddings:
    name = "test-identical"
    status = "injected"

    def encode(self, texts):
        return [[1., 0.] for _ in texts]


class Adapter:
    model = "deterministic-correction-test"
    configured = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def configuration(self):
        return {"model": self.model, "revision": "fixture"}

    def complete(self, messages, *, purpose):
        self.calls.append((purpose, messages))
        reply = self.replies.pop(0)
        return reply if isinstance(reply, ModelResponse) else ModelResponse(
            json.dumps(reply), 12, 8, 1, "stop", True)


def abstention(**overrides):
    return {"answer": "", "data": None, "abstained": True, "citations": [], **overrides}


def critique(**overrides):
    return {"supported": False, "responsive": False, "answerable": False,
            "feedback": "The source does not establish the requested closing date.", **overrides}


def request(**kwargs):
    return AnswerRequest(question="When did the service close?", sources=[{
        "id": "doc", "title": "Service", "text": "The service opened in 2023."}], **kwargs)


def service(tmp_path, replies, embeddings=None):
    return AnswerService(tmp_path / "answers.sqlite3", Adapter(replies), embeddings or NoEmbeddings())


def test_no_answer_verdict_accepts_valid_abstention_without_repeated_generation(tmp_path):
    runtime = service(tmp_path, [abstention(), critique()])
    output = runtime.run(request())
    assert output["status"] == "abstained"
    assert len(output["attempts"]) == 1
    assert output["usage"]["calls"] == 2
    assert output["quality"]["score"] == 1
    semantic_checks = [c for c in output["quality"]["checks"] if c["name"].startswith("critic_")]
    assert [c["name"] for c in semantic_checks] == ["critic_answerability"]
    assert semantic_checks[0]["passed"]
    # Raw boolean verdict is preserved, not silently rewritten as support=true.
    assert output["attempts"][0]["critic"]["supported"] is False
    assert output["attempts"][0]["critic"]["responsive"] is False


@pytest.mark.parametrize("supported,responsive", [(False, False), (True, True), (True, False)])
def test_answerable_source_rejects_abstention_regardless_of_unused_flags(tmp_path, supported, responsive):
    runtime = service(tmp_path, [abstention(), critique(answerable=True, supported=supported, responsive=responsive)])
    output = runtime.run(request(max_attempts=1))
    assert output["status"] == "failed"
    assert any(c["name"] == "critic_answerability" and not c["passed"] for c in output["quality"]["checks"])


@pytest.mark.parametrize("missing", ["supported", "responsive", "answerable", "feedback"])
def test_incomplete_critic_cannot_approve_abstention(tmp_path, missing):
    review = critique()
    del review[missing]
    output = service(tmp_path, [abstention(), review]).run(request(max_attempts=1))
    assert output["status"] == "failed"
    assert output["attempts"][0]["critic"] is None
    assert any(c["name"] == "critic" and not c["passed"] for c in output["quality"]["checks"])


@pytest.mark.parametrize("review", [
    ModelResponse("not-json", 12, 8, 1, "stop", True),
    ModelResponse(json.dumps(critique()), 12, 8, 1, "length", True),
    ModelResponse("", error="Inference transport or response error"),
    {"supported": False, "responsive": False, "answerable": "false", "feedback": "Unknown."},
])
def test_invalid_or_incomplete_review_never_passes_abstention(tmp_path, review):
    output = service(tmp_path, [abstention(), review]).run(request(max_attempts=1))
    assert output["status"] == "failed"
    assert not all(c["passed"] for c in output["quality"]["checks"])


@pytest.mark.parametrize("candidate", [
    abstention(answer="2023"), abstention(data={"year": 2023}),
    abstention(citations=[{"source_id": "doc", "quote": "The service opened in 2023."}]),
    {"answer": "", "data": None, "citations": []},
])
def test_malformed_or_nonexplicit_abstention_fails_before_critic(tmp_path, candidate):
    runtime = service(tmp_path, [candidate])
    output = runtime.run(request(max_attempts=1))
    assert output["status"] == "failed"
    assert len(runtime.adapter.calls) == 1
    assert output["attempts"][0]["critic"] is None


@pytest.mark.parametrize("failed_field", ["supported", "responsive", "answerable"])
def test_actual_answer_requires_all_three_critic_dimensions(tmp_path, failed_field):
    candidate = {"answer": "2023", "data": None, "abstained": False,
                 "citations": [{"source_id": "doc", "quote": "The service opened in 2023."}]}
    review = critique(supported=True, responsive=True, answerable=True)
    review[failed_field] = False
    runtime = service(tmp_path, [candidate, review])
    req = request(max_attempts=1).model_copy(update={"question": "When did the service open?"})
    assert runtime.run(req)["status"] == "failed"


def test_correct_abstentions_are_not_written_to_exact_or_semantic_cache(tmp_path):
    opened = {"answer": "2023", "data": None, "abstained": False,
              "citations": [{"source_id": "doc", "quote": "The service opened in 2023."}]}
    runtime = service(tmp_path, [opened, critique(supported=True, responsive=True, answerable=True),
                                 critique(), abstention(), critique(),
                                 critique(), abstention(), critique()], IdenticalEmbeddings())
    seed = request().model_copy(update={"question": "When did the service open?"})
    assert runtime.run(seed)["status"] == "accepted"
    for _ in range(2):
        output = runtime.run(request())
        assert output["status"] == "abstained"
        assert output["cache"]["status"] == "miss"
        assert output["cache"]["rejected_candidates"] == 1
        assert output["usage"]["calls"] == 3
    assert len(runtime.adapter.calls) == 8


def test_duplicate_quote_feedback_repairs_json_without_discarding_data(tmp_path):
    malformed = '{"answer":"","data":{"year":2023},"abstained":false,"citations":[{"source_id":"doc","quote":"The service opened","quote":"in 2023."}]}'
    repaired = {"answer": "", "data": {"year": 2023}, "abstained": False,
                "citations": [{"source_id": "doc", "quote": "The service opened in 2023."}]}
    runtime = service(tmp_path, [ModelResponse(malformed, 12, 8, 1, "stop", True), repaired,
                                 critique(supported=True, responsive=True, answerable=True)])
    req = AnswerRequest(question="Extract the opening year.", sources=request().sources,
                        task="extraction", schema={"type": "object", "properties": {
                            "year": {"type": "integer"}}, "required": ["year"],
                            "additionalProperties": False})
    output = runtime.run(req)
    assert output["status"] == "accepted"
    assert output["data"] == {"year": 2023}
    assert output["final_attempt_index"] == 2
    feedback = output["attempts"][0]["feedback"]
    assert "quote field is repeated" in feedback
    assert "separate objects" in feedback
    assert "retain the extracted data" in feedback
    sent = json.loads(runtime.adapter.calls[1][1][-1]["content"])
    assert sent["feedback"] == feedback
    assert sent["previous_candidate"] == malformed


@pytest.mark.parametrize("key", ["quote", "answer", "sensitive_customer_label_12345", "x" * 5000])
def test_duplicate_errors_expose_only_fixed_protocol_field_names(key):
    raw = "{" + json.dumps(key) + ":1," + json.dumps(key) + ":2}"
    with pytest.raises(DuplicateJSONKeyError) as captured:
        parse_json(raw)
    error = captured.value
    assert len(str(error)) < 100
    assert len(error.repair_feedback()) < 350
    if key in {"quote", "answer"}:
        assert error.field_name == key
    else:
        assert error.field_name is None
        assert key not in str(error)
        assert key not in error.repair_feedback()


def test_duplicate_critic_keys_still_fail_strict_review(tmp_path):
    duplicate = '{"supported":false,"responsive":false,"answerable":true,"answerable":false,"feedback":"No answer."}'
    output = service(tmp_path, [abstention(), ModelResponse(duplicate, 12, 8, 1, "stop", True)]).run(request(max_attempts=1))
    assert output["status"] == "failed"
    assert output["attempts"][0]["critic"] is None
