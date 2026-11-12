"""The answer runtime is reachable in the real app and exports cannot invent completion."""

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentproof.answers import AnswerService, OpenAIAdapter
from agentproof.api import create_app

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_answer_routes_exist_in_main_application_and_reject_gold(tmp_path):
    service = AnswerService(tmp_path / "answers.sqlite3", OpenAIAdapter(base_url="", model=""))
    with TestClient(create_app(tmp_path / "legacy.sqlite3", answer_service=service)) as client:
        assert client.get("/api/answers/config").json()["configured"] is False
        assert client.get("/api/answers/runs").json() == []
        request = {
            "question": "When?",
            "sources": [{"id": "a", "text": "Released in 2024."}],
            "gold": {"answer": "2024"},
        }
        assert client.post("/api/answers/run", json=request).status_code == 422
        del request["gold"]
        result = client.post("/api/answers/run", json=request).json()
        assert result["status"] == "error"
        assert result["usage"]["calls"] == 0
        assert client.get("/api/answers/runs/" + result["id"]).json() == result
        assert client.get("/api/scenarios").status_code == 200


def test_empty_static_catalog_is_honest_and_output_not_overwritten(tmp_path):
    build = load_script("build_answer_evidence").build_answer_evidence
    result = build(tmp_path / "absent", tmp_path / "public")
    assert result["reports"] == {}
    assert json.loads((tmp_path / "public/catalog.json").read_text()) == []
    with pytest.raises(ValueError, match="empty"):
        build(tmp_path / "absent", tmp_path / "public")


def test_static_catalog_rejects_symlinked_evidence(tmp_path):
    build = load_script("build_answer_evidence").build_answer_evidence
    source = tmp_path / "reports"
    source.mkdir()
    (tmp_path / "private.json").write_text("{}")
    (source / "indirect.json").symlink_to(tmp_path / "private.json")
    with pytest.raises(ValueError, match="Invalid evidence"):
        build(source, tmp_path / "public")


def test_cache_probe_does_not_grade_failed_empty_answer_as_correct_abstention():
    probe = load_script("answer_cache_probe")

    class FailedService:
        def run(self, request):
            return {"status": "failed", "abstained": False, "answer": ""}

    row = probe.execute(FailedService(), None, [""])
    assert row["correct"] is False
    assert row["exact_match"] == 0
