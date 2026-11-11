"""Independent archive boundaries; no model calls or live study mutation."""

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agentproof.evidence as evidence_module
from agentproof.api import create_app
from agentproof.evidence import CATALOG, MAX_ARCHIVE_BYTES, EvidenceError, EvidenceLibrary

ROOT = Path(__file__).resolve().parents[1]
ENTRY = next(entry for entry in CATALOG if entry.id == "original-v01")


def fixture_library(tmp_path, raw):
    """Repin only a temporary catalog to exercise validation beyond integrity."""
    entry = replace(ENTRY, sha256=hashlib.sha256(raw).hexdigest())
    (tmp_path / entry.filename).write_bytes(raw)
    return EvidenceLibrary(tmp_path, [entry]), entry


@pytest.mark.parametrize("location", ["trace", "metadata", "extra"])
def test_overflow_json_number_rejected_even_inside_untyped_fields(tmp_path, monkeypatch, location):
    document = json.loads((ROOT / "reports" / ENTRY.filename).read_bytes())
    if location == "trace":
        document["runs"][0]["events"][0]["detail"]["review_number"] = "OVERFLOW_SENTINEL"
    elif location == "metadata":
        document["server_metadata"]["review_number"] = "OVERFLOW_SENTINEL"
    else:
        document["review_extra"] = {"nested": ["OVERFLOW_SENTINEL"]}
    raw = json.dumps(document).encode().replace(b'"OVERFLOW_SENTINEL"', b"1e400")
    assert b"1e400" in raw and b"Infinity" not in raw and b"NaN" not in raw
    library, entry = fixture_library(tmp_path, raw)
    with pytest.raises(EvidenceError):
        library.load(entry.id)
    monkeypatch.setattr(evidence_module, "CATALOG", (entry,))
    with TestClient(create_app(tmp_path / "workspace.sqlite3", evidence_root=tmp_path)) as client:
        catalog = client.get("/api/evidence")
        assert catalog.status_code == 200
        assert catalog.json()[0]["available"] is False
        assert client.get(f"/api/evidence/{entry.id}").status_code == 422
        assert client.get(f"/api/evidence/{entry.id}/download").status_code == 422


def test_size_limit_accepts_exact_boundary_and_download_keeps_all_whitespace(tmp_path, monkeypatch):
    original = (ROOT / "reports" / ENTRY.filename).read_bytes()
    assert len(original) < MAX_ARCHIVE_BYTES
    raw = original + b" " * (MAX_ARCHIVE_BYTES - len(original))
    library, entry = fixture_library(tmp_path, raw)
    assert library.load(entry.id)[0] == raw
    monkeypatch.setattr(evidence_module, "CATALOG", (entry,))
    with TestClient(create_app(tmp_path / "workspace.sqlite3", evidence_root=tmp_path)) as client:
        response = client.get(f"/api/evidence/{entry.id}/download")
        assert response.status_code == 200
        assert response.content == raw
        assert len(response.content) == MAX_ARCHIVE_BYTES
        assert response.headers["content-type"] == "application/json"
        assert response.headers["etag"] == f'"{entry.sha256}"'
        assert response.headers["cache-control"] == "no-store"


def test_duplicate_key_inside_trace_is_not_silently_last_value_wins(tmp_path):
    document = json.loads((ROOT / "reports" / ENTRY.filename).read_bytes())
    document["runs"][0]["events"][0]["detail"]["review_nested"] = "DUPLICATE_SENTINEL"
    raw = json.dumps(document).encode().replace(
        b'"DUPLICATE_SENTINEL"', b'{"approved":false,"approved":true}',
    )
    library, entry = fixture_library(tmp_path, raw)
    with pytest.raises(EvidenceError, match="duplicate"):
        library.load(entry.id)


def test_archive_id_collision_never_reads_or_writes_workspace_run(tmp_path, monkeypatch):
    raw, archived = EvidenceLibrary().load(ENTRY.id)
    snapshot = archived["experiment"]
    pending = next(run for run in snapshot["runs"] if run["status"] == "awaiting_approval")
    scenario = next(case for case in snapshot["scenarios"] if case["id"] == pending["scenario_id"])
    workspace_run = copy.deepcopy(pending)
    workspace_run.update(scenario_name="Mutable workspace counterpart", status="completed")
    workspace_run["final_state"]["review_marker"] = "workspace only"

    def forbidden(*args, **kwargs):
        raise AssertionError("Archive routes must not access workspace runs or provider adapters")

    app = create_app(tmp_path / "workspace.sqlite3", provider_factory=forbidden)
    app.state.store.save_run(workspace_run, scenario)
    original_get = app.state.store.get_run
    with TestClient(app) as client:
        assert client.get(f"/api/runs/{pending['id']}").json()["scenario_name"] == "Mutable workspace counterpart"
        monkeypatch.setattr(app.state.store, "get_run", forbidden)
        monkeypatch.setattr(app.state.store, "save_run", forbidden)
        response = client.get(f"/api/evidence/{ENTRY.id}")
        assert response.status_code == 200
        archived_run = next(run for run in response.json()["experiment"]["runs"] if run["id"] == pending["id"])
        assert archived_run["status"] == "awaiting_approval"
        assert archived_run["scenario_name"] == pending["scenario_name"]
        assert archived_run["final_state"]["effects"] == []
        assert "review_marker" not in archived_run["final_state"]
        assert client.get(f"/api/evidence/{ENTRY.id}/download").content == raw
        assert original_get(pending["id"]) == workspace_run


def test_shipped_catalog_files_are_explicitly_present_in_docker_context():
    docker = (ROOT / "Dockerfile").read_text()
    report_copy = next(line for line in docker.splitlines() if line.startswith("COPY reports/"))
    paths = report_copy.split()[1:-1]
    assert {str(Path("reports") / entry.filename) for entry in CATALOG} <= set(paths)
    assert all((ROOT / path).is_file() for path in paths)
