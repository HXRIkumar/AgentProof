"""Historical reports stay out of the live journal and keep byte-level provenance."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.evidence import CATALOG, MAX_ARCHIVE_BYTES, EvidenceError, EvidenceLibrary

ROOT = Path(__file__).resolve().parents[1] / "reports"


def repinned_library(tmp_path, mutation=None, *, raw=None):
    """Trust a test catalog hash deliberately to exercise checks beyond file integrity."""
    if raw is None:
        document = json.loads((ROOT / CATALOG[0].filename).read_text())
        if mutation:
            mutation(document)
        raw = json.dumps(document).encode()
    entry = replace(CATALOG[0], sha256=hashlib.sha256(raw).hexdigest())
    (tmp_path / entry.filename).write_bytes(raw)
    return EvidenceLibrary(tmp_path, [entry]), entry


def test_all_shipped_archives_validate_and_download_exact_bytes_without_models_or_store_writes(
    tmp_path,
):
    def no_provider(_name):
        raise AssertionError("Archive browsing must never construct a provider")

    app = create_app(tmp_path / "empty.db", provider_factory=no_provider)
    with TestClient(app) as client:
        assert client.get("/api/experiments").json() == []
        listing = client.get("/api/evidence")
        assert listing.status_code == 200
        assert len(listing.json()) == 5
        assert all(item["available"] and item["read_only"] for item in listing.json())
        for item in listing.json():
            response = client.get("/api/evidence/" + item["id"])
            assert response.status_code == 200
            envelope = response.json()
            assert envelope["archive"]["sha256"] == item["sha256"]
            assert envelope["archive"]["provider"] == "openai"
            report = envelope["experiment"]
            assert report["summary"]["total_runs"] == item["trial_count"]
            assert report["status"] == "completed"
            download = client.get(envelope["archive"]["download_url"])
            assert download.status_code == 200
            assert hashlib.sha256(download.content).hexdigest() == item["sha256"]
            entry = next(entry for entry in CATALOG if entry.id == item["id"])
            assert download.content == (ROOT / entry.filename).read_bytes()
            assert download.headers["etag"] == '"' + item["sha256"] + '"'
            # The archived run ID is never imported into the live store.
            assert client.get("/api/runs/" + report["runs"][0]["id"]).status_code == 404
        assert client.get("/api/experiments").json() == []
        with app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0


def test_archive_routes_offer_no_mutation_or_arbitrary_path_access(tmp_path):
    with TestClient(create_app(tmp_path / "empty.db")) as client:
        for method in (client.post, client.put, client.delete):
            assert method("/api/evidence/challenge-v02").status_code == 405
            assert method("/api/evidence/challenge-v02/download").status_code == 405
        assert client.get("/api/evidence/not-a-catalog-id").status_code == 404
        assert client.get("/api/evidence/..%2F.env").status_code == 404
        assert client.post(
            "/api/evidence/challenge-v02/approve", json={"approved": True}
        ).status_code in (404, 405)


def test_missing_or_tampered_archives_fail_closed_without_breaking_workspace(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    target = root / CATALOG[0].filename
    target.write_bytes((ROOT / CATALOG[0].filename).read_bytes())
    with TestClient(create_app(tmp_path / "empty.db", evidence_root=root)) as client:
        listing = client.get("/api/evidence").json()
        assert listing[0]["available"]
        assert all(not item["available"] for item in listing[1:])
        target.write_bytes(target.read_bytes() + b" ")
        assert client.get("/api/evidence/challenge-v02").status_code == 422
        assert client.get("/api/evidence/challenge-v02/download").status_code == 422
        assert not client.get("/api/evidence").json()[0]["available"]
        assert client.get("/api/ready").status_code == 200
        assert (
            client.post("/api/experiments", json={"scenario_ids": ["eligible"]}).status_code == 201
        )


def test_oversized_file_rejected_before_parsing(tmp_path):
    library, entry = repinned_library(tmp_path, raw=b" " * (MAX_ARCHIVE_BYTES + 1))
    with pytest.raises(EvidenceError, match="file size"):
        library.load(entry.id)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["runs"][0]["events"][0].update(duration_ms=True),
        lambda d: d["runs"][0]["events"][0].update(duration_ms=-1),
        lambda d: d["runs"][0].update(events={}),
        lambda d: d["runs"][0].update(model_calls=True),
        lambda d: d["runs"][0].update(token_usage=3.5),
        lambda d: d["runs"][0].update(latency_ms=float("nan")),
        lambda d: d["runs"][0]["checks"][0].update(passed="true"),
        lambda d: d["runs"].pop(),
        lambda d: d["runs"][0].update(scenario_name="a false scenario name"),
        lambda d: d["runs"][0]["final_state"].update(total_refunded_cents=True),
        lambda d: d["configuration"].update(model_revision=123),
        lambda d: d["configuration"].update(max_proposals=True),
        lambda d: d.update(created_at="not a date"),
        lambda d: d.update(created_at="2026-11-12T00:00:00"),
        lambda d: d.update(status="failed"),
        lambda d: d.update(error="interrupted"),
    ],
)
def test_repinned_malformed_exports_still_fail_schema_or_semantic_validation(tmp_path, mutation):
    library, entry = repinned_library(tmp_path, mutation)
    with pytest.raises(EvidenceError):
        library.load(entry.id)


def test_duplicate_json_keys_are_rejected(tmp_path):
    library, entry = repinned_library(tmp_path, raw=b'{"id":"first","id":"second"}')
    with pytest.raises(EvidenceError, match="duplicate"):
        library.load(entry.id)


def test_summary_is_recomputed_and_raw_download_is_unchanged(tmp_path, monkeypatch):
    import agentproof.evidence as evidence_module

    library, entry = repinned_library(
        tmp_path, lambda d: d.update(summary={"guarded": {"passed": 999999}})
    )
    monkeypatch.setattr(evidence_module, "CATALOG", (entry,))
    with TestClient(create_app(tmp_path / "empty.db", evidence_root=tmp_path)) as client:
        view = client.get("/api/evidence/" + entry.id).json()
        assert view["experiment"]["summary"]["guarded"]["passed"] == 54
        downloaded = client.get(view["archive"]["download_url"])
        assert downloaded.json()["summary"]["guarded"]["passed"] == 999999
        assert hashlib.sha256(downloaded.content).hexdigest() == entry.sha256
        assert library.load(entry.id)[0] == downloaded.content


def test_view_returns_detached_data_and_keeps_pending_decision_historical():
    library = EvidenceLibrary()
    original, first = library.load("original-v01")
    pending = next(
        run for run in first["experiment"]["runs"] if run["status"] == "awaiting_approval"
    )
    assert pending["final_state"]["effects"] == []
    pending["outcome"] = "tampered-in-memory"
    raw, second = library.load("original-v01")
    assert raw == original
    assert not any(run["outcome"] == "tampered-in-memory" for run in second["experiment"]["runs"])
