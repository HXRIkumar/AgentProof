"""Expanded-corpus integrity and retrieval metrics; fake vectors only, no model loading."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "retrieval_benchmark", ROOT / "scripts/retrieval_benchmark.py"
)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def parent_suite(tmp_path):
    sources = [
        {"id": "source-1", "title": "Blue unit", "text": "The cobalt unit operates in Northbay."},
        {"id": "source-1", "title": "Green unit", "text": "The jade unit operates in Southbank."},
        *[
            {
                "id": "source-1",
                "title": f"Other {i}",
                "text": f"Archive item {i} describes unrelated farming equipment.",
            }
            for i in range(8)
        ],
        {
            "id": "source-1",
            "title": "Exclude",
            "text": "The unrelated NORTHBAY warehouse stores empty boxes.",
        },
    ]
    cases = [
        {
            "id": f"question-{index}",
            "task": "qa",
            "category": "answerable" if index < 2 else "unanswerable",
            "request": {
                "question": f"Where does the {'cobalt' if index == 0 else 'jade'} unit operate?",
                "task": "qa",
                "sources": [source],
            },
            "gold": {
                "answerable": index < 2,
                "answers": ["Northbay" if index == 0 else "Southbank"] if index < 2 else [],
                "relevant_source_ids": [source["id"]],
            },
        }
        for index, source in enumerate(sources)
    ]
    # A duplicate under another local source ID must not create another distractor.
    cases[-1]["request"]["sources"].append({**sources[2], "id": "source-2"})
    suite = {"version": "answer-suite-v1", "split": "evaluation", "cases": cases}
    target = tmp_path / "parent"
    target.mkdir()
    path = target / "evaluation.json"
    path.write_bytes(RUNNER.encoded(suite))
    (target / "manifest.json").write_text(
        json.dumps({"files": {path.name: RUNNER.sha(path.read_bytes())}})
    )
    return path


def freeze(tmp_path):
    path = parent_suite(tmp_path)
    output = tmp_path / "frozen"
    RUNNER.freeze_suite(path, output, source_count=5, expected_cases=2)
    return output / "suite.json"


class FakeVectors:
    name = RUNNER.MODEL
    revision = RUNNER.REVISION
    status = "loaded"

    def encode(self, texts):
        return [[float("cobalt" in text), float("jade" in text), 0.1] for text in texts]


class MissingVectors(FakeVectors):
    status = "unavailable"

    def encode(self, texts):
        return None


def test_freeze_is_deterministic_excludes_answers_and_never_ranks(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Freeze must not rank or load models")

    monkeypatch.setattr(RUNNER, "retrieve", forbidden)
    monkeypatch.setattr(RUNNER, "SentenceEmbedder", forbidden)
    parent = parent_suite(tmp_path)
    first, second = tmp_path / "a", tmp_path / "b"
    RUNNER.freeze_suite(parent, first, source_count=5, expected_cases=2)
    RUNNER.freeze_suite(parent, second, source_count=5, expected_cases=2)
    assert (first / "suite.json").read_bytes() == (second / "suite.json").read_bytes()
    suite, _, _ = RUNNER.load_frozen(first / "suite.json")
    for case in suite["cases"]:
        assert len(case["sources"]) == 5
        assert len({source["id"] for source in case["sources"]}) == 5
        assert len({RUNNER.normalized(s["text"]) for s in case["sources"]}) == 5
        for source in case["sources"]:
            if source["id"] != case["annotation"]["relevant_source_id"]:
                assert not any(
                    RUNNER.normalized(answer) in RUNNER.normalized(source["text"])
                    for answer in case["annotation"]["excluded_answer_strings"]
                )


def test_freeze_refuses_overwrite_and_manifest_mismatch(tmp_path):
    parent = parent_suite(tmp_path)
    output = tmp_path / "frozen"
    RUNNER.freeze_suite(parent, output, source_count=5, expected_cases=2)
    with pytest.raises(FileExistsError):
        RUNNER.freeze_suite(parent, output, source_count=5, expected_cases=2)
    parent.write_text(parent.read_text() + " ")
    with pytest.raises(ValueError, match="manifest"):
        RUNNER.freeze_suite(parent, tmp_path / "changed", source_count=5, expected_cases=2)
    assert not (tmp_path / "changed").exists()


def test_not_enough_distractors_never_relaxes_filter(tmp_path):
    parent = parent_suite(tmp_path)
    with pytest.raises(ValueError, match="Insufficient"):
        RUNNER.freeze_suite(parent, tmp_path / "too-big", source_count=20, expected_cases=2)
    assert not (tmp_path / "too-big").exists()


def test_rank_and_recall_use_annotation_only_after_scoring(tmp_path):
    suite, _, _ = RUNNER.load_frozen(freeze(tmp_path))
    case = suite["cases"][0]
    first = RUNNER.rank_case(case)
    assert first["annotated_source_first_rank"] == 1
    assert first["recall_at_1"] == first["recall_at_4"] == first["reciprocal_rank"] == 1
    changed = copy.deepcopy(case)
    changed["annotation"]["relevant_source_id"] = first["ranking"][-1]["source_id"]
    second = RUNNER.rank_case(changed)
    assert first["ranking"] == second["ranking"]
    assert second["annotated_source_first_rank"] == 5
    assert second["recall_at_1"] == second["recall_at_4"] == 0
    assert second["reciprocal_rank"] == pytest.approx(0.2)


@pytest.mark.parametrize("embedder", [None, FakeVectors()])
def test_all_ranked_prefix_matches_production_k4(tmp_path, embedder):
    suite, _, _ = RUNNER.load_frozen(freeze(tmp_path))
    for case in suite["cases"]:
        result = RUNNER.rank_case(case, embedder)
        assert result["selected_count"] == 4
        assert result["chunk_count"] == 5
        assert result["top_4_source_ids"] == [item["source_id"] for item in result["ranking"][:4]]


def test_fake_vector_study_is_complete_and_preserves_per_case_results(tmp_path):
    suite_path = freeze(tmp_path)
    report = RUNNER.evaluate(suite_path, tmp_path / "report", embedder=FakeVectors())
    assert report["status"] == "completed"
    assert report["llm_calls"] == 0
    assert report["suite_integrity"] and report["source_integrity"]
    assert len(report["trials"]) == 4
    assert {row["case_id"] for row in report["trials"]} == {"question-0", "question-1"}
    assert all(
        summary["complete"] and summary["ranked_queries"] == 2
        for summary in report["summary"].values()
    )
    assert json.loads((tmp_path / "report/raw.json").read_text()) == report
    with pytest.raises(FileExistsError):
        RUNNER.evaluate(suite_path, tmp_path / "report", embedder=FakeVectors())


def test_missing_embeddings_never_report_bm25_as_hybrid(tmp_path):
    report = RUNNER.evaluate(freeze(tmp_path), tmp_path / "report", embedder=MissingVectors())
    assert report["status"] == "failed"
    assert report["summary"]["bm25"]["complete"]
    assert report["summary"]["hybrid"]["errors"] == 2
    assert report["summary"]["hybrid"]["mrr"] is None
    assert report["summary"]["hybrid"]["recall_at_4"] is None


def test_rank_case_rejects_fallback_after_initial_embedding_load(tmp_path):
    suite, _, _ = RUNNER.load_frozen(freeze(tmp_path))
    with pytest.raises(ValueError, match="fell back"):
        RUNNER.rank_case(suite["cases"][0], MissingVectors())


def test_tampered_frozen_data_is_rejected_before_output(tmp_path):
    path = freeze(tmp_path)
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="manifest"):
        RUNNER.evaluate(path, tmp_path / "report", embedder=FakeVectors())
    assert not (tmp_path / "report").exists()


def test_runtime_change_marks_report_incomplete(tmp_path, monkeypatch):
    suite = freeze(tmp_path)
    calls = iter([{"retrieval.py": "before"}, {"retrieval.py": "after"}])
    monkeypatch.setattr(RUNNER, "source_manifest", lambda: next(calls))
    report = RUNNER.evaluate(suite, tmp_path / "report", embedder=FakeVectors())
    assert report["status"] == "failed"
    assert report["source_integrity"] is False


def test_archived_generator_change_during_run_fails_frozen_integrity(tmp_path, monkeypatch):
    suite = freeze(tmp_path)
    archive = suite.parent / "frozen-generator.py.txt"
    original = RUNNER.rank_case

    def mutate_archive(case, embedder=None):
        archive.write_text(archive.read_text() + "\n# modified after freeze\n")
        return original(case, embedder)

    monkeypatch.setattr(RUNNER, "rank_case", mutate_archive)
    report = RUNNER.evaluate(suite, tmp_path / "report", embedder=FakeVectors())
    assert report["status"] == "failed"
    assert report["suite_integrity"] is False
    assert report["source_integrity"] is True
    assert len(report["trials"]) == 4


def test_interruption_preserves_checkpoint_without_complete_claim(tmp_path, monkeypatch):
    original = RUNNER.rank_case
    calls = 0

    def interrupted(case, embedder=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original(case, embedder)

    monkeypatch.setattr(RUNNER, "rank_case", interrupted)
    report = RUNNER.evaluate(freeze(tmp_path), tmp_path / "report", embedder=FakeVectors())
    assert report["status"] == "interrupted"
    assert len(report["trials"]) == 1
    assert report["summary"]["bm25"]["mrr"] is None
    assert json.loads((tmp_path / "report/raw.json").read_text())["status"] == "interrupted"


def test_whole_document_source_recall_is_explicit_for_multichunk_input(tmp_path):
    suite, _, _ = RUNNER.load_frozen(freeze(tmp_path))
    case = copy.deepcopy(suite["cases"][0])
    source = next(x for x in case["sources"] if x["id"] == case["annotation"]["relevant_source_id"])
    source["text"] = source["text"] + " Archive material." * 250
    result = RUNNER.rank_case(case)
    assert result["chunk_count"] > result["source_count"]
    assert result["annotated_source_first_rank"] == 1
    assert len(result["ranking"]) == result["chunk_count"]
