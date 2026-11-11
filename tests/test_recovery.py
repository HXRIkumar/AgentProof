"""Correction can request a new proposal; it cannot manufacture an accepted action."""

import copy
import json

import pytest

from agentproof.engine import Engine
from agentproof.scenarios import BY_ID
from agentproof.store import Store


class RefusingProvider:
    model = "controlled-refusal-fixture"
    is_live = False

    def __init__(self, recover=True):
        self.observations = []
        self.recover = recover

    def propose(self, observation, feedback=None, fault="none", attempt=0):
        self.observations.append((copy.deepcopy(observation), feedback))
        accepted = self.recover and attempt > 0
        return json.dumps({
            "action": "refund" if accepted else "reject",
            "order_id": observation["order"]["id"] if observation["order"] else "unknown",
            "customer_id": observation["authenticated_customer"],
            "amount_cents": observation["requested_cents"] if accepted else 0,
            "policy_version": observation["policy_version"],
            "reason": "Controlled response to runtime feedback.",
        }), 0


def build(tmp_path, provider):
    store = Store(tmp_path / "recovery.sqlite3")
    return Engine(store, lambda _: provider), store


def test_refusal_gets_bounded_feedback_then_real_validated_proposal(tmp_path):
    provider = RefusingProvider()
    engine, store = build(tmp_path, provider)
    run = engine.run(BY_ID["eligible"], "guarded")
    assert run["passed"] and run["proposal_calls"] == 2 and run["retries"] == 1
    assert len(store.effects(run["id"])) == 1
    assert "authoritative" in provider.observations[1][1]
    assert all("expected_outcome" not in obs for obs, _ in provider.observations)


def test_persistent_refusal_escalates_without_fabricated_refund(tmp_path):
    provider = RefusingProvider(recover=False)
    engine, store = build(tmp_path, provider)
    run = engine.run(BY_ID["eligible"], "guarded")
    assert run["outcome"] == "escalated" and not run["passed"]
    assert run["proposal_calls"] == 3 and run["retries"] == 2
    assert not store.effects(run["id"])


@pytest.mark.parametrize("scenario_id", ["wrong-owner", "day-31", "over-balance", "zero", "processing"])
def test_invalid_request_is_not_coached_into_refund(tmp_path, scenario_id):
    provider = RefusingProvider()
    engine, store = build(tmp_path, provider)
    run = engine.run(BY_ID[scenario_id], "guarded")
    assert run["outcome"] == "rejected" and run["passed"]
    assert run["proposal_calls"] == 1 and not store.effects(run["id"])


def test_policy_refresh_changes_observed_version_before_correction(tmp_path):
    provider = RefusingProvider()
    engine, _ = build(tmp_path, provider)
    scenario = BY_ID["stale-policy"]
    run = engine.run(scenario, "guarded")
    assert run["passed"] and run["proposal_calls"] == 2
    assert provider.observations[0][0]["policy_version"] == scenario.observed_policy
    assert provider.observations[1][0]["policy_version"] == scenario.current_policy
    assert any(e["name"] == "refresh_policy" for e in run["events"])


def test_correction_cannot_bypass_human_approval(tmp_path):
    provider = RefusingProvider()
    engine, store = build(tmp_path, provider)
    run = engine.run(BY_ID["approval"], "guarded")
    assert run["passed"] and run["status"] == "awaiting_approval"
    assert not store.effects(run["id"])
    assert len(store.effects(engine.approve(run["id"], True)["id"])) == 1


def test_baseline_does_not_receive_guarded_correction(tmp_path):
    provider = RefusingProvider()
    engine, _ = build(tmp_path, provider)
    run = engine.run(BY_ID["eligible"], "baseline")
    assert run["outcome"] == "rejected" and run["proposal_calls"] == 1
    assert provider.observations[0][1] is None


def test_evaluation_label_cannot_drive_runtime_recovery(tmp_path):
    provider = RefusingProvider()
    engine, _ = build(tmp_path, provider)
    # Deliberately contradictory oracle; runtime follows domain facts, grading catches it.
    scenario = BY_ID["eligible"].model_copy(update={"expected_outcome": "rejected"})
    run = engine.run(scenario, "guarded")
    assert run["outcome"] == "refunded" and not run["passed"]


def test_missing_order_does_not_trigger_refund_correction(tmp_path):
    provider = RefusingProvider()
    engine, store = build(tmp_path, provider)
    run = engine.run(BY_ID["unknown-order"], "guarded")
    assert run["outcome"] == "escalated" and run["passed"]
    assert run["proposal_calls"] == 1 and not store.effects(run["id"])


@pytest.mark.parametrize("policy", ["refund release 2", "refund.v2."])
def test_opaque_policy_identifiers_are_not_parsed_from_prose(tmp_path, policy):
    engine = Engine(Store(tmp_path / "opaque.sqlite3"))
    scenario = BY_ID["stale-policy"].model_copy(update={"current_policy": policy})
    run = engine.run(scenario, "guarded")
    assert run["passed"]
    assert run["final_state"]["effects"][0]["policy_version"] == policy


def test_unsupported_requested_amount_rejected_before_execution():
    from pydantic import ValidationError

    from agentproof.models import Scenario

    data = BY_ID["approval"].model_dump()
    data["requested_cents"] = 1_000_001
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)
