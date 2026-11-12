"""Reference metrics, frozen-case integrity, and no-gold paired evaluation contracts."""

import copy
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from agentproof.answer_eval import (
    comparison_summary,
    evidence_digest,
    grade_result,
    load_suite,
    normalize_answer,
    paired_interval,
    qa_scores,
    strategy_summary,
    summarize_report,
    typed_equal,
)
from agentproof.answers import ModelResponse

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("answer_benchmark", ROOT / "scripts/answer_benchmark.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def qa_case(answerable=True):
    return {
        "id": "qa-example", "task": "qa", "category": "answerable" if answerable else "unanswerable",
        "request": {"task": "qa", "question": "What color is the sky in this record?",
                    "sources": [{"id": "doc", "title": "Record", "text": "The sky is blue."}]},
        "gold": {"answers": ["blue"] if answerable else [], "answerable": answerable,
                 "relevant_source_ids": ["doc"]},
    }


def result(answer="blue", status="accepted", abstained=False, data=None):
    initial = ModelResponse("fixture", prompt_tokens=10, completion_tokens=10,
                            latency_ms=5, usage_known=True, request_hash="fixture")
    return {"status": status, "answer": answer, "abstained": abstained, "data": data,
            "usage": {"calls": 1, "total_tokens": 20, "known": True, "actual_calls": 0,
                      "actual_total_tokens": 0},
            "latency_ms": 10.0, "attempts": [{"generation": asdict(initial)}],
            "cache": {"status": "disabled"},
            "retrieval": {"selected": [{"source_id": "doc"}]}}


def trial(strategy="baseline", answer="blue", initial="blue", case=None):
    case = case or qa_case()
    final = result(answer)
    first = result(initial)
    return {"case_id": case["id"], "case": case, "task": case["task"],
            "category": case["category"], "strategy": strategy, "result": final,
            "initial_result": first, "grade": grade_result(case, final),
            "initial_grade": grade_result(case, first)}


def report(trials):
    return {"status": "completed", "suite": {"case_count": 1, "case_ids": ["qa-example"],
            "case_manifest_sha256": {"qa-example": evidence_digest(qa_case())}},
            "configuration": {"strategies": ["baseline", "validated", "adaptive"]},
            "initial_generations": [{"case_id": "qa-example", "response":
                                     trials[0]["initial_result"]["attempts"][0]["generation"]}],
            "trials": trials}


def test_squad_normalization_and_multireference_f1():
    assert normalize_answer("  The, Blue! Sky  ") == "blue sky"
    assert qa_scores("the blue", ["red", "blue"]) == (1.0, 1.0)
    assert qa_scores("blue sky", ["blue"]) == (0, 2 / 3)
    assert qa_scores("", []) == (1, 1)
    assert qa_scores("not in source", []) == (0, 0)
    assert qa_scores("red red blue", ["red blue blue"])[1] == 2 / 3


@pytest.mark.parametrize("status,abstained", [("error", False), ("failed", False),
                                             ("accepted", False), ("error", True)])
def test_empty_or_error_is_never_correct_unanswerable(status, abstained):
    grade = grade_result(qa_case(False), result("", status=status, abstained=abstained))
    assert not grade["correct"]
    assert grade["exact_match"] == 0


def test_explicit_abstention_and_delivery_separate():
    assert grade_result(qa_case(False), result("", "abstained", True))["correct"]
    assert not grade_result(qa_case(True), result("", "abstained", True))["correct"]
    rejected_correct = grade_result(qa_case(), result("blue", "failed"))
    assert rejected_correct["answer_correct"]
    assert not rejected_correct["correct"]


@pytest.mark.parametrize("answer", ["the", "a", "an", "...", "!!!", " The. "])
def test_normalization_empty_text_does_not_fake_abstention(answer):
    grade = grade_result(qa_case(False), result(answer))
    assert not grade["correct"]
    assert grade["exact_match"] == grade["token_f1"] == 0


def test_unchanged_failed_delivery_is_not_a_regression():
    row = trial()
    row["result"]["status"] = row["initial_result"]["status"] = "failed"
    row["grade"] = grade_result(row["case"], row["result"])
    row["initial_grade"] = grade_result(row["case"], row["initial_result"])
    summary = strategy_summary([row])
    assert summary["regressed"] == 0
    assert summary["regression_rate"] is None
    assert summary["answer_regression_rate"] == 0


def test_typed_fields_and_extra_data_penalty():
    case = {"task": "extraction", "request": {"schema": {
        "type": "object", "properties": {"count": {"type": "integer"}, "enabled": {"type": "boolean"}},
        "required": ["count", "enabled"], "additionalProperties": False}},
        "gold": {"data": {"count": 1, "enabled": True}}}
    assert not typed_equal(True, 1)
    assert typed_equal(1, 1.0)
    assert not typed_equal({"a": [1, 2]}, {"a": [2, 1]})
    assert grade_result(case, result(data={"count": 1, "enabled": True}))["correct"]
    wrong_type = grade_result(case, result(data={"count": True, "enabled": True}))
    assert not wrong_type["schema_valid"]
    assert wrong_type["field_accuracy"] == .5
    extra = grade_result(case, result(data={"count": 1, "enabled": True, "extra": 5}))
    assert not extra["correct"]
    assert extra["field_accuracy"] == 2 / 3
    assert extra["field_f1"] == pytest.approx(.8)


def test_recovery_regression_denominators_and_unknown_usage():
    recovered = trial("adaptive", "blue", "red")
    recovered["result"]["attempts"] = [{}, {}]
    lost = trial("adaptive", "red", "blue")
    lost["result"]["usage"]["known"] = False
    summary = strategy_summary([recovered, lost])
    assert summary["recovery_rate"] == 1
    assert summary["regression_rate"] == 1
    assert summary["false_accept_rate"] == .5
    assert summary["retries_per_query"] == .5
    assert summary["total_tokens"] is None
    assert summary["tokens_per_correct"] is None
    assert summary["observed_tokens"] == 40
    assert strategy_summary([trial()])["recovery_rate"] is None
    assert strategy_summary([])["success_rate"] is None


def test_paired_bootstrap_reproducible_and_empty_is_null():
    assert paired_interval([]) is None
    assert paired_interval([0, 0, 0]) == [0, 0]
    assert paired_interval([1, 1, 1]) == [1, 1]
    assert paired_interval([1, 0, -1]) == paired_interval([1, 0, -1])
    comparison = comparison_summary([trial("baseline", "red"), trial("adaptive", "blue")],
                                    "baseline", "adaptive")
    assert comparison["success_delta"] == 1
    assert comparison["success_delta_ci95"] == [1, 1]
    assert comparison["paired_cases"] == 1


def test_summary_regrades_and_rejects_duplicate_or_missing_coverage():
    document = report([trial(s) for s in ("baseline", "validated", "adaptive")])
    document["trials"][0]["grade"]["correct"] = False
    assert summarize_report(document)["strategies"]["baseline"]["correct"] == 1
    assert summarize_report(document)["complete"]
    partial = copy.deepcopy(document)
    partial["trials"].pop()
    assert not summarize_report(partial)["complete"]
    changed = copy.deepcopy(document)
    changed["source_unchanged"] = False
    assert not summarize_report(changed)["complete"]
    duplicate = copy.deepcopy(document)
    duplicate["trials"][2] = duplicate["trials"][0]
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_report(duplicate)
    unknown = copy.deepcopy(document)
    unknown["trials"][0]["case_id"] = "invented"
    with pytest.raises(ValueError, match="Unexpected case"):
        summarize_report(unknown)


@pytest.mark.parametrize("tamper", ["case", "initial", "generation", "baseline"])
def test_summary_rejects_unpaired_or_relabelled_evidence(tamper):
    document = report([trial(s) for s in ("baseline", "validated", "adaptive")])
    if tamper == "case":
        document["trials"][2]["case"]["gold"]["answers"] = ["red"]
    elif tamper == "initial":
        document["trials"][2]["initial_result"]["answer"] = "red"
    elif tamper == "generation":
        document["initial_generations"][0]["response"] = {"text": "different"}
    else:
        document["trials"][0]["result"]["answer"] = "red"
    with pytest.raises(ValueError, match="manifest|identical initial|recorded model|Baseline result"):
        summarize_report(document)


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), -1, True, None])
def test_summary_rejects_invalid_latency(latency):
    document = report([trial()])
    document["trials"][0]["result"]["latency_ms"] = latency
    with pytest.raises((ValueError, TypeError), match="latency"):
        summarize_report(document)


def test_frozen_suite_hashes_schemas_and_split_independence():
    directory = ROOT / "examples/answer-suite-v1"
    manifest = json.loads((directory / "manifest.json").read_text())
    assert hashlib.sha256((directory / "frozen-generator.py.txt").read_bytes()).hexdigest() == manifest["extractor_sha256"]
    suites = {}
    contexts = {}
    for split, expected_qa, expected_extraction in [("development", 12, 6), ("evaluation", 48, 16)]:
        suites[split], digest = load_suite(directory / f"{split}.json")
        assert digest == manifest["files"][f"{split}.json"]
        cases = suites[split]["cases"]
        qa = [c for c in cases if c["task"] == "qa"]
        assert len(qa) == expected_qa
        assert sum(c["task"] == "extraction" for c in cases) == expected_extraction
        assert sum(c["gold"]["answerable"] for c in qa) == expected_qa // 2
        contexts[split] = set()
        for case in qa:
            sources = case["request"]["sources"]
            assert len(sources) == 3
            assert len({s["title"] for s in sources}) == 3
            assert sum(len(s["text"]) for s in sources) <= 3700
            original = next(s for s in sources if s["id"] in case["gold"]["relevant_source_ids"])
            contexts[split].add(original["text"])
            for answer in case["gold"]["answers"]:
                assert answer in original["text"]
        assert len(contexts[split]) == expected_qa
    assert not contexts["development"] & contexts["evaluation"]
    assert not ({c["id"] for c in suites["development"]["cases"]}
                & {c["id"] for c in suites["evaluation"]["cases"]})


class FakeAdapter:
    model = "deterministic-test-fixture"


class FakeService:
    adapter = FakeAdapter()

    def __init__(self):
        self.initials = []
        self.inputs = []

    def configuration(self):
        return {"fixture": True}

    def generate_initial(self, request):
        response = ModelResponse("fixture", prompt_tokens=10, completion_tokens=10,
                                 latency_ms=5, usage_known=True, request_hash="fixture")
        self.initials.append(response)
        return response

    def run(self, request, initial_response=None, persist=False):
        assert not persist
        assert "gold" not in request.model_dump()
        self.inputs.append((request, initial_response))
        answer = "red" if request.strategy == "baseline" else "blue"
        output = result(answer)
        if request.strategy != "baseline":
            output["attempts"] = [{}, {}]
            output["usage"] = {"calls": 2, "total_tokens": 40, "known": True,
                               "actual_calls": 1, "actual_total_tokens": 20}
        return output


def test_runner_shares_initial_excludes_labels_and_preserves_output(tmp_path):
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps({"version": "test", "split": "development", "cases": [qa_case()]}))
    service = FakeService()
    document = RUNNER.run_benchmark(suite_path, tmp_path / "output", service=service)
    assert len(service.initials) == 1
    assert len(service.inputs) == 3
    assert all(initial is service.initials[0] for _, initial in service.inputs)
    assert all(not request.use_cache for request, _ in service.inputs)
    assert document["actual_usage"]["calls"] == 3
    assert document["actual_usage"]["total_tokens"] == 60
    assert document["summary"]["strategies"]["adaptive"]["recovery_rate"] == 1
    assert document["source_unchanged"]
    assert document["summary"]["complete"]
    assert asdict(service.initials[0]) == document["initial_generations"][0]["response"]
    assert json.loads((tmp_path / "output/raw.json").read_text())["status"] == "completed"
    with pytest.raises(FileExistsError):
        RUNNER.run_benchmark(suite_path, tmp_path / "output", service=service)


def test_interruption_retains_initial_response_and_partial_status(tmp_path):
    class Interrupted(FakeService):
        def run(self, request, initial_response=None, persist=False):
            raise KeyboardInterrupt
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"version": "test", "split": "development", "cases": [qa_case()]}))
    document = RUNNER.run_benchmark(path, tmp_path / "interrupted", service=Interrupted())
    assert document["status"] == "interrupted"
    assert document["actual_usage"]["calls"] == 1
    assert len(document["initial_generations"]) == 1
    assert not document["summary"]["complete"]
