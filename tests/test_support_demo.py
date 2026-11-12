"""Static publishing preserves recordings and never fills absent model outputs."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("support_builder", ROOT / "scripts/build_support_demo.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_recording():
    # Deliberate unit fixture only: never written to reports/ or published.
    return {
        "format": "agentproof-support-demo-v1",
        "config": {"configured": True},
        "documents": [{"id": "doc1", "filename": "manual.md", "version": 1, "text": "Manual."}],
        "tickets": [
            {"id": "ticket1", "events": [], "result": {
                "answer_run": {"id": "run1", "attempts": [{"generation": {"text": "fixture"}}]}
            }},
            {"id": "ticket2", "status": "failed", "events": [], "result": None},
        ],
    }


def test_exact_bytes_manifest_and_failed_ticket_are_preserved(tmp_path):
    source, output = tmp_path / "recorded.json", tmp_path / "support"
    raw = (json.dumps(fixture_recording(), indent=3) + "\n\n").encode()
    source.write_bytes(raw)
    manifest = module.build_support_demo(source, output)
    assert (output / "demo.json").read_bytes() == raw
    assert manifest["files"]["demo.json"] == hashlib.sha256(raw).hexdigest()
    assert manifest["ticket_count"] == 2 and manifest["recorded_answer_runs"] == 1
    assert manifest["models_executed_by_site"] is False
    with pytest.raises(ValueError, match="must be empty"):
        module.build_support_demo(source, output)
    assert (output / "demo.json").read_bytes() == raw


def test_missing_recording_fails_without_creating_placeholder(tmp_path):
    output = tmp_path / "support"
    with pytest.raises(ValueError, match="missing"):
        module.build_support_demo(tmp_path / "absent.json", output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["no_trace", "credential", "duplicate_id", "bad_attempt"])
def test_incomplete_or_private_recording_cannot_publish(tmp_path, mutation):
    data = fixture_recording()
    if mutation == "no_trace":
        data["tickets"][0]["result"] = None
    elif mutation == "credential":
        data["config"]["provider"] = {"api_key": "unit-test-placeholder"}
    elif mutation == "duplicate_id":
        data["tickets"][1]["id"] = "ticket1"
    else:
        data["tickets"][0]["result"]["answer_run"]["attempts"] = [None]
    source, output = tmp_path / "recording.json", tmp_path / "support"
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        module.build_support_demo(source, output)
    assert not output.exists()


def test_duplicate_json_keys_are_rejected(tmp_path):
    source = tmp_path / "recording.json"
    source.write_text('{"format":"agentproof-support-demo-v1","format":"other"}')
    with pytest.raises(ValueError, match="Duplicate JSON keys"):
        module.build_support_demo(source, tmp_path / "support")
