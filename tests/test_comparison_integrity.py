"""Adversarial metadata copies and compatibility checks; no evidence or model changes."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from agentproof.comparison import ComparisonError, compare_reports, validate_experiment_export
from agentproof.evidence import CATALOG, EvidenceLibrary

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def live():
    return json.loads((ROOT / "reports/qwen35-4b-live-v1.json").read_text())


def rehash(document):
    # Deliberately allow NaN/Infinity here: invalid values must fail validation
    # even when both synthetic inputs carry a matching recomputed hash.
    document["config_hash"] = hashlib.sha256(
        json.dumps(document["configuration"], sort_keys=True).encode()
    ).hexdigest()


@pytest.mark.parametrize("key,value", [
    ("temperature", float("inf")), ("temperature", float("nan")),
    ("temperature", -1), ("temperature", 3), ("temperature", True),
    ("temperature", "0"), ("temperature", 10**400),
    ("timeout_seconds", -1), ("timeout_seconds", 0), ("timeout_seconds", 121),
    ("timeout_seconds", None), ("timeout_seconds", True),
    ("timeout_seconds", float("inf")), ("timeout_seconds", 10**400),
    ("max_tokens", True), ("max_tokens", 512.0), ("max_tokens", "512"),
    ("max_tokens", 0), ("max_tokens", 2049), ("max_tokens", None),
    ("disable_thinking", "false"), ("disable_thinking", 0),
    ("max_proposals", 0), ("max_proposals", 2), ("max_proposals", True),
    ("max_proposals", 3.0), ("variant_order", []), ("variant_order", "unknown"),
    ("model_revision", {}), ("model_revision", ""), ("model_revision", "   "),
    ("model_revision", " unrecorded "), ("model", None), ("model", " "),
])
def test_shared_invalid_settings_fail_even_with_recomputed_hash(live, key, value):
    live["configuration"][key] = value
    rehash(live)
    with pytest.raises(ComparisonError):
        compare_reports(live, copy.deepcopy(live))


def test_unsupported_provider_cannot_be_legitimized_by_matching_metadata(live):
    live["provider"] = live["configuration"]["provider"] = "invented-provider"
    for run in live["runs"]:
        run["provider"] = "invented-provider"
    rehash(live)
    with pytest.raises(ComparisonError, match="provider"):
        compare_reports(live, copy.deepcopy(live))


def test_unknown_generation_setting_is_not_silently_excluded_from_comparison(live):
    live["configuration"]["undeclared_top_p"] = .5
    rehash(live)
    with pytest.raises(ComparisonError, match="unsupported evaluation"):
        compare_reports(live, copy.deepcopy(live))


@pytest.mark.parametrize("value", [None, "", "0" * 64, "not-a-hash", 123])
def test_configuration_hash_must_be_present_and_match(live, value):
    if value is None:
        live.pop("config_hash")
    else:
        live["config_hash"] = value
    with pytest.raises(ComparisonError, match="config_hash"):
        compare_reports(live, copy.deepcopy(live))


def test_valid_changed_configuration_still_requires_new_hash(live):
    live["configuration"]["max_tokens"] = 1024
    with pytest.raises(ComparisonError, match="config_hash"):
        compare_reports(live, copy.deepcopy(live))
    rehash(live)
    assert compare_reports(live, copy.deepcopy(live))["gate"]["passed"]


def test_valid_generation_mismatch_is_refused_after_both_hashes_validate(live):
    candidate = copy.deepcopy(live)
    candidate["configuration"]["max_tokens"] = 1024
    rehash(candidate)
    validate_experiment_export(candidate)
    with pytest.raises(ComparisonError, match="Model/evaluation settings differ: max_tokens"):
        compare_reports(live, candidate)


@pytest.mark.parametrize("value", [None, "", "new-prompt", {}, True])
def test_shared_missing_or_malformed_prompt_hash_is_not_comparable(live, value):
    live["prompt_hash"] = value
    for run in live["runs"]:
        run["prompt_hash"] = value
    with pytest.raises(ComparisonError, match="prompt fingerprint"):
        compare_reports(live, copy.deepcopy(live))


def test_optional_legacy_endpoint_fingerprint_is_validated_when_present(live):
    assert "base_url_sha256" not in live["configuration"]
    validate_experiment_export(live)
    live["configuration"]["base_url_sha256"] = None
    rehash(live)
    with pytest.raises(ComparisonError, match="endpoint fingerprint"):
        compare_reports(live, copy.deepcopy(live))


@pytest.mark.parametrize("options", [
    None, {}, {"max_proposals": 1}, {"max_proposals": True}, {"max_proposals": 3.0},
    {"max_proposals": 3, "undeclared_option": True},
])
def test_declared_run_options_must_match_valid_shared_configuration(live, options):
    live["runs"][0]["engine_options"] = options
    with pytest.raises(ComparisonError, match="engine_options"):
        compare_reports(live, copy.deepcopy(live))


def test_legacy_absence_and_explicit_matching_run_options_are_supported(live):
    assert all("engine_options" not in run for run in live["runs"])
    legacy = compare_reports(live, copy.deepcopy(live))
    for run in live["runs"]:
        run["engine_options"] = {"max_proposals": 3}
    assert compare_reports(live, copy.deepcopy(live))["gate"] == legacy["gate"]


@pytest.mark.parametrize("value", [-1, 4, True, 1.0])
def test_recorded_proposal_calls_cannot_contradict_declared_budget(live, value):
    run = next(run for run in live["runs"] if run["variant"] == "guarded")
    run["proposal_calls"] = value
    with pytest.raises(ComparisonError, match="Proposal-call count"):
        compare_reports(live, copy.deepcopy(live))


def test_lower_shared_budget_cannot_hide_historical_multi_attempt_runs(live):
    live["configuration"]["max_proposals"] = 1
    rehash(live)
    assert any(run["proposal_calls"] > 1 for run in live["runs"])
    with pytest.raises(ComparisonError, match="Proposal-call count"):
        compare_reports(live, copy.deepcopy(live))


@pytest.mark.parametrize("reference,candidate", [
    ("fixture-v1.json", "fixture-v02.json"),
    ("qwen35-4b-live-v1.json", "qwen35-4b-live-v02.json"),
    ("challenge-v1-before.json", "challenge-v1-after.json"),
])
def test_genuine_historical_release_pairs_stay_valid_without_rewriting(reference, candidate):
    paths = [ROOT / "reports" / name for name in (reference, candidate)]
    original = [path.read_bytes() for path in paths]
    report = compare_reports(*(json.loads(raw) for raw in original))
    assert report["gate"]["passed"]
    assert [path.read_bytes() for path in paths] == original


def test_published_archive_and_rules_reference_inputs_remain_valid():
    paths = [ROOT / "reports" / entry.filename for entry in CATALOG]
    paths += [ROOT / "reports" / name / "raw.json" for name in (
        "rules-original-v1", "rules-challenge-v1",
    )]
    for path in paths:
        original = path.read_bytes()
        document = json.loads(original)
        validate_experiment_export(document.get("reference", document))
        assert path.read_bytes() == original
    # Exercise the application's hash-pinned archive loader as well as comparison.
    library = EvidenceLibrary()
    for entry in CATALOG:
        _, envelope = library.load(entry.id)
        assert envelope["archive"]["id"] == entry.id
