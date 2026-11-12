"""Independent hosted accounting checks. All model I/O and keys are test doubles."""

import copy
import json
from dataclasses import asdict

import httpx
import pytest
from test_answer_cache_eval import fixture as cache_fixture
from test_answer_eval import RUNNER, FakeService, qa_case, report, result, trial
from test_answers_hosted import MESSAGES, make_adapter, response_body

from agentproof.answer_cache_eval import CacheEvidenceError, _response_usage, summarize_cache
from agentproof.answer_eval import cost_summary, strategy_summary, summarize_report
from agentproof.answers import ModelResponse
from agentproof.answers.provider import usage_for


def paid_response(*, known=True, reservation="one"):
    return ModelResponse("fixture", prompt_tokens=10 if known else None,
                         completion_tokens=20 if known else None, usage_known=known,
                         request_hash="fixture", billing={
                             "reservation_id": reservation,
                             "state": "settled" if known else "uncertain",
                             "estimated_cost_usd": .01 if known else None,
                             "accounted_usd": .01 if known else .05,
                         })


def blocked_response(reason="budget_exhausted"):
    return ModelResponse("", error="No request sent", request_sent=False,
                         blocked_reason=reason, request_hash="fixture")


def test_refusal_preserves_settled_usage_without_leaking_refusal_text(tmp_path):
    body = response_body(prompt=100, completion=20)
    body["choices"][0]["message"] = {"content": None, "refusal": "private test message"}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    adapter, client, ledger = make_adapter(tmp_path, handler)
    try:
        response = adapter.complete(MESSAGES, purpose="critic")
    finally:
        client.close()
    assert len(requests) == 1 and response.request_sent
    assert response.error and response.usage_known
    assert response.prompt_tokens == 100 and response.completion_tokens == 20
    assert response.billing["state"] == "settled"
    assert ledger.snapshot()["accounted_usd"] == response.billing["estimated_cost_usd"]
    assert "private test message" not in json.dumps(asdict(response))


def test_actual_study_counts_shared_initial_once_and_excludes_blocked():
    initial = paid_response()
    critic = paid_response(reservation="two")
    blocked = blocked_response()
    usages = [usage_for([(initial, True)]),
              usage_for([(initial, True), (critic, False), (blocked, False)])]
    document = {"initial_generations": [{"response": asdict(initial)}],
                "trials": [{"result": {"usage": value}} for value in usages]}
    usage = RUNNER.actual_usage(document)
    assert usage["calls"] == 2 and usage["paid_calls"] == 2
    assert usage["blocked_calls"] == 1 and usage["total_tokens"] == 60
    assert usage["estimated_cost_usd"] == .02 and usage["accounted_cost_usd"] == .02
    assert cost_summary(usages)["estimated_cost_usd"] == .03


def test_uncertain_initial_is_not_multiplied_across_policies_or_reported_zero():
    initial = paid_response(known=False)
    usages = [usage_for([(initial, True)]) for _ in range(3)]
    document = {"initial_generations": [{"response": asdict(initial)}],
                "trials": [{"result": {"usage": value}} for value in usages]}
    usage = RUNNER.actual_usage(document)
    assert usage["calls"] == 1 and usage["paid_calls"] == 1
    assert not usage["cost_known"] and usage["estimated_cost_usd"] is None
    assert usage["accounted_cost_usd"] == .05 and usage["total_tokens"] is None
    assert cost_summary(usages)["accounted_cost_usd"] == pytest.approx(.15)


def test_strategy_cost_per_correct_requires_known_cost_and_success():
    row = trial()
    row["result"]["usage"] = usage_for([(paid_response(), True)])
    summary = strategy_summary([row])
    assert summary["cost_per_correct_usd"] == .01
    assert summary["actual_paid_calls"] == 0 and summary["paid_calls"] == 1
    row["grade"]["correct"] = False
    assert strategy_summary([row])["cost_per_correct_usd"] is None
    row["result"]["usage"] = usage_for([(paid_response(known=False), True)])
    assert strategy_summary([row])["estimated_cost_usd"] is None


def test_local_reports_do_not_gain_hosted_cost_fields():
    assert cost_summary([{"calls": 1, "known": True}]) == {}
    assert "cost_known" not in strategy_summary([trial()])
    assert "cost_known" not in summarize_cache(cache_fixture())


def write_suite(path):
    cases = [qa_case(), copy.deepcopy(qa_case())]
    cases[1]["id"] = "second"
    path.write_text(json.dumps({"version": "fixture", "split": "development", "cases": cases}))


@pytest.mark.parametrize("reason", ["budget_exhausted", "credentials", "budget_guard", "paid_disabled"])
def test_blocked_initial_stops_without_running_or_skipping_to_next_case(tmp_path, reason):
    class BlockedService(FakeService):
        def generate_initial(self, request):
            response = blocked_response(reason)
            self.initials.append(response)
            return response

        def run(self, *args, **kwargs):
            pytest.fail("An unsent initial response must never be run as a trial")

    suite = tmp_path / "suite.json"
    write_suite(suite)
    service = BlockedService()
    document = RUNNER.run_benchmark(suite, tmp_path / "blocked", service=service)
    assert len(service.initials) == 1 and document["trials"] == []
    assert document["status"] == "blocked" and document["stop_reason"]["code"] == reason
    assert not document["summary"]["complete"]
    assert document["actual_usage"]["calls"] == 0
    assert document["actual_usage"]["blocked_calls"] == 1
    assert document["actual_usage"]["total_tokens"] == 0
    assert json.loads((tmp_path / "blocked/raw.json").read_text())["status"] == "blocked"


def test_blocked_critic_retains_partial_trial_then_stops_other_arms_and_cases(tmp_path):
    class BlockedCritic(FakeService):
        def run(self, request, initial_response=None, persist=False):
            self.inputs.append(request)
            output = result()
            output["attempts"] = [{"generation": asdict(initial_response)}]
            calls = [(initial_response, True)]
            if request.strategy != "baseline":
                denied = blocked_response()
                output["attempts"][0]["critic_response"] = asdict(denied)
                output["status"] = "failed"
                calls.append((denied, False))
            output["usage"] = usage_for(calls)
            return output

    suite = tmp_path / "suite.json"
    write_suite(suite)
    service = BlockedCritic()
    document = RUNNER.run_benchmark(suite, tmp_path / "partial", service=service)
    assert len(service.initials) == 1 and len(service.inputs) == 2
    assert len(document["trials"]) == 2 and document["status"] == "blocked"
    assert not document["summary"]["complete"]
    assert document["actual_usage"]["calls"] == 1
    assert document["actual_usage"]["blocked_calls"] == 1
    assert document["actual_usage"]["total_tokens"] == 20


def test_full_coverage_cannot_override_blocked_evidence():
    document = report([trial(strategy) for strategy in ("baseline", "validated", "adaptive")])
    document["trials"][2]["result"]["usage"]["blocked_calls"] = 1
    assert not summarize_report(document)["complete"]


def test_cache_audit_reconstructs_unsent_critic_and_cannot_mark_complete():
    document = cache_fixture()
    document["groups"][0]["replays"] = []
    document["groups"][0]["queries"] = []
    output = document["groups"][0]["cold"]["result"]
    generation = ModelResponse(**output["attempts"][0]["generation"])
    denied = blocked_response()
    output["attempts"][0]["critic_response"] = asdict(denied)
    output["usage"] = usage_for([(generation, False), (denied, False)])
    output["status"] = "failed"
    summary = summarize_cache(document)
    assert summary["actual_calls"] == 1 and summary["tokens"] == 20
    assert summary["blocked_calls"] == 1 and not summary["complete"]
    output["usage"]["actual_calls"] = 2
    with pytest.raises(CacheEvidenceError, match="actual_calls"):
        summarize_cache(document)


def test_cache_audit_regrades_known_and_unknown_billing():
    for known in (True, False):
        response = paid_response(known=known)
        output = {"attempts": [{"generation": asdict(response)}],
                  "usage": usage_for([(response, False)]), "cache": {"status": "miss"}}
        audit = _response_usage(output)
        assert audit["cost_known"] is known and audit["paid_calls"] == 1
        output["usage"]["accounted_cost_usd"] = 0
        with pytest.raises(CacheEvidenceError, match="accounted_cost_usd"):
            _response_usage(output)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True])
def test_invalid_cost_not_silently_zeroed(bad):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        cost_summary([{"paid_calls": 1, "cost_known": True, "estimated_cost_usd": bad}])
