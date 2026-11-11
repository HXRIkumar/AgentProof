"""Accounting regressions using explicit fixtures and MockTransport, never model inference."""

import asyncio
import copy
import json

import httpx
import pytest

from agentproof.ablation import (
    _metrics,
    _model_attempt_events,
    analyse_ablation,
    digest,
    load_suites,
    run_ablation,
    write_analysis,
)
from agentproof.engine import Engine
from agentproof.providers import LiveProvider
from agentproof.scenarios import BY_ID
from agentproof.store import Store


def diagnostic(**updates):
    return {
        "http_status": 200,
        "finish_reason": "stop",
        "usage_present": True,
        "usage_known": True,
        "usage_status": "reported",
        "content_utf8_bytes": 10,
        "content_sha256": "0" * 64,
        "parse_category": "valid",
        **updates,
    }


@pytest.fixture(scope="module")
def live_shaped_study(tmp_path_factory):
    """Synthetic analyser input; its live-shaped metadata is not observed model data."""
    document = run_ablation(tmp_path_factory.mktemp("usage-review") / "scripted")
    assert document["status"] == "completed"
    document["configuration"].update(
        provider="openai",
        model="mock-accounting-fixture",
        model_revision="synthetic-no-model-inference",
        timeout_seconds=1,
        max_tokens=128,
    )
    document["configuration_sha256"] = digest(document["configuration"])
    document["warmup"] = {
        "status": "completed",
        "model_calls": 1,
        "reported_tokens": 10,
        "latency_ms": 1,
        "excluded_from_trial_metrics": True,
    }
    cases = {
        (suite["id"], case["id"]): case
        for suite in load_suites()
        for case in suite["scenarios"]
    }
    for row in document["records"]:
        row["configuration_sha256"] = document["configuration_sha256"]
        run = row["run"]
        injections = sum(e["name"] == "inject_provider_fault" for e in run["events"])
        run.update(
            provider="openai", model="mock-accounting-fixture",
            model_calls=run["proposal_calls"] - injections, latency_ms=1,
        )
        run["token_usage"] = 10 if run["model_calls"] else 0
        fault = cases[(row["suite_id"], row["scenario_id"])]["fault"]
        for event in run["events"]:
            if event["name"] != "propose_action" or fault == "model_outage":
                continue
            if fault == "malformed" and event["detail"]["attempt"] == 1:
                continue
            event["detail"]["response_diagnostics"] = diagnostic()
    return document


def retry_row(document):
    return next(row for row in document["records"] if row["run"]["model_calls"] >= 2)


def proposal_events(row):
    return [e for e in row["run"]["events"] if e["name"] == "propose_action"]


def test_complete_response_accounting_keeps_separate_correctness(live_shaped_study):
    report = analyse_ablation(live_shaped_study)
    assert report["usage_analysis_policy"] == "per_response_diagnostics"
    assert report["adoption"]["correctness_supported"]
    assert report["adoption"]["passes_declared_study_rules"]
    for suite in report["suites"].values():
        assert suite["token_efficiency_evidence"] == "reported_usage_for_all_model_attempts"
        for arm in ("A1", "A3"):
            coverage = suite[arm]["token_usage_coverage"]
            assert coverage["accounted_attempts"] == suite[arm]["model_calls"]
            assert coverage["incomplete_attempts"] == 0


@pytest.mark.parametrize("replacement,gap", [
    (diagnostic(usage_present=False, usage_known=False, usage_status="missing"),
     "unknown_reported_usage"),
    (diagnostic(usage_known=False, usage_status="missing_total_tokens"),
     "unknown_reported_usage"),
    (diagnostic(usage_known=False, usage_status="invalid"), "unknown_reported_usage"),
    (diagnostic(http_status=None), "unavailable_response_accounting"),
    (diagnostic(parse_category="not_attempted"), "rejected_response_wrapper"),
    (None, "missing_response_diagnostics"),
])
def test_positive_trial_total_cannot_hide_missing_attempt_usage(
    live_shaped_study, replacement, gap
):
    document = copy.deepcopy(live_shaped_study)
    row = retry_row(document)
    event = proposal_events(row)[0]
    event["detail"]["response_diagnostics"] = replacement
    assert row["run"]["model_calls"] >= 2 and row["run"]["token_usage"] > 0
    before = json.dumps(document, sort_keys=True)
    report = analyse_ablation(document)
    assert json.dumps(document, sort_keys=True) == before
    assert report["adoption"]["correctness_supported"]
    assert not report["adoption"]["passes_declared_study_rules"]
    suite = report["suites"][row["suite_id"]]
    coverage = suite[row["arm"]]["token_usage_coverage"]
    assert coverage["incomplete_attempts"] == 1
    assert coverage["trials_with_incomplete_accounting"] == 1
    assert coverage["gap_reasons"] == {gap: 1}
    assert suite["additional_reported_tokens_per_additional_correct"] is None


def test_no_response_in_another_trial_is_not_reclassified_as_legacy(live_shaped_study):
    document = copy.deepcopy(live_shaped_study)
    row = next(row for row in document["records"] if row["run"]["model_calls"] == 1)
    event = proposal_events(row)[-1]
    del event["detail"]["response_diagnostics"]
    report = analyse_ablation(document)
    assert report["usage_analysis_policy"] == "per_response_diagnostics"
    assert not report["adoption"]["passes_declared_study_rules"]
    coverage = report["suites"][row["suite_id"]][row["arm"]]["token_usage_coverage"]
    assert coverage["gap_reasons"] == {"missing_response_diagnostics": 1}


def test_rejected_wrapper_with_known_usage_does_not_count_as_accounted(live_shaped_study):
    document = copy.deepcopy(live_shaped_study)
    row = retry_row(document)
    event = proposal_events(row)[0]
    event.update(status="error")
    event["detail"]["error"] = "ProviderFailure"
    # Fail closed even if an inconsistent diagnostic claims proposal parsing occurred.
    event["detail"]["response_diagnostics"] = diagnostic()
    report = analyse_ablation(document)
    assert report["adoption"]["correctness_supported"]
    assert not report["adoption"]["passes_declared_study_rules"]
    assert report["suites"][row["suite_id"]][row["arm"]]["token_usage_coverage"][
        "gap_reasons"
    ] == {"rejected_response_wrapper": 1}


def test_injected_attempts_need_no_response_telemetry(live_shaped_study):
    document = copy.deepcopy(live_shaped_study)
    row = next(row for row in document["records"] if row["scenario_id"] == "malformed")
    proposal_events(row)[0]["detail"]["response_diagnostics"] = diagnostic(
        usage_known=False, usage_status="missing"
    )
    report = analyse_ablation(document)
    assert report["adoption"]["passes_declared_study_rules"]


def test_legacy_policy_is_explicit_and_retained_without_rewriting_raw(
    live_shaped_study, tmp_path
):
    document = copy.deepcopy(live_shaped_study)
    for row in document["records"]:
        for event in row["run"]["events"]:
            event["detail"].pop("response_diagnostics", None)
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(document))
    before = raw.read_bytes()
    report = write_analysis(raw)
    assert raw.read_bytes() == before
    assert report["usage_analysis_policy"] == "legacy_aggregate_only"
    assert report["adoption"]["passes_declared_study_rules"]
    for suite in report["suites"].values():
        assert suite["token_efficiency_evidence"] == "legacy_aggregate_only"
        for arm in ("A1", "A3"):
            assert suite[arm]["token_usage_coverage"]["accounted_attempts"] is None
            assert suite[arm]["token_usage_coverage"]["incomplete_attempts"] is None
    markdown = (tmp_path / "report.md").read_text()
    assert "legacy_aggregate_only" in markdown
    assert "Positive totals do not establish complete usage coverage" in markdown


def test_reported_zero_retains_historical_uncertainty_guard(live_shaped_study):
    document = copy.deepcopy(live_shaped_study)
    row = retry_row(document)
    row["run"]["token_usage"] = 0
    report = analyse_ablation(document)
    assert report["adoption"]["correctness_supported"]
    assert not report["adoption"]["passes_declared_study_rules"]
    coverage = report["suites"][row["suite_id"]][row["arm"]]["token_usage_coverage"]
    assert coverage["incomplete_attempts"] == 0


@pytest.mark.parametrize("first_usage,first_content,expected_gap", [
    (None, "{", "unknown_reported_usage"),
    ({"total_tokens": 7}, "{", None),
    ({"total_tokens": 7}, None, "rejected_response_wrapper"),
])
def test_actual_provider_retry_metadata_matches_token_tuple_accounting(
    tmp_path, monkeypatch, first_usage, first_content, expected_gap
):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "mock-usage-test")
    monkeypatch.delenv("AGENTPROOF_API_KEY", raising=False)
    case = BY_ID["eligible"]
    calls = []

    def response(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            body = {"choices": [{"finish_reason": "length", "message": {"content": first_content}}]}
            if first_usage is not None:
                body["usage"] = first_usage
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "action": "refund", "order_id": case.order.id,
                "customer_id": case.authenticated_customer,
                "amount_cents": case.requested_cents, "policy_version": case.current_policy,
                "reason": "Mock response only.",
            })}}],
            "usage": {"total_tokens": 10},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    try:
        adapter = LiveProvider(client)
        run = Engine(Store(tmp_path / "usage.sqlite"), lambda _: adapter).run(
            case, provider="openai"
        )
    finally:
        asyncio.run(client.aclose())
    assert run["passed"] and run["safe"] and run["model_calls"] == len(calls) == 2
    assert len(_model_attempt_events(run, case)) == 2
    assert run["token_usage"] == (17 if expected_gap is None else 10)
    coverage = _metrics([run], {case.id: case}, metadata_aware=True)["token_usage_coverage"]
    assert coverage["gap_reasons"] == ({expected_gap: 1} if expected_gap else {})
    assert coverage["accounted_attempts"] == (1 if expected_gap else 2)
