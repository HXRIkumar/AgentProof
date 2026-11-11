"""Independent checks of ablation accounting, oracle separation and CLI interruption."""

import asyncio
import copy
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from agentproof.ablation import AblationError, analyse_ablation, digest, run_ablation
from agentproof.engine import Engine, EngineOptions
from agentproof.providers import LiveProvider, ProviderFailure, ScriptedProvider
from agentproof.scenarios import BY_ID
from agentproof.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    result = run_ablation(tmp_path_factory.mktemp("review") / "study")
    assert result["status"] == "completed"
    return result


@pytest.mark.parametrize("metric,value", [("model_calls", 1), ("token_usage", 1), ("retries", 999)])
def test_impossible_fixture_accounting_is_refused(study, metric, value):
    document = copy.deepcopy(study)
    run = next(row["run"] for row in document["records"] if row["run"]["proposal_calls"])
    run[metric] = value
    with pytest.raises(AblationError):
        analyse_ablation(document)


def test_completed_study_with_configuration_failure_cannot_support_adoption(study):
    document = copy.deepcopy(study)
    document["error"] = {"type": "ConfigurationChanged", "message": "Changed during final trial"}
    with pytest.raises(AblationError):
        analyse_ablation(document)


def live_shaped_fixture(study):
    """Synthetic evidence for analyser tests; never emitted as a live benchmark."""
    document = copy.deepcopy(study)
    document["configuration"].update(
        provider="openai",
        model="mock-local",
        model_revision="test-revision",
        timeout_seconds=1,
        max_tokens=128,
    )
    document["configuration_sha256"] = digest(document["configuration"])
    document["warmup"] = {
        "status": "completed",
        "model_calls": 1,
        "reported_tokens": 0,
        "latency_ms": 1,
        "excluded_from_trial_metrics": True,
    }
    for row in document["records"]:
        row["configuration_sha256"] = document["configuration_sha256"]
        run = row["run"]
        run.update(provider="openai", model="mock-local", token_usage=0, latency_ms=1)
        injections = sum(event["name"] == "inject_provider_fault" for event in run["events"])
        run["model_calls"] = run["proposal_calls"] - injections
    return document


def test_completed_live_warmup_requires_accounting_not_just_status(study):
    document = live_shaped_fixture(study)
    document["warmup"] = {"status": "completed"}
    with pytest.raises(AblationError):
        analyse_ablation(document)


def test_unknown_live_token_coverage_does_not_pass_efficiency_rules(study):
    document = live_shaped_fixture(study)
    summary = analyse_ablation(document)
    assert summary["adoption"]["correctness_supported"]
    assert not summary["adoption"]["passes_declared_study_rules"]
    assert any("token" in flag.lower() for flag in summary["adoption"]["efficiency_flags"])


def test_failed_warmup_preserves_attempt_and_terminal_status(tmp_path, monkeypatch):
    class WarmupFailure(ScriptedProvider):
        is_live = True
        is_loopback = True
        timeout = 1
        max_tokens = 128

        def propose(self, *args, **kwargs):
            raise ProviderFailure("PRIVATE provider response")

    monkeypatch.setenv("AGENTPROOF_MODEL_REVISION", "test-revision")
    document = run_ablation(
        tmp_path / "warmup-failure", provider="openai", provider_factory=lambda _: WarmupFailure()
    )
    assert document["status"] == "failed"
    assert document["records"] == []
    assert document["warmup"]["model_calls"] == 1
    assert document["warmup"]["status"] == "failed"
    assert "PRIVATE" not in json.dumps(document)
    assert not analyse_ablation(document)["adoption"]["correctness_supported"]


def test_initial_model_request_is_identical_across_arms_without_oracle_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AGENTPROOF_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("AGENTPROOF_MODEL", "mock-local")
    monkeypatch.setenv("AGENTPROOF_DISABLE_THINKING", "true")
    requests_by_arm = {}
    case = BY_ID["eligible"]
    for budget in (1, 3):
        captured = []

        def respond(request, captured=captured):
            captured.append(json.loads(request.content))
            proposal = {
                "action": "refund",
                "order_id": case.order.id,
                "customer_id": case.authenticated_customer,
                "amount_cents": case.requested_cents * (2 if len(captured) == 1 else 1),
                "policy_version": case.current_policy,
                "reason": "Mock response",
            }
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(proposal)}}],
                    "usage": {"total_tokens": 37},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            provider = LiveProvider(client)
            run = Engine(
                Store(tmp_path / f"{budget}.sqlite"),
                lambda _, selected=provider: selected,
                options=EngineOptions(budget),
            ).run(case, provider="openai")
        finally:
            asyncio.run(client.aclose())
        requests_by_arm[budget] = captured
        assert run["model_calls"] == len(captured)
        assert run["token_usage"] == 37 * len(captured)
        assert run["passed"] is (budget == 3)
        for request in captured:
            text = json.dumps(request["messages"])
            for forbidden in ("expected_outcome", "max_proposals", '"A1"', '"A3"', '"fault"'):
                assert forbidden not in text
    assert requests_by_arm[1][0] == requests_by_arm[3][0]
    assert len(requests_by_arm[1]) == 1
    assert len(requests_by_arm[3]) == 2


def test_cli_valid_unfavorable_study_exits_zero_without_claiming_adoption(study, tmp_path):
    document = copy.deepcopy(study)
    row = next(
        row
        for row in document["records"]
        if row["arm"] == "A3" and row["scenario_id"] == "eligible"
    )
    row["run"].update(passed=False, safe=True, outcome="escalated", status="completed")
    row["run"]["final_state"] = {"effects": [], "total_refunded_cents": 0, "approval": None}
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(document))
    result = subprocess.run(
        [sys.executable, "scripts/ablate.py", "analyse", str(raw)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)
    assert printed["status"] == "completed"
    assert printed["adoption"]["correctness_supported"] is False
    assert (tmp_path / "summary.json").is_file()


def test_cli_sigterm_preserves_partial_checkpoint_and_returns_130(tmp_path):
    directory = tmp_path / "interrupted-study"
    marker = tmp_path / "in-proposal"
    driver = """
import sys, time
from pathlib import Path
import agentproof.ablation as module
from agentproof.providers import ScriptedProvider
from scripts.ablate import main
out, marker = sys.argv[1], sys.argv[2]
class SlowProvider(ScriptedProvider):
    def propose(self, *args, **kwargs):
        Path(marker).write_text("entered")
        time.sleep(15)
        return super().propose(*args, **kwargs)
module.provider_for = lambda _: SlowProvider()
sys.argv = ["ablate.py", "run", "--output-dir", out]
raise SystemExit(main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", driver, str(directory), str(marker)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not marker.exists() and process.poll() is None:
            time.sleep(0.02)
        assert marker.exists(), "Child did not reach its controlled proposal"
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 130, stderr
        printed = json.loads(stdout)
        assert printed["status"] == "interrupted"
        assert printed["adoption"]["correctness_supported"] is False
        saved = json.loads((directory / "raw.json").read_text())
        assert saved["status"] == "interrupted"
        assert saved["active_trial"] is not None
        assert len(saved["records"]) < 216
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)
