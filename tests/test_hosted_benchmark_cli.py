"""Hosted invocation must be explicit and remain separate from free local runs."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("hosted_study", SCRIPTS / "answer_hosted_benchmark.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hybrid_routes_only_critic(hosted):
    configuration = hosted.route_environment("hybrid", {
        "ANSWER_LAB_BASE_URL": "http://127.0.0.1:8089/v1",
        "ANSWER_LAB_MODEL": "local-model", "OPENAI_API_KEY": "DO-NOT-COPY",
    })
    assert "ANSWER_LAB_BASE_URL" not in configuration
    assert configuration["ANSWER_LAB_CRITIC_BASE_URL"] == hosted.ENDPOINT
    assert "DO-NOT-COPY" not in repr(configuration)
    assert configuration["ANSWER_LAB_CRITIC_MAX_TOKENS"] == "1536"


@pytest.mark.parametrize("endpoint", ["https://example.com/v1", "", "http://user@localhost/v1"])
def test_hybrid_rejects_external_or_credential_endpoint(hosted, endpoint):
    with pytest.raises(ValueError, match="local generator"):
        hosted.route_environment("hybrid", {"ANSWER_LAB_BASE_URL": endpoint, "ANSWER_LAB_MODEL": "local"})


def test_hosted_pins_efficient_model(hosted):
    configuration = hosted.route_environment("hosted", {})
    assert configuration["ANSWER_LAB_MODEL"] == "gpt-5.4-mini-2026-03-17"
    assert configuration["ANSWER_LAB_BASE_URL"] == "https://api.openai.com/v1"
    assert configuration["ANSWER_LAB_OPENAI_REASONING_EFFORT"] == "low"


def test_explicit_paid_optin_required(hosted, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["hosted", "--mode", "hosted", "--suite", "unused.json",
                                    "--output-dir", str(tmp_path / "unused")])
    monkeypatch.setattr(hosted, "AnswerService", lambda *_: pytest.fail("Must not construct provider"))
    with pytest.raises(SystemExit):
        hosted.main()
    assert "--allow-paid is required" in capsys.readouterr().err
    assert not (tmp_path / "unused").exists()


def test_local_runner_rejects_paid_critic(tmp_path):
    env = os.environ.copy()
    env.update(ANSWER_LAB_BASE_URL="http://127.0.0.1:8089/v1",
               ANSWER_LAB_CRITIC_BASE_URL="https://api.openai.com/v1",
               ANSWER_LAB_ENABLE_PAID="1")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "answer_benchmark.py"), "run", "--suite", "unused.json",
         "--output-dir", str(tmp_path / "unused")], env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "only local inference" in result.stderr
    assert not (tmp_path / "unused").exists()


def test_budget_audit_survives_study_failure(hosted, monkeypatch, tmp_path):
    def fail_study(*_args, **_kwargs):
        raise RuntimeError("Controlled test interruption")

    monkeypatch.setattr(hosted, "run_benchmark", fail_study)
    args = SimpleNamespace(mode="hybrid", suite=tmp_path / "unused.json",
                           output_dir=tmp_path / "study", limit=None, max_attempts=3)
    service = SimpleNamespace(adapter=SimpleNamespace(budget_status=lambda: {"spent": 0.01}))
    with pytest.raises(RuntimeError, match="Controlled test interruption"):
        hosted.run_study(args, service, {"spent": 0})
    audit = json.loads((tmp_path / "study.budget.json").read_text())
    assert audit["budget_before"] == {"spent": 0}
    assert audit["budget_after"] == {"spent": 0.01}


def test_prior_budget_audit_is_preserved(hosted, monkeypatch, tmp_path, capsys):
    audit = tmp_path / "study.budget.json"
    audit.write_text("retained audit")
    monkeypatch.setattr(sys, "argv", ["hosted", "--allow-paid", "--mode", "hosted",
                                    "--suite", "unused.json", "--output-dir", str(tmp_path / "study")])
    monkeypatch.setattr(hosted, "AnswerService", lambda *_: pytest.fail("Must not construct provider"))
    with pytest.raises(SystemExit):
        hosted.main()
    assert "Budget audit already exists" in capsys.readouterr().err
    assert audit.read_text() == "retained audit"
