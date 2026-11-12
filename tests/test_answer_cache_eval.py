"""Cache evidence regrading, plan integrity, negatives, and honest denominators."""

import copy
import hashlib
import json

import pytest

from agentproof.answer_cache_eval import CacheEvidenceError, expected_request, summarize_cache
from agentproof.answer_eval import evidence_digest

CONFIG = {"provider": {"model": "unit-test-fixture", "revision": "test"}, "prompt_hash": "test"}


def response(known=True):
    return {"text": "fixture", "prompt_tokens": 12 if known else None,
            "completion_tokens": 8 if known else None, "usage_known": known,
            "latency_ms": 1, "finish_reason": "stop", "request_hash": "test", "error": None}


def row(group, question, references, run_id, *, cache="miss", answer="2024", origin=None,
        elapsed=1000, known=True):
    req = expected_request(group, question)
    calls = 0 if cache == "exact_hit" else 1 if cache == "semantic_hit" else 2
    tokens = calls * 20 if known else 0
    result = {
        "id": run_id, "model": "unit-test-fixture", "question": question,
        "sources": req["sources"], "task": "qa", "schema": None,
        "strategy": "adaptive", "namespace": group["id"], "status": "accepted",
        "answer": answer, "data": None, "abstained": False,
        "citations": [{"source_id": "source", "quote": "Alpha launched in 2024."}],
        "source_hash": evidence_digest(req["sources"]), "config_hash": evidence_digest(CONFIG),
        "wall_latency_ms": elapsed - .25, "latency_ms": elapsed - .25,
        "cache": {"status": cache, "rejected_candidates": 0},
        "attempts": [],
        "usage": {"calls": calls, "actual_calls": calls, "reused_calls": 0,
                  "prompt_tokens": calls * 12 if known else 0,
                  "completion_tokens": calls * 8 if known else 0,
                  "total_tokens": tokens, "actual_total_tokens": tokens,
                  "known": known if calls else True, "unknown_calls": calls if not known else 0},
    }
    if cache == "miss":
        result["attempts"] = [{"generation": response(known), "critic_response": response(known)}]
    elif cache == "semantic_hit":
        result["cache"]["verification"] = {"response": response(known)}
    if origin:
        result["cache"]["source_run_id"] = origin
    return {"request": req, "references": references, "result": result,
            "end_to_end_ms": elapsed, "exact_match": 1, "token_f1": 1, "correct": True}


def fixture():
    group = {
        "id": "launch", "source": {"id": "source", "title": "Dates",
            "text": "Alpha launched in 2024. Beta launched in 2025."},
        "seed": {"question": "When did Alpha launch?", "answers": ["2024"]},
        "queries": [
            {"question": "What is the launch year of Alpha?", "answers": ["2024"],
             "kind": "paraphrase", "reuse_expected": True},
            {"question": "When did Beta launch?", "answers": ["2025"],
             "kind": "entity-swap", "reuse_expected": False},
        ],
    }
    suite = {"version": "fixture", "groups": [group]}
    source_text = json.dumps(suite)
    cold = row(group, group["seed"]["question"], group["seed"]["answers"], "cold")
    warm = row(group, group["seed"]["question"], group["seed"]["answers"], "warm",
               cache="exact_hit", origin="cold", elapsed=5)
    queries = []
    for i, query in enumerate(group["queries"]):
        queries.append({"kind": query["kind"], "reuse_expected": query["reuse_expected"],
                        **row(group, query["question"], query["answers"], f"query-{i}",
                              cache="semantic_hit", origin="cold", elapsed=50)})
    return {
        "format": "answer-cache-probe-v1", "status": "completed", "model": "unit-test-fixture",
        "suite_source_text": source_text, "suite_snapshot": suite,
        "suite_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        "plan": {"replays_per_group": 1, "max_attempts": 3}, "configuration": CONFIG,
        "source_files": {"src/engine.py": "a" * 64},
        "source_files_after": {"src/engine.py": "a" * 64}, "source_unchanged": True,
        "groups": [{"id": group["id"], "cold": cold, "replays": [warm], "queries": queries}],
    }


def test_regrades_false_hit_and_retains_exact_frontend_keys():
    summary = summarize_cache(fixture())
    assert summary["complete"]
    assert summary["exact_hit_rate"] == 1
    assert summary["p50_exact_replay_speedup"] == 200
    assert summary["paired_cold_requests"] == summary["correct_paired_groups"] == 1
    assert summary["semantic_hits"] == 2
    assert summary["semantic_false_hits"] == 1
    assert summary["semantic_false_hit_rate"] == .5
    assert summary["semantic_total_correct"] == 1
    assert summary["by_kind"]["entity-swap"]["false_hits"] == 1
    assert summary["negative_query_hits"] == 1
    assert summary["actual_calls"] == 4
    assert summary["tokens"] == 80


def test_incorrect_cold_and_exact_hits_are_retained_not_speedup_filtered():
    report = fixture()
    for row_value in [report["groups"][0]["cold"], *report["groups"][0]["replays"],
                      *report["groups"][0]["queries"]]:
        row_value["result"]["answer"] = "1999"
    summary = summarize_cache(report)
    assert summary["cold_incorrect"] == 1
    assert summary["exact_false_hits"] == 1
    assert summary["paired_cold_requests"] == 1
    assert summary["p50_exact_replay_speedup"] == 200
    assert summary["correct_paired_groups"] == 0
    assert summary["correct_pair_speedup_p50"] is None


@pytest.mark.parametrize("change", ["missing_group", "missing_query", "missing_replay", "source_change", "interrupted"])
def test_incomplete_coverage_or_changed_source_blocks_complete(change):
    report = fixture()
    if change == "missing_group":
        report["groups"] = []
    elif change == "missing_query":
        report["groups"][0]["queries"].pop()
    elif change == "missing_replay":
        report["groups"][0]["replays"] = []
    elif change == "source_change":
        report["source_files_after"]["src/engine.py"] = "b" * 64
        report["source_unchanged"] = False
    else:
        report["status"] = "interrupted"
    assert not summarize_cache(report)["complete"]


@pytest.mark.parametrize("change", ["suite_hash", "snapshot", "reference", "request", "source", "model", "config", "query_kind", "duplicate_id", "unseen_origin", "origin_answer", "unexpected_query"])
def test_tampering_rejected(change):
    report = copy.deepcopy(fixture())
    group = report["groups"][0]
    if change == "suite_hash":
        report["suite_sha256"] = "0" * 64
    elif change == "snapshot":
        report["suite_snapshot"]["groups"][0]["seed"]["answers"] = ["1999"]
    elif change == "reference":
        group["cold"]["references"] = ["1999"]
    elif change == "request":
        group["cold"]["request"]["question"] = "Changed?"
    elif change == "source":
        group["cold"]["result"]["source_hash"] = "bad"
    elif change == "model":
        group["cold"]["result"]["model"] = "different"
    elif change == "config":
        group["cold"]["result"]["config_hash"] = "changed"
    elif change == "query_kind":
        group["queries"][1]["kind"] = "paraphrase"
    elif change == "duplicate_id":
        group["replays"][0]["result"]["id"] = "cold"
    elif change == "unseen_origin":
        group["replays"][0]["result"]["cache"]["source_run_id"] = "imaginary"
    elif change == "origin_answer":
        group["replays"][0]["result"]["answer"] = "2025"
    elif change == "unexpected_query":
        group["queries"].append(copy.deepcopy(group["queries"][0]))
    with pytest.raises(CacheEvidenceError):
        summarize_cache(report)


@pytest.mark.parametrize("field,value", [("actual_calls", 0), ("actual_calls", True),
                                         ("total_tokens", 1), ("known", False),
                                         ("unknown_calls", 1), ("reused_calls", 1)])
def test_call_and_token_accounting_reconstructed(field, value):
    report = fixture()
    report["groups"][0]["cold"]["result"]["usage"][field] = value
    with pytest.raises(CacheEvidenceError, match="accounting"):
        summarize_cache(report)


def test_unknown_usage_blocks_token_claim_without_dropping_calls():
    report = fixture()
    group = report["suite_snapshot"]["groups"][0]
    report["groups"][0]["cold"] = row(group, group["seed"]["question"], group["seed"]["answers"], "cold", known=False)
    summary = summarize_cache(report)
    assert not summary["usage_known"]
    assert summary["tokens"] is None
    assert summary["observed_tokens"] == 40
    assert summary["actual_calls"] == 4


def test_unanswerable_requires_explicit_abstention_even_if_text_normalizes_empty():
    report = fixture()
    suite = report["suite_snapshot"]
    query = suite["groups"][0]["queries"][1]
    query["answers"] = [""]
    query["kind"] = "unanswerable"
    report["suite_source_text"] = json.dumps(suite)
    report["suite_sha256"] = hashlib.sha256(report["suite_source_text"].encode()).hexdigest()
    group = report["groups"][0]
    negative = row(suite["groups"][0], query["question"], query["answers"], "query-1", answer="the")
    group["queries"][1] = {"kind": "unanswerable", "reuse_expected": False, **negative}
    summary = summarize_cache(report)
    assert summary["semantic_total_correct"] == 1
    assert summary["by_kind"]["unanswerable"]["correct"] == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_bad_latency_rejected(value):
    report = fixture()
    report["groups"][0]["cold"]["end_to_end_ms"] = value
    with pytest.raises(CacheEvidenceError):
        summarize_cache(report)


def test_exact_hit_with_hidden_model_call_rejected():
    report = fixture()
    result = report["groups"][0]["replays"][0]["result"]
    result["attempts"] = [{"generation": response(), "critic_response": None}]
    with pytest.raises(CacheEvidenceError):
        summarize_cache(report)


def test_semantic_hit_without_recorded_critic_rejected():
    report = fixture()
    del report["groups"][0]["queries"][0]["result"]["cache"]["verification"]
    with pytest.raises(CacheEvidenceError):
        summarize_cache(report)


def test_real_probe_runner_roundtrip_with_deterministic_local_adapter(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    from agentproof.answers import AnswerService, ModelResponse

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("cache_probe", root / "scripts/answer_cache_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    class Embedder:
        name = "test-vector"
        status = "injected"
        revision = "test"

        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Adapter:
        model = "deterministic-cache-test-fixture"
        configured = True

        def configuration(self):
            return {"model": self.model, "revision": "test"}

        def complete(self, messages, *, purpose):
            context = json.loads(messages[-1]["content"])
            expected = "2025" if "Beta" in context["question"] else "2024"
            if purpose == "critic":
                correct = context["candidate"]["answer"] == expected
                body = {"supported": correct, "responsive": correct, "answerable": True,
                        "feedback": "Use the matching application launch year."}
            else:
                app = "Beta" if expected == "2025" else "Alpha"
                body = {"answer": expected, "data": None, "abstained": False,
                        "citations": [{"source_id": "source", "quote": f"{app} launched in {expected}."}]}
            return ModelResponse(json.dumps(body), 10, 10, 1, "stop", True)

    def factory(db, adapter=None, embedder=None):
        return AnswerService(db, adapter=adapter or Adapter(), embedder=embedder or Embedder())

    monkeypatch.setattr(probe, "AnswerService", factory)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(fixture()["suite_snapshot"]))
    report = probe.run_probe(suite_path, tmp_path / "output", replays=2)
    assert report["summary"]["complete"]
    assert report["summary"] == summarize_cache(json.loads((tmp_path / "output/raw.json").read_text()))
    assert report["summary"]["exact_hits"] == 2
    assert report["summary"]["semantic_hits"] == 1
    assert report["summary"]["semantic_total_correct"] == 2
    assert report["summary"]["semantic_false_hits"] == 0
    assert report["summary"]["actual_calls"] == 6  # 2 cold, 1 paraphrase, 1 rejected+2 new answer.
