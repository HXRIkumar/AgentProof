"""Offline verifier regressions with synthetic records, never model output claims."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("independent_answer_audit", ROOT / "scripts/audit_answer_evidence.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
SUITE = (ROOT / "examples/answer-suite-v1/development.json").read_bytes()


def fixture():
    """Perfect synthetic evidence over public dev cases, for audit tests only."""
    cases = json.loads(SUITE)["cases"]
    ids = [case["id"] for case in cases]
    document = {
        "status": "completed", "source_unchanged": True,
        "suite": {"sha256": AUDIT.FROZEN["development"][1], "split": "development",
                  "case_count": 18, "case_ids": ids,
                  "case_manifest_sha256": {case["id"]: AUDIT.digest(case) for case in cases}},
        "configuration": {"strategies": ["baseline", "validated", "adaptive"], "cache_enabled": False,
                          "runtime": {"fixture": "Synthetic test records, not a model benchmark"},
                          "source_files": {"fixture.py": "a" * 64}},
        "initial_generations": [], "trials": [],
        "summary": {"complete": True, "strategies": {}},
    }
    for case in cases:
        unanswerable = case["task"] == "qa" and not case["gold"]["answerable"]
        response = {"text": "synthetic-fixture", "prompt_tokens": 10, "completion_tokens": 5,
                    "usage_known": True, "request_sent": True, "model": "gpt-5.4-mini-2026-03-17",
                    "billing": {"provider": "openai", "reservation_id": case["id"], "state": "settled",
                                "estimated_cost_usd": .00003, "accounted_usd": .00003, "reserved_usd": .001,
                                "reported_prompt_tokens": 10, "reported_completion_tokens": 5,
                                "pricing_version": "openai-gpt-5.4-mini-standard-2026-11-12"}}
        result = {"status": "abstained" if unanswerable else "accepted", "abstained": unanswerable,
                  "answer": (case["gold"]["answers"][0] if not unanswerable else "") if case["task"] == "qa" else "",
                  "data": case["gold"].get("data"), "attempts": [{"generation": response}],
                  "cache": {"status": "disabled"}, "usage": AUDIT.usage([(response, True)])}
        document["initial_generations"].append({"case_id": case["id"], "response": response})
        for strategy in document["configuration"]["strategies"]:
            document["trials"].append({"case_id": case["id"], "strategy": strategy, "case": case,
                                       "result": result, "initial_result": result,
                                       "grade": AUDIT.grade(case, result), "initial_grade": AUDIT.grade(case, result)})
    for strategy in document["configuration"]["strategies"]:
        document["summary"]["strategies"][strategy] = {
            "trials": 18, "correct": 18, "success_rate": 1., "answer_correct": 18, "answer_accuracy": 1.,
            "calls": 18, "observed_tokens": 270, "total_tokens": 270, "usage_known": True,
            "tokens_per_correct": 15., "recovered": 0, "regressed": 0, "exact_match": 1., "token_f1": 1.,
            "field_accuracy": 1., "field_f1": 1., "schema_valid_rate": 1., "paid_calls": 18,
            "actual_paid_calls": 0, "blocked_calls": 0, "estimated_cost_usd": .00054,
            "accounted_cost_usd": .00054, "cost_known": True, "cost_per_correct_usd": .00003,
        }
    document["actual_usage"] = {"calls": 18, "observed_tokens": 270, "total_tokens": 270,
                                "usage_known": True, "shared_initial_generations": 18,
                                "paid_calls": 18, "blocked_calls": 0, "estimated_cost_usd": .00054,
                                "accounted_cost_usd": .00054, "cost_known": True}
    return copy.deepcopy(document)


def audited(document):
    return AUDIT.audit_report(document, SUITE, allow_development=True)


def test_full_synthetic_development_audit_binds_shared_cost_once():
    result = audited(fixture())
    assert result["passed"] and result["case_count"] == 18 and result["paired_trials"] == 54
    assert result["actual_usage"]["calls"] == 18
    assert result["unique_paid_reservations"] == 18
    assert result["actual_usage"]["estimated_cost_usd"] == pytest.approx(.00054)


@pytest.mark.parametrize("mutation,expected", [
    (lambda r: r.update(status="running"), "completed"),
    (lambda r: r["suite"].update(sha256="0" * 64), "suite identity"),
    (lambda r: r["trials"].pop(), "coverage"),
    (lambda r: r["trials"].append(copy.deepcopy(r["trials"][0])), "Duplicate"),
    (lambda r: r["actual_usage"].update(calls=54), "Physical study usage"),
    (lambda r: r["actual_usage"].update(estimated_cost_usd=.00162), "Physical study usage"),
    (lambda r: r["summary"]["strategies"]["adaptive"].update(correct=17), "Strategy adaptive"),
    (lambda r: r["initial_generations"][0]["response"].update(request_sent=False), "Blocked response"),
    (lambda r: r["initial_generations"][0]["response"]["billing"].update(estimated_cost_usd=0), "Billing"),
    (lambda r: r["initial_generations"][0]["response"]["billing"].update(
        reservation_id=r["initial_generations"][1]["response"]["billing"]["reservation_id"]), "reservation ID"),
])
def test_tampered_coverage_usage_cost_and_completeness_fail(mutation, expected):
    document = fixture()
    mutation(document)
    with pytest.raises(AUDIT.AuditError, match=expected):
        audited(document)


def test_an_arm_cannot_replace_shared_initial_and_still_pass():
    document = fixture()
    document["trials"][1] = copy.deepcopy(document["trials"][1])
    document["trials"][1]["result"]["attempts"][0]["generation"]["text"] = "replacement"
    with pytest.raises(AUDIT.AuditError, match="initial"):
        audited(document)


def test_development_does_not_masquerade_as_final_evaluation():
    with pytest.raises(AUDIT.AuditError, match="Development"):
        AUDIT.audit_report(fixture(), SUITE)


def test_explicit_abstention_and_typed_extraction_are_independent():
    qa = {"task": "qa", "gold": {"answerable": False, "answers": []}}
    assert not AUDIT.grade(qa, {"status": "accepted", "answer": "the", "abstained": False})["correct"]
    assert AUDIT.grade(qa, {"status": "abstained", "answer": "", "abstained": True})["correct"]
    extraction = {"task": "extraction", "request": {"schema": {"type": "object"}}, "gold": {"data": {"value": 1}}}
    assert not AUDIT.grade(extraction, {"status": "accepted", "data": {"value": True}})["correct"]
    assert AUDIT.grade(extraction, {"status": "accepted", "data": {"value": 1.0}})["correct"]
    qa = {"task": "qa", "gold": {"answerable": True, "answers": ["the blue sky"]}}
    assert AUDIT.grade(qa, {"status": "accepted", "answer": "blue"})["token_f1"] == pytest.approx(2/3)


def test_source_root_checks_bytes_instead_of_trusting_flag(tmp_path):
    (tmp_path / "fixture.py").write_text("different source")
    with pytest.raises(AUDIT.AuditError, match="Frozen source mismatch"):
        AUDIT.audit_report(fixture(), SUITE, allow_development=True, source_root=tmp_path)


def test_cli_writes_separate_audit_and_refuses_overwrite(tmp_path):
    original, output = tmp_path / "raw.json", tmp_path / "audit.json"
    original.write_text(json.dumps(fixture()))
    before = original.read_bytes()
    command = [sys.executable, str(ROOT / "scripts/audit_answer_evidence.py"), str(original),
               "--output", str(output), "--suite", str(ROOT / "examples/answer-suite-v1/development.json"),
               "--allow-development"]
    first = subprocess.run(command, check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    saved = output.read_bytes()
    assert subprocess.run(command, check=False, capture_output=True).returncode != 0
    assert output.read_bytes() == saved and original.read_bytes() == before


def test_auditor_does_not_import_production_grader_or_runtime():
    import ast
    tree = ast.parse((ROOT / "scripts/audit_answer_evidence.py").read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith("agentproof") for name in imports)
