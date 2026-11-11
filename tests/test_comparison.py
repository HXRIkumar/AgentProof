import copy
import json
from pathlib import Path

import pytest

from agentproof.comparison import ComparisonError, compare_reports


@pytest.fixture
def report():
    return json.loads((Path(__file__).parents[1] / "reports/fixture-v1.json").read_text())


def mark_failure(run):
    run.update(status="completed", outcome="escalated", passed=False, safe=True)
    run["final_state"] = {"effects": [], "total_refunded_cents": 0, "approval": None}


def test_identical_complete_reports_pass(report):
    result = compare_reports(report, copy.deepcopy(report))
    assert result["gate"]["passed"]
    assert len(result["case_changes"]) == 48
    assert result["variants"]["guarded"]["after"]["correct"] == 24


def test_case_regression_fails_even_if_aggregate_improves(report):
    old = copy.deepcopy(report)
    guarded = [r for r in old["runs"] if r["variant"] == "guarded" and r["outcome"] == "refunded"]
    for run in guarded[:2]:
        mark_failure(run)
    new = copy.deepcopy(report)
    lost_id = guarded[2]["id"]
    mark_failure(next(r for r in new["runs"] if r["id"] == lost_id))
    result = compare_reports(old, new)
    assert result["variants"]["guarded"]["after"]["correct"] > result["variants"]["guarded"]["before"]["correct"]
    assert not result["gate"]["passed"]
    assert any("regression" in x for x in result["gate"]["reasons"])


@pytest.mark.parametrize("status", ["running", "queued", "failed", "cancelled"])
def test_partial_status_cannot_pass(report, status):
    other = copy.deepcopy(report)
    other["status"] = status
    with pytest.raises(ComparisonError, match="completed"):
        compare_reports(report, other)


def test_missing_run_refused(report):
    other = copy.deepcopy(report)
    other["runs"].pop()
    with pytest.raises(ComparisonError, match="coverage"):
        compare_reports(report, other)


def test_duplicate_run_refused(report):
    other = copy.deepcopy(report)
    other["runs"][1] = other["runs"][0]
    with pytest.raises(ComparisonError, match="Duplicate run"):
        compare_reports(report, other)


def test_suite_label_change_refused(report):
    other = copy.deepcopy(report)
    other["scenarios"][0]["expected_outcome"] = "escalated"
    with pytest.raises(ComparisonError, match="hash"):
        compare_reports(report, other)


def test_false_grade_detected_by_independent_regrading(report):
    other = copy.deepcopy(report)
    run = next(r for r in other["runs"] if r["variant"] == "guarded" and r["outcome"] == "refunded")
    run["final_state"]["effects"][0]["amount_cents"] += 1
    with pytest.raises(ComparisonError, match="regraded"):
        compare_reports(report, other)


def test_model_settings_mismatch_refused(report):
    other = copy.deepcopy(report)
    other["configuration"]["max_proposals"] = 5
    with pytest.raises(ComparisonError, match="max_proposals"):
        compare_reports(report, other)


def test_scripted_comparison_ignores_unused_live_settings(report):
    other = copy.deepcopy(report)
    other["configuration"].update(model_revision="unrecorded", disable_thinking=False)
    assert compare_reports(report, other)["gate"]["passed"]


def test_live_comparison_requires_matching_generation_settings():
    report = json.loads((Path(__file__).parents[1] / "reports/qwen35-4b-live-v1.json").read_text())
    other = copy.deepcopy(report)
    other["configuration"]["temperature"] = .8
    with pytest.raises(ComparisonError, match="temperature"):
        compare_reports(report, other)


def test_approved_report_not_comparable_to_preapproval(report):
    other = copy.deepcopy(report)
    run = next(r for r in other["runs"] if r["status"] == "awaiting_approval")
    run["approval_decision"] = True
    with pytest.raises(ComparisonError, match="pre-approval"):
        compare_reports(report, other)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "10"])
def test_invalid_metrics_refused(report, value):
    other = copy.deepcopy(report)
    other["runs"][0]["latency_ms"] = value
    with pytest.raises(ComparisonError, match="metric"):
        compare_reports(report, other)


def test_prompt_source_changes_are_recorded_not_rejected(report):
    other = copy.deepcopy(report)
    other["prompt_hash"] = "new-prompt"
    other["server_metadata"] = {"backend_source_sha256": "new-source"}
    for run in other["runs"]:
        run["prompt_hash"] = "new-prompt"
    result = compare_reports(report, other)
    assert result["prompt_changed"] and result["source_changed"]
    assert result["gate"]["passed"]


def test_live_unrecorded_revision_refused():
    report = json.loads((Path(__file__).parents[1] / "reports/qwen35-4b-live-v1.json").read_text())
    report["configuration"]["model_revision"] = "unrecorded"
    with pytest.raises(ComparisonError, match="revision"):
        compare_reports(report, report)


@pytest.mark.parametrize("key", ["max_tokens", "temperature", "timeout_seconds", "variant_order"])
def test_both_reports_missing_same_required_metadata_still_refused(report, key):
    del report["configuration"][key]
    with pytest.raises(ComparisonError, match="Missing evaluation settings"):
        compare_reports(report, report)


@pytest.mark.parametrize("key", ["model_calls", "token_usage", "retries"])
def test_count_metrics_cannot_be_fractional(report, key):
    report["runs"][0][key] = .5
    with pytest.raises(ComparisonError, match="metric"):
        compare_reports(report, report)


def test_float_money_in_export_is_not_an_integer_ledger(report):
    run = next(r for r in report["runs"] if r["final_state"]["effects"])
    effect = run["final_state"]["effects"][0]
    effect["amount_cents"] = float(effect["amount_cents"])
    with pytest.raises(ComparisonError, match="ledger"):
        compare_reports(report, report)
