"""The UI comparison route uses the same strict checker as exported-report CLI."""

from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.scenarios import BY_ID


def create(client, **extra):
    response = client.post("/api/experiments", json={"scenario_ids": ["eligible"], **extra})
    assert response.status_code == 201
    return response.json()


def test_compare_existing_experiments_without_mutation(tmp_path):
    with TestClient(create_app(tmp_path / "compare.db")) as client:
        reference, candidate = create(client), create(client)
        response = client.post(
            "/api/comparisons",
            json={"reference_id": reference["id"], "candidate_id": candidate["id"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reference_id"] == reference["id"]
        assert data["candidate_id"] == candidate["id"]
        assert data["gate"]["passed"] is True
        assert data["variants"]["guarded"]["after"]["trials"] == 1
        assert client.get(f"/api/experiments/{candidate['id']}").json() == candidate
        assert len(client.get("/api/experiments").json()) == 2


def test_missing_and_unknown_fields_are_explicit(tmp_path):
    with TestClient(create_app(tmp_path / "compare.db")) as client:
        assert (
            client.post(
                "/api/comparisons", json={"reference_id": "missing", "candidate_id": "missing"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/comparisons",
                json={
                    "reference_id": "missing",
                    "candidate_id": "missing",
                    "ignore_failures": True,
                },
            ).status_code
            == 422
        )


def test_incompatible_suites_and_cancelled_exports_refuse_comparison(tmp_path):
    app = create_app(tmp_path / "compare.db")
    with TestClient(app) as client:
        reference = create(client)
        case = BY_ID["eligible"].model_dump()
        case["order"]["age_days"] = 14
        candidate = client.post("/api/experiments", json={"scenarios": [case]}).json()
        response = client.post(
            "/api/comparisons",
            json={"reference_id": reference["id"], "candidate_id": candidate["id"]},
        )
        assert response.status_code == 422
        assert "suites differ" in response.json()["detail"]
        saved = app.state.store.get_experiment(reference["id"])
        saved["status"] = "cancelled"
        app.state.store.save_experiment(saved)
        response = client.post(
            "/api/comparisons",
            json={"reference_id": reference["id"], "candidate_id": reference["id"]},
        )
        assert response.status_code == 422
        assert "completed" in response.json()["detail"]


def test_returned_evidence_is_the_graded_snapshot_when_approval_changes_afterward(
    tmp_path, monkeypatch
):
    from datetime import datetime

    import agentproof.api as api_module

    app = create_app(tmp_path / "compare.db")
    original_compare = api_module.compare_reports
    with TestClient(app) as client:
        reference = create(client, scenario_ids=["approval"])
        candidate = create(client, scenario_ids=["approval"])
        pending = next(run for run in candidate["runs"] if run["variant"] == "guarded")
        assert pending["status"] == "awaiting_approval"

        def approve_after_grading(reference_snapshot, candidate_snapshot):
            comparison = original_compare(reference_snapshot, candidate_snapshot)
            # Deterministically simulate another request committing approval after grading
            # and before serialization. Do not mutate the detached comparison inputs.
            app.state.engine.approve(pending["id"], True)
            return comparison

        monkeypatch.setattr(api_module, "compare_reports", approve_after_grading)
        response = client.post(
            "/api/comparisons",
            json={"reference_id": reference["id"], "candidate_id": candidate["id"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["gate"]["passed"] is True
        assert datetime.fromisoformat(data["captured_at"]).utcoffset().total_seconds() == 0
        assert data["reference_snapshot"] == reference
        assert data["candidate_snapshot"] == candidate
        captured = next(
            run for run in data["candidate_snapshot"]["runs"] if run["id"] == pending["id"]
        )
        assert captured["status"] == "awaiting_approval"
        assert captured["final_state"]["effects"] == []
        stored = client.get(f"/api/runs/{pending['id']}").json()
        assert stored["status"] == "completed"
        assert stored["approval_decision"] is True
        assert len(stored["final_state"]["effects"]) == 1
        rechecked = original_compare(data["reference_snapshot"], data["candidate_snapshot"])
        assert all(data[key] == value for key, value in rechecked.items())
