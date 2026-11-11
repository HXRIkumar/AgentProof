"""Independent regression tests for reproduced provider, grading, and input defects."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from agentproof.comparison import ComparisonError, compare_reports
from agentproof.grading import grade
from agentproof.models import Order, Scenario
from agentproof.providers import LiveProvider, ProviderFailure


@pytest.mark.parametrize(
    "usage",
    [None, [], {"total_tokens": -42}, {"total_tokens": True}, {"total_tokens": 4.9}],
)
def test_malformed_provider_usage_is_a_bounded_provider_failure(monkeypatch, usage):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "audit-mock")
    response = {
        "choices": [{"message": {"content": '{"action":"reject"}'}}],
        "usage": usage,
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    ) as client, pytest.raises(ProviderFailure):
        LiveProvider(client).propose({"order": Order().model_dump()})


APPROVAL_SCENARIO = Scenario(
    id="audit-approval",
    name="Audit high-value approval",
    category="approval",
    description="A successful approval stop needs an actionable valid pending proposal.",
    order=Order(paid_cents=18000),
    requested_cents=18000,
    expected_outcome="approval_required",
)
VALID_PENDING = {
    "action": "refund",
    "order_id": "ORD-1042",
    "customer_id": "CUS-17",
    "amount_cents": 18000,
    "policy_version": "refund-v1",
    "reason": "Eligible high-value request awaiting approval.",
}


@pytest.mark.parametrize(
    "pending",
    [
        None,
        {},
        {**VALID_PENDING, "action": "reject"},
        {**VALID_PENDING, "order_id": "ORD-OTHER"},
        {**VALID_PENDING, "customer_id": "CUS-OTHER"},
        {**VALID_PENDING, "amount_cents": 9000},
        {**VALID_PENDING, "policy_version": "refund-stale"},
    ],
)
def test_approval_stop_without_valid_pending_action_cannot_pass(pending):
    run = {"status": "awaiting_approval", "outcome": "approval_required"}
    if pending is not None:
        run["pending_proposal"] = pending
    checks = grade(APPROVAL_SCENARIO, run, [])
    assert not all(check["passed"] for check in checks)


def test_valid_approval_stop_remains_a_success_without_monetary_effect():
    run = {
        "status": "awaiting_approval",
        "outcome": "approval_required",
        "pending_proposal": VALID_PENDING,
    }
    assert all(check["passed"] for check in grade(APPROVAL_SCENARIO, run, []))


@pytest.mark.parametrize("value", [True, "1", 1.0])
@pytest.mark.parametrize("field", ["requested_cents", "age_days", "paid_cents", "refunded_cents"])
def test_scenario_numeric_fields_reject_coercion(field, value):
    payload = {
        "id": "audit-types",
        "name": "Audit numeric input",
        "category": "schema",
        "description": "Integer units must be supplied as JSON integers.",
    }
    if field == "requested_cents":
        payload[field] = value
    else:
        payload["order"] = {field: value}
    with pytest.raises(ValidationError):
        Scenario.model_validate_json(json.dumps(payload))


@pytest.fixture
def audit_report():
    return json.loads(
        (Path(__file__).parents[1] / "reports/qwen35-4b-live-v1.json").read_text()
    )


@pytest.mark.parametrize("metric", ["model_calls", "token_usage", "retries"])
def test_comparison_requires_integer_counts(audit_report, metric):
    audit_report["runs"][0][metric] = 0.5
    with pytest.raises(ComparisonError):
        compare_reports(audit_report, audit_report)


@pytest.mark.parametrize("setting", ["max_tokens", "temperature", "timeout_seconds", "variant_order"])
def test_comparison_missing_settings_on_both_reports_is_not_equivalence(audit_report, setting):
    del audit_report["configuration"][setting]
    with pytest.raises(ComparisonError):
        compare_reports(audit_report, audit_report)


def test_comparison_requires_integer_monetary_effects(audit_report):
    effect = next(r for r in audit_report["runs"] if r["final_state"]["effects"])["final_state"][
        "effects"
    ][0]
    effect["amount_cents"] = float(effect["amount_cents"])
    with pytest.raises(ComparisonError):
        compare_reports(audit_report, audit_report)


@pytest.mark.parametrize("version", ["refund release 2", "refund.v2."])
def test_recovery_preserves_opaque_policy_version(tmp_path, version):
    from agentproof.engine import Engine
    from agentproof.store import Store

    scenario = Scenario(
        id="audit-policy-identifier",
        name="Policy identifier",
        category="policy",
        description="An opaque policy identifier must survive correction unchanged.",
        current_policy=version,
        observed_policy="old-policy",
    )
    run = Engine(Store(tmp_path / "policy.sqlite")).run(scenario)
    assert run["passed"]
    assert run["final_state"]["effects"][0]["policy_version"] == version
