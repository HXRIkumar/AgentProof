"""Independent runtime checks; deterministic adapters, never model/network calls."""

import json

import pytest

from agentproof.answers import AnswerRequest, AnswerService, ModelResponse
from agentproof.answers.engine import validate_candidate
from agentproof.answers.retrieval import retrieve


class NoEmbeddings:
    name = "independent-disabled"
    status = "unavailable"
    revision = "test"

    def encode(self, texts):
        return None


class Adapter:
    model = "independent-fixture"
    configured = True
    revision = "one"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def configuration(self):
        return {"model": self.model, "revision": self.revision}

    def complete(self, messages, *, purpose):
        self.calls.append(purpose)
        value = self.responses.pop(0)
        return value if isinstance(value, ModelResponse) else ModelResponse(
            json.dumps(value), 11, 7, 4, "stop", True)


def proposal(answer="2023", quote="The service launched in 2023."):
    return {"answer": answer, "data": None, "abstained": False,
            "citations": [{"source_id": "doc", "quote": quote}]}


def review(**kwargs):
    return {"supported": True, "responsive": True, "answerable": True,
            "feedback": "Supported by the cited launch record.", **kwargs}


def request(**kwargs):
    return AnswerRequest(question="When did the service launch?", sources=[{
        "id": "doc", "title": "Record", "text": "The service launched in 2023."}], **kwargs)


def test_quote_spanning_adjacent_retrieved_chunks_is_supported():
    prefix = "padding " * 275  # 2200 chars: quote crosses the fixed 2400-char chunk boundary.
    quote = "The service launched in 2023 with " + "documented launch details " * 14 + "."
    source = prefix + quote + " trailing notes" * 30
    req = AnswerRequest(question="When did the service launch?", sources=[{
        "id": "doc", "title": "Long source", "text": source}])
    retrieval = retrieve(req.question, req.sources, NoEmbeddings())
    assert len(retrieval["selected"]) >= 2
    assert quote in source
    assert not any(quote in p["text"] for p in retrieval["selected"])
    _, checks = validate_candidate(req, ModelResponse(json.dumps(proposal(quote=quote))), retrieval)
    assert next(c["passed"] for c in checks if c["name"] == "citations")


def test_quote_crossing_unretrieved_gap_is_rejected():
    req = AnswerRequest(question="What happened?", sources=[{
        "id": "doc", "title": "Partial", "text": "alpha " + "hidden " * 100 + "omega"}])
    retrieval = {"selected": [
        {"source_id": "doc", "text": "alpha ", "start": 0, "end": 6},
        {"source_id": "doc", "text": "omega", "start": 706, "end": 711},
    ]}
    _, checks = validate_candidate(req, ModelResponse(json.dumps(
        proposal(answer="alpha", quote=req.sources[0].text))), retrieval)
    assert not next(c["passed"] for c in checks if c["name"] == "citations")


def test_whitespace_quote_never_counts_as_extraction_evidence():
    req = AnswerRequest(question="Extract the year.", task="extraction", sources=[{
        "id": "doc", "title": "Record", "text": "The service launched in 2023."}],
        schema={"type": "object", "properties": {"year": {"type": "integer"}},
                "required": ["year"], "additionalProperties": False})
    payload = {"answer": "", "data": {"year": 2023}, "abstained": False,
               "citations": [{"source_id": "doc", "quote": " \n\t "}]}
    _, checks = validate_candidate(req, ModelResponse(json.dumps(payload)),
                                   retrieve(req.question, req.sources, NoEmbeddings()))
    assert not next(c["passed"] for c in checks if c["name"] == "citations")


@pytest.mark.parametrize("mutation", ["namespace", "source", "revision", "prompt"])
def test_exact_cache_invalidates_semantic_dependencies(tmp_path, monkeypatch, mutation):
    adapter = Adapter([proposal(), review(), proposal(), review()])
    service = AnswerService(tmp_path / "answer.db", adapter, NoEmbeddings())
    first = service.run(request(), persist=False)
    assert first["status"] == "accepted"
    unchanged = service.run(request(), persist=False)
    assert unchanged["cache"]["status"] == "exact_hit"
    assert unchanged["usage"]["calls"] == 0
    new_request = request()
    if mutation == "namespace":
        new_request = request(namespace="different")
    elif mutation == "source":
        new_request = request()
        new_request.sources[0].text += " New evidence was added."
    elif mutation == "revision":
        adapter.revision = "two"
    elif mutation == "prompt":
        monkeypatch.setattr("agentproof.answers.engine.PROMPT_HASH", "changed-prompt")
    changed = service.run(new_request, persist=False)
    assert changed["cache"]["status"] == "miss"
    assert changed["usage"]["calls"] == 2


def test_best_failed_candidate_keeps_its_own_checks_and_index(tmp_path):
    bad_json = ModelResponse("not json", 5, 5, 2, "stop", True)
    adapter = Adapter([proposal(), review(responsive=False), bad_json])
    service = AnswerService(tmp_path / "answer.db", adapter, NoEmbeddings())
    output = service.run(request(max_attempts=2, use_cache=False), persist=False)
    assert output["status"] == "failed"
    assert output["answer"] == "2023"
    assert output["final_attempt_index"] == 1
    assert output["quality"]["checks"] == output["attempts"][0]["checks"]
    assert output["attempts"][1]["answer"] == ""
    assert output["usage"]["calls"] == 3


def test_critic_parse_failure_is_not_cached_and_shared_latency_is_attributed(tmp_path):
    bad_critic = ModelResponse("invalid review", 4, 4, 3, "stop", True)
    adapter = Adapter([proposal(), bad_critic, proposal(), review()])
    service = AnswerService(tmp_path / "answer.db", adapter, NoEmbeddings())
    failed = service.run(request(max_attempts=1), persist=False)
    assert failed["status"] == "failed"
    succeeding = service.run(request(max_attempts=1), persist=False)
    assert succeeding["cache"]["status"] == "miss"
    assert succeeding["status"] == "accepted"
    second_adapter = Adapter([proposal(), review()])
    second = AnswerService(tmp_path / "shared.db", second_adapter, NoEmbeddings())
    initial = second.generate_initial(request())
    shared = second.run(request(), initial_response=initial, persist=False)
    assert shared["usage"]["reused_calls"] == 1
    assert shared["usage"]["actual_calls"] == 1
    assert shared["usage"]["calls"] == 2
    assert shared["latency_ms"] - shared["wall_latency_ms"] == pytest.approx(initial.latency_ms)
