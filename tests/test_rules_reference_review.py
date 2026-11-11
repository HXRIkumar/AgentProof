"""Independent control checks with temporary, explicitly mocked live-shaped inputs.

These are unit/integration fixtures, not real-model observations or study results.
No published reports or independent evaluation cases are consumed here.
"""

import asyncio
import copy
import hashlib
import json
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

import agentproof.rules_reference as reference_module
from agentproof.api import create_app
from agentproof.comparison import ComparisonError
from agentproof.engine import Engine
from agentproof.providers import LiveProvider
from agentproof.rules import RulesProvider, decide
from agentproof.rules_reference import run_reference
from agentproof.scenarios import BY_ID


@pytest.fixture
def mock_reference(tmp_path, monkeypatch):
    """Produce schema-valid paired evidence via the API and a mock HTTP transport."""
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "mock-live-rules-review")
    monkeypatch.setenv("AGENTPROOF_MODEL_REVISION", "unit-test-transport-only")
    monkeypatch.delenv("AGENTPROOF_API_KEY", raising=False)
    calls = []

    def create(cases, repeats=2):
        def response(request):
            body = json.loads(request.content)
            facts = json.loads(body["messages"][1]["content"])
            calls.append(copy.deepcopy(facts))
            return httpx.Response(200, json={
                "choices": [{"message": {"content": decide(facts).model_dump_json()}}],
                "usage": {"total_tokens": 10},
            })

        transport = httpx.AsyncClient(transport=httpx.MockTransport(response))
        adapter = LiveProvider(transport)
        app = create_app(tmp_path / "mock-input.sqlite3", provider_factory=lambda _: adapter)
        try:
            with TestClient(app) as client:
                result = client.post("/api/experiments", json={
                    "provider": "openai", "repeats": repeats,
                    "scenarios": [case.model_dump() for case in cases],
                })
            assert result.status_code == 201, result.text
            document = result.json()
            assert document["status"] == "completed"
            # Make the fixture identity unmistakable in retained raw input.
            document["notes"].append("Independent test fixture: MockTransport, no model calls.")
            path = tmp_path / "mock-reference.json"
            path.write_text(json.dumps(document))
            return path, document, calls
        finally:
            asyncio.run(transport.aclose())

    return create


def test_only_actual_live_model_faults_are_excluded(mock_reference, tmp_path, monkeypatch):
    case_ids = [
        "eligible", "amount-injection", "wrong-order", "malformed", "model-outage",
        "stale-policy", "read-outage", "approval", "unknown-order",
    ]
    path, reference, http_facts = mock_reference([BY_ID[key] for key in case_ids])
    original_bytes = path.read_bytes()
    observed = []
    actual_propose = RulesProvider.propose

    def capture(self, observation, *args, **kwargs):
        observed.append(copy.deepcopy(observation))
        return actual_propose(self, observation, *args, **kwargs)

    monkeypatch.setattr(RulesProvider, "propose", capture)
    output = tmp_path / "rules-control"
    summary = run_reference(path, output)
    raw = json.loads((output / "raw.json").read_text())
    excluded = {row["scenario_id"] for row in raw["applicability"] if not row["applicable"]}
    assert excluded == {"malformed", "model-outage"}
    included = set(case_ids) - excluded
    assert Counter(run["scenario_id"] for run in raw["rules_runs"]) == dict.fromkeys(included, 2)
    assert summary["live_guarded"]["trials"] == summary["rules_guarded"]["trials"] == 14
    assert summary["rules_guarded"]["correct"] == 14
    assert summary["rules_guarded"]["model_calls"] == summary["rules_guarded"]["reported_tokens"] == 0
    assert raw["reference"] == reference and path.read_bytes() == original_bytes
    assert raw["reference_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert summary["raw_sha256"] == hashlib.sha256((output / "raw.json").read_bytes()).hexdigest()
    fields = {"order", "authenticated_customer", "requested_cents", "policy_version", "retrieved_note"}
    assert observed and http_facts
    assert all(set(facts) == fields for facts in observed + http_facts)
    assert all(run["prompt_hash"] is None for run in raw["rules_runs"])
    assert all(run["variant"] == "guarded" for run in raw["rules_runs"])
    assert "gate" not in summary


def test_wrong_label_is_retained_and_never_guides_rules(mock_reference, tmp_path):
    mislabeled = BY_ID["eligible"].model_copy(update={"expected_outcome": "rejected"})
    path, _, _ = mock_reference([mislabeled])
    output = tmp_path / "wrong-label"
    summary = run_reference(path, output)
    raw = json.loads((output / "raw.json").read_text())
    assert summary["live_guarded"]["correct"] == summary["rules_guarded"]["correct"] == 0
    assert summary["rules_guarded"]["trials"] == 2
    assert raw["reference"]["scenarios"][0]["expected_outcome"] == "rejected"
    assert all(run["outcome"] == "refunded" and not run["passed"] for run in raw["rules_runs"])
    assert all(run["final_state"]["total_refunded_cents"] == mislabeled.requested_cents
               for run in raw["rules_runs"])


def test_unfavorable_rules_result_still_reported_without_changing_denominator(
    mock_reference, tmp_path, monkeypatch,
):
    path, _, _ = mock_reference([BY_ID["eligible"]])

    def reject(self, observation, *args, **kwargs):
        proposal = decide(observation).model_copy(update={
            "action": "reject", "amount_cents": 0, "reason": "Controlled bad rules response.",
        })
        return proposal.model_dump_json(), 0

    monkeypatch.setattr(RulesProvider, "propose", reject)
    summary = run_reference(path, tmp_path / "unfavorable")
    assert summary["status"] == "completed"
    assert summary["live_guarded"]["correct"] == 2
    assert summary["rules_guarded"]["correct"] == 0
    assert summary["rules_guarded"]["effect_invariants"] == 2
    assert summary["case_results"] == [{
        "scenario_id": "eligible", "live_correct": 2, "rules_correct": 0, "trials_each": 2,
    }]


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError])
def test_interruption_retains_finished_prefix_and_never_writes_completed_summary(
    mock_reference, tmp_path, monkeypatch, error,
):
    path, _, _ = mock_reference([BY_ID["eligible"]])
    original_run = Engine.run
    calls = 0

    def stop_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error("controlled interruption")
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "run", stop_second)
    output = tmp_path / "partial"
    with pytest.raises(error):
        run_reference(path, output)
    raw = json.loads((output / "raw.json").read_text())
    assert raw["status"] == ("interrupted" if error is KeyboardInterrupt else "failed")
    assert raw["error_type"] == error.__name__
    assert len(raw["rules_runs"]) == 1 and raw["rules_runs"][0]["passed"]
    assert raw["active_case"] == {"scenario_id": "eligible", "repeat": 2}
    assert raw["finished_at"]
    assert not (output / "summary.json").exists()
    assert not (output / "report.md").exists()
    with pytest.raises(FileExistsError):
        run_reference(path, output)


def test_source_change_retains_prefix_as_failed_evidence(mock_reference, tmp_path, monkeypatch):
    path, _, _ = mock_reference([BY_ID["eligible"]])
    real_fingerprint = reference_module.source_fingerprint()
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        return real_fingerprint if calls <= 2 else "changed"

    monkeypatch.setattr(reference_module, "source_fingerprint", drift)
    output = tmp_path / "source-drift"
    with pytest.raises(RuntimeError, match="Source changed"):
        run_reference(path, output)
    raw = json.loads((output / "raw.json").read_text())
    assert raw["status"] == "failed" and len(raw["rules_runs"]) == 1
    assert not (output / "summary.json").exists()


def test_no_applicable_cases_is_not_an_empty_perfect_score(mock_reference, tmp_path):
    path, _, _ = mock_reference([BY_ID["malformed"], BY_ID["model-outage"]])
    output = tmp_path / "empty"
    with pytest.raises(ComparisonError, match="No applicable cases"):
        run_reference(path, output)
    assert not output.exists()


def test_completed_input_with_error_metadata_is_refused(mock_reference, tmp_path):
    path, document, _ = mock_reference([BY_ID["eligible"]])
    document["error"] = {"type": "ConfigurationChanged", "message": "Controlled invalid input."}
    path.write_text(json.dumps(document))
    output = tmp_path / "invalid-completion"
    with pytest.raises(ComparisonError):
        run_reference(path, output)
    assert not output.exists()
