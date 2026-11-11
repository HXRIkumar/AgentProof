import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from agentproof.ablation import (
    AblationError,
    analyse_ablation,
    atomic_json,
    load_suites,
    make_schedule,
    run_ablation,
    write_analysis,
)
from agentproof.engine import Engine, EngineOptions
from agentproof.providers import ScriptedProvider
from agentproof.scenarios import BY_ID
from agentproof.store import Store


@pytest.mark.parametrize("value", [0, 2, 4, True, "3", 3.0, None])
def test_only_declared_integer_budgets_are_supported(value):
    with pytest.raises(ValueError):
        EngineOptions(max_proposals=value)


def test_options_are_immutable_and_do_not_change_other_engines(tmp_path):
    store = Store(tmp_path / "options.sqlite")
    one = Engine(store, options=EngineOptions(max_proposals=1))
    default = Engine(store)
    with pytest.raises(FrozenInstanceError):
        one.options.max_proposals = 3
    with pytest.raises(AttributeError):
        one.options = EngineOptions()
    first = one.run(BY_ID["malformed"])
    second = default.run(BY_ID["malformed"])
    assert first["outcome"] == "escalated" and first["proposal_calls"] == 1
    assert first["final_state"]["effects"] == []
    assert second["passed"] and second["proposal_calls"] == 2
    assert first["engine_options"] == {"max_proposals": 1}
    assert second["engine_options"] == {"max_proposals": 3}
    assert Engine.MAX_PROPOSALS == 3
    assert default.replay(first["id"])["engine_options"] == {"max_proposals": 1}


@pytest.mark.parametrize("budget", [1, 3])
@pytest.mark.parametrize(
    "case", ["wrong-owner", "over-balance", "duplicate", "approval", "stale-policy"]
)
def test_both_budgets_keep_effect_invariants(tmp_path, budget, case):
    run = Engine(Store(tmp_path / "controls.sqlite"), options=EngineOptions(budget)).run(
        BY_ID[case]
    )
    assert run["safe"]
    assert run["proposal_calls"] <= budget
    if case == "approval":
        assert run["status"] == "awaiting_approval"
        assert run["final_state"]["effects"] == []
    if case == "stale-policy" and budget == 1:
        assert run["outcome"] == "escalated"
        assert run["final_state"]["effects"] == []


def test_schedule_is_saved_reproducible_balanced_and_guarded_only():
    suites = load_suites()
    schedule = make_schedule(suites, 42)
    assert schedule == make_schedule(suites, 42)
    assert schedule != make_schedule(suites, 43)
    assert len(schedule) == 216
    firsts = {}
    for index in range(0, len(schedule), 2):
        first, second = schedule[index : index + 2]
        assert {first["arm"], second["arm"]} == {"A1", "A3"}
        assert (first["suite_id"], first["scenario_id"], first["repeat"]) == (
            second["suite_id"],
            second["scenario_id"],
            second["repeat"],
        )
        firsts.setdefault((first["suite_id"], first["scenario_id"]), []).append(first["arm"])
    assert all(set(arms) == {"A1", "A3"} for arms in firsts.values())


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ablation") / "study"
    document = run_ablation(directory)
    assert document["status"] == "completed"
    return document, directory


def test_complete_fixture_is_216_executions_without_model_calls(completed):
    document, directory = completed
    summary = analyse_ablation(document)
    assert summary["complete"] and summary["planned_trials"] == summary["finished_trials"] == 216
    assert summary["suites"]["original"]["A1"]["trials"] == 48
    assert summary["suites"]["challenge"]["A3"]["trials"] == 60
    assert summary["suites"]["original"]["A3"]["correct"] == 48
    assert summary["suites"]["challenge"]["A3"]["correct"] == 60
    assert summary["adoption"]["correctness_supported"]
    assert all(r["run"]["variant"] == "guarded" for r in document["records"])
    assert sum(r["run"]["model_calls"] for r in document["records"]) == 0
    before = (directory / "raw.json").read_bytes()
    write_analysis(directory / "raw.json")
    assert (directory / "raw.json").read_bytes() == before
    assert (directory / "summary.json").exists() and (directory / "report.md").exists()
    with pytest.raises(FileExistsError):
        run_ablation(directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_budget",
        "changed_model",
        "source",
        "duplicate",
        "schedule",
        "false_grade",
        "partial_completed",
    ],
)
def test_invalid_evidence_cannot_support_an_ablation(completed, mutation):
    document = copy.deepcopy(completed[0])
    row = document["records"][0]
    if mutation == "wrong_budget":
        row["run"]["engine_options"] = {"max_proposals": 2}
    elif mutation == "changed_model":
        row["run"]["model"] = "different-model"
    elif mutation == "source":
        row["source_sha256"] = "different-source"
    elif mutation == "duplicate":
        document["records"][1]["run"]["id"] = row["run"]["id"]
    elif mutation == "schedule":
        document["records"][0], document["records"][1] = (
            document["records"][1],
            document["records"][0],
        )
    elif mutation == "false_grade":
        row["run"]["passed"] = not row["run"]["passed"]
    else:
        document["records"].pop()
    with pytest.raises(AblationError):
        analyse_ablation(document)


def test_aggregate_gain_cannot_hide_one_case_regression(completed):
    document = copy.deepcopy(completed[0])
    row = next(
        r for r in document["records"] if r["arm"] == "A3" and r["scenario_id"] == "eligible"
    )
    run = row["run"]
    run.update(passed=False, safe=True, outcome="escalated", status="completed")
    run["final_state"] = {"effects": [], "total_refunded_cents": 0, "approval": None}
    summary = analyse_ablation(document)
    assert summary["suites"]["challenge"]["additional_correct"] > 0
    assert not summary["adoption"]["correctness_supported"]
    assert any("original/eligible" in reason for reason in summary["adoption"]["reasons"])


@pytest.mark.parametrize(
    "exception,status", [(KeyboardInterrupt, "interrupted"), (RuntimeError, "failed")]
)
def test_interruption_keeps_prefix_and_active_trial_without_resume(tmp_path, exception, status):
    class InterruptingProvider(ScriptedProvider):
        def __init__(self):
            self.calls = 0

        def propose(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 3:
                raise exception("private detail must not enter raw error")
            return super().propose(*args, **kwargs)

    provider = InterruptingProvider()
    directory = tmp_path / "partial"
    document = run_ablation(directory, provider_factory=lambda _: provider)
    persisted = json.loads((directory / "raw.json").read_text())
    assert persisted == document and document["status"] == status
    assert 0 < len(document["records"]) < 216
    assert document["active_trial"] is not None
    assert "private detail" not in json.dumps(document)
    assert not analyse_ablation(document)["adoption"]["correctness_supported"]
    assert (directory / "ledger.sqlite3").exists()


def test_configuration_drift_stops_before_the_next_model_call(tmp_path):
    class ChangingProvider(ScriptedProvider):
        def propose(self, *args, **kwargs):
            result = super().propose(*args, **kwargs)
            self.model = "changed-mid-study"
            return result

    adapter = ChangingProvider()
    document = run_ablation(tmp_path / "changed", provider_factory=lambda _: adapter)
    assert document["status"] == "failed"
    assert len(document["records"]) == 1
    assert not analyse_ablation(document)["adoption"]["correctness_supported"]


def test_atomic_checkpoint_does_not_replace_last_good_json_on_encoding_failure(tmp_path):
    path = tmp_path / "raw.json"
    atomic_json(path, {"valid": True})
    with pytest.raises(ValueError):
        atomic_json(path, {"invalid": float("nan")})
    assert json.loads(path.read_text()) == {"valid": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("bad_budget", [True, 1.0])
def test_analysis_rejects_coerced_arm_budget(completed, bad_budget):
    document = copy.deepcopy(completed[0])
    row = next(row for row in document["records"] if row["arm"] == "A1")
    row["run"]["engine_options"]["max_proposals"] = bad_budget
    with pytest.raises(AblationError):
        analyse_ablation(document)


@pytest.mark.parametrize("status", ["running", "failed", "interrupted"])
def test_full_trial_count_alone_cannot_certify_unfinished_status(completed, status):
    document = copy.deepcopy(completed[0])
    document["status"] = status
    summary = analyse_ablation(document)
    assert summary["finished_trials"] == 216
    assert summary["complete"] is False
    assert summary["adoption"]["correctness_supported"] is False


def test_remote_live_endpoint_is_rejected_without_a_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "not-called")
    monkeypatch.setenv("AGENTPROOF_API_KEY", "dummy-test-token")
    monkeypatch.setenv("AGENTPROOF_MODEL_REVISION", "test-revision")
    with pytest.raises(AblationError, match="local inference"):
        run_ablation(tmp_path / "remote", provider="openai")
    assert not (tmp_path / "remote").exists()
