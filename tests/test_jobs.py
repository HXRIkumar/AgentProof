"""Observable queue, cancellation and restart guarantees (no paid model calls)."""

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agentproof.api import create_app
from agentproof.engine import Engine
from agentproof.jobs import ExperimentWorker
from agentproof.models import ExperimentRequest
from agentproof.providers import ScriptedProvider
from agentproof.scenarios import BY_ID


class BlockingProvider(ScriptedProvider):
    """Hold only the first proposal so request/worker races can be driven explicitly."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def propose(self, *args, **kwargs):
        with self.lock:
            self.calls += 1
            first = self.calls == 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if first:
                self.entered.set()
                if not self.release.wait(5):
                    raise RuntimeError("Test did not release provider")
            return super().propose(*args, **kwargs)
        finally:
            with self.lock:
                self.active -= 1


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Condition did not become true")


def terminal(client, experiment_id):
    def finished():
        response = client.get(f"/api/experiments/{experiment_id}")
        assert response.status_code == 200
        data = response.json()
        return data if data["status"] not in ("queued", "running") else None

    return until(finished)


def submit(client, **extra):
    response = client.post(
        "/api/experiments?background=true",
        json={"scenario_ids": ["eligible"], **extra},
    )
    assert response.status_code == 202, response.text
    return response.json()


def prepare(app, **extra):
    return app.state.prepare_experiment(ExperimentRequest(scenario_ids=["eligible"], **extra), True)


def test_async_accepts_before_trial_finishes_and_reports_progress(tmp_path):
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    with TestClient(app) as client:
        try:
            data = submit(client, repeats=2)
            assert provider.entered.wait(2)
            running = client.get(f"/api/experiments/{data['id']}").json()
            assert running["status"] == "running"
            assert running["summary"]["total_runs"] == 0
            assert running["summary"]["expected_runs"] == 4
            assert running["summary"]["gate"]["passed"] is False
            assert client.get("/api/config").json()["background_available"]
        finally:
            provider.release.set()
        finished = terminal(client, data["id"])
        assert finished["status"] == "completed"
        assert len(finished["runs"]) == 4
        assert finished["summary"]["gate"]["passed"]


def test_sync_requests_share_durable_serial_execution_with_background(tmp_path):
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        try:
            first = submit(client)
            assert provider.entered.wait(2)
            sync = pool.submit(client.post, "/api/experiments", json={"scenario_ids": ["eligible"]})
            until(lambda: len(client.get("/api/experiments").json()) == 2)
            assert not sync.done()
            records = client.get("/api/experiments").json()
            assert sorted(item["status"] for item in records) == ["queued", "running"]
        finally:
            provider.release.set()
        response = sync.result(timeout=5)
        assert response.status_code == 201
        assert response.json()["status"] == "completed"
        assert terminal(client, first["id"])["status"] == "completed"
        assert provider.peak == 1
        assert provider.calls == 4


def test_queue_limit_is_atomic_and_cancelled_waiting_job_frees_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTPROOF_MAX_QUEUED", "1")
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    with TestClient(app) as client:
        try:
            first = submit(client)
            assert provider.entered.wait(2)
            waiting = submit(client)
            assert waiting["status"] == "queued"
            overflow = client.post(
                "/api/experiments?background=true", json={"scenario_ids": ["eligible"]}
            )
            assert overflow.status_code == 429
            assert len(client.get("/api/experiments").json()) == 2
            cancelled = client.post(f"/api/experiments/{waiting['id']}/cancel").json()
            assert cancelled["status"] == "cancelled"
            assert cancelled["runs"] == []
            replacement = submit(client)
        finally:
            provider.release.set()
        assert terminal(client, first["id"])["status"] == "completed"
        assert terminal(client, replacement["id"])["status"] == "completed"
        assert provider.calls == 4  # The cancelled queued job never called the model.


def test_running_cancel_finishes_current_trial_and_preserves_effect(tmp_path):
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    with TestClient(app) as client:
        try:
            data = submit(client, repeats=2)
            assert provider.entered.wait(2)
            response = client.post(f"/api/experiments/{data['id']}/cancel")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert response.json()["cancel_requested"] is True
        finally:
            provider.release.set()
        finished = terminal(client, data["id"])
        assert finished["status"] == "cancelled"
        assert len(finished["runs"]) == provider.calls == 1
        run = finished["runs"][0]
        assert len(app.state.store.effects(run["id"])) == 1
        assert finished["summary"]["gate"]["passed"] is False
        again = client.post(f"/api/experiments/{data['id']}/cancel").json()
        assert again == finished
        exported = client.get(f"/api/experiments/{data['id']}/export").json()
        assert exported == finished


def test_cancel_unknown_returns_404_and_completed_is_unchanged(tmp_path):
    with TestClient(create_app(tmp_path / "jobs.db")) as client:
        assert client.post("/api/experiments/missing/cancel").status_code == 404
        completed = client.post("/api/experiments", json={"scenario_ids": ["eligible"]}).json()
        assert client.post(f"/api/experiments/{completed['id']}/cancel").json() == completed


def test_queued_job_survives_server_restart_and_runs_exactly_once(tmp_path):
    path = tmp_path / "jobs.db"
    original = create_app(path)
    queued = prepare(original)
    original.state.store.enqueue_experiment(queued, 8)
    with TestClient(create_app(path)) as client:
        result = terminal(client, queued["id"])
        assert result["status"] == "completed"
        assert len(result["runs"]) == 2
    with TestClient(create_app(path)) as client:
        assert client.get(f"/api/experiments/{queued['id']}").json() == result


def test_interrupted_job_is_failed_without_replaying_completed_effects(tmp_path):
    path = tmp_path / "jobs.db"
    previous = create_app(path)
    store = previous.state.store
    interrupted = prepare(previous)
    store.enqueue_experiment(interrupted, 8)
    assert store.claim_experiment()["id"] == interrupted["id"]
    run = Engine(store).run(BY_ID["eligible"], "baseline")
    store.record_experiment_run(interrupted["id"], run["id"])
    queued = prepare(previous)
    store.enqueue_experiment(queued, 8)
    with TestClient(create_app(path)) as client:
        failed = client.get(f"/api/experiments/{interrupted['id']}").json()
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "InterruptedExecution"
        assert [item["id"] for item in failed["runs"]] == [run["id"]]
        assert len(store.effects(run["id"])) == 1
        assert not failed["summary"]["gate"]["passed"]
        assert terminal(client, queued["id"])["status"] == "completed"


def test_interrupted_legacy_sync_experiment_is_also_recovered(tmp_path):
    path = tmp_path / "jobs.db"
    previous = create_app(path)
    legacy = prepare(previous)
    legacy["status"] = "running"
    legacy.pop("background")
    previous.state.store.save_experiment(legacy)  # No experiment_jobs row in v0.1.
    with TestClient(create_app(path)) as client:
        data = client.get(f"/api/experiments/{legacy['id']}").json()
        assert data["status"] == "failed"
        assert data["error"]["type"] == "InterruptedExecution"


@pytest.mark.parametrize("changed", ["model_revision", "prompt_hash", "backend_source"])
def test_changed_queued_configuration_fails_without_model_calls(tmp_path, monkeypatch, changed):
    provider = BlockingProvider()
    path = tmp_path / "jobs.db"
    app = create_app(path, lambda _: provider)
    queued = prepare(app)
    if changed == "model_revision":
        monkeypatch.setenv("AGENTPROOF_MODEL_REVISION", "new-model-weights")
    elif changed == "prompt_hash":
        queued["prompt_hash"] = "previous-prompt"
    else:
        queued["server_metadata"]["backend_source_sha256"] = "previous-source"
    # Persist a deep snapshot; later app construction must not mutate it.
    before = json.loads(json.dumps(queued["configuration"]))
    app.state.store.enqueue_experiment(queued, 8)
    with TestClient(app) as client:
        failed = terminal(client, queued["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "ConfigurationChanged"
        assert failed["configuration"] == before
        assert failed["runs"] == []
        assert provider.calls == 0


def test_mid_experiment_configuration_change_preserves_only_consistent_trials(
    tmp_path, monkeypatch
):
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    with TestClient(app) as client:
        try:
            job = submit(client)
            assert provider.entered.wait(2)
            monkeypatch.setenv("AGENTPROOF_MODEL_REVISION", "changed-mid-experiment")
        finally:
            provider.release.set()
        failed = terminal(client, job["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "ConfigurationChanged"
        assert len(failed["runs"]) == 1
        assert provider.calls == 1
        assert failed["summary"]["gate"]["passed"] is False


def test_second_process_cannot_start_worker_for_same_database(tmp_path):
    path = tmp_path / "jobs.db"
    with TestClient(create_app(path)) as client:
        alias = tmp_path / "alias.db"
        alias.symlink_to(path)
        script = (
            "import sys; from fastapi.testclient import TestClient; "
            "from agentproof.api import create_app; "
            "client=TestClient(create_app(sys.argv[1])); client.__enter__()"
        )
        second = subprocess.run(
            [sys.executable, "-c", script, str(alias)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert second.returncode != 0
        assert "already owns this database" in second.stderr
        assert client.get("/api/config").json()["background_available"]
        assert (
            client.post("/api/experiments", json={"scenario_ids": ["eligible"]}).status_code == 201
        )


def test_worker_exception_is_redacted_and_next_queued_job_still_runs(tmp_path):
    app = create_app(tmp_path / "jobs.db")
    first, second = prepare(app), prepare(app)
    for job in (first, second):
        app.state.store.enqueue_experiment(job, 8)

    def execute(job, stop_event):
        if job["id"] == first["id"]:
            raise RuntimeError("SECRET-provider-token")
        app.state.store.finish_experiment(job["id"], "completed")

    worker = ExperimentWorker(app.state.store, execute)
    worker.start()
    try:
        until(lambda: app.state.store.get_experiment(second["id"])["status"] == "completed")
        failed = app.state.store.get_experiment(first["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "RuntimeError"
        assert "SECRET" not in json.dumps(failed)
        assert worker.available
    finally:
        worker.stop()


def test_shutdown_preserves_current_trial_and_leaves_queued_job_for_restart(tmp_path):
    provider = BlockingProvider()
    path = tmp_path / "jobs.db"
    app = create_app(path, lambda _: provider)
    with TestClient(app) as client:
        first = submit(client, repeats=2)
        assert provider.entered.wait(2)
        queued = submit(client)
        with ThreadPoolExecutor(max_workers=1) as pool:
            shutdown = pool.submit(app.state.worker.stop)
            try:
                until(app.state.worker.stop_event.is_set)
                assert not shutdown.done()
            finally:
                provider.release.set()
            shutdown.result(timeout=5)
        failed = client.get(f"/api/experiments/{first['id']}").json()
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "ServerShutdown"
        assert len(failed["runs"]) == 1
        assert client.get(f"/api/experiments/{queued['id']}").json()["status"] == "queued"
    with TestClient(create_app(path, lambda _: provider)) as client:
        assert terminal(client, queued["id"])["status"] == "completed"
        assert len(client.get(f"/api/experiments/{first['id']}").json()["runs"]) == 1


def test_worker_required_when_lifespan_is_disabled(tmp_path):
    client = TestClient(create_app(tmp_path / "jobs.db"))
    for suffix in ("", "?background=true"):
        response = client.post(f"/api/experiments{suffix}", json={"scenario_ids": ["eligible"]})
        assert response.status_code == 503
    assert client.get("/api/experiments").json() == []


def test_concurrent_submissions_cannot_exceed_queue_bound(tmp_path):
    app = create_app(tmp_path / "jobs.db")
    jobs = [prepare(app) for _ in range(12)]

    def enqueue(job):
        try:
            app.state.store.enqueue_experiment(job, 3)
            return True
        except OverflowError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(enqueue, jobs))
    assert sum(accepted) == 3
    assert len(app.state.store.experiments()) == 3


def test_replay_does_not_overlap_running_experiment(tmp_path):
    provider = BlockingProvider()
    app = create_app(tmp_path / "jobs.db", lambda _: provider)
    replayable = Engine(app.state.store).run(BY_ID["eligible"], "guarded")
    with TestClient(app) as client:
        try:
            job = submit(client)
            assert provider.entered.wait(2)
            assert client.post(f"/api/runs/{replayable['id']}/replay").status_code == 409
        finally:
            provider.release.set()
        terminal(client, job["id"])
        assert client.post(f"/api/runs/{replayable['id']}/replay").status_code == 201


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "different-model"),
        ("timeout", 11),
        ("max_tokens", 256),
        ("disable_thinking", True),
        ("base_url", "http://127.0.0.1:9999/v1"),
    ],
)
def test_effective_provider_settings_are_pinned_at_submission(tmp_path, field, value):
    settings = {
        "model": "initial-model",
        "timeout": 20,
        "max_tokens": 512,
        "disable_thinking": False,
        "base_url": "http://127.0.0.1:8089/v1",
    }

    def factory(_):
        adapter = ScriptedProvider()
        for key, setting in settings.items():
            setattr(adapter, key, setting)
        return adapter

    app = create_app(tmp_path / "jobs.db", factory)
    queued = prepare(app)
    original = json.loads(json.dumps(queued["configuration"]))
    app.state.store.enqueue_experiment(queued, 8)
    settings[field] = value
    with TestClient(app) as client:
        failed = terminal(client, queued["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "ConfigurationChanged"
        assert failed["configuration"] == original
        assert failed["runs"] == []
        assert "http://127.0.0.1" not in json.dumps(failed["configuration"])


def test_worker_claim_failure_is_visible_and_releases_lease(tmp_path, monkeypatch, caplog):
    app = create_app(tmp_path / "jobs.db")

    def broken_claim():
        raise RuntimeError("SECRET database credential")

    monkeypatch.setattr(app.state.store, "claim_experiment", broken_claim)
    worker = ExperimentWorker(app.state.store, lambda *_: None)
    worker.start()
    until(lambda: not worker.available)
    worker.stop()
    assert "Experiment worker stopped: RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text
    # A new process/app can recover after the failed worker relinquishes ownership.
    with TestClient(create_app(tmp_path / "jobs.db")) as restarted:
        assert restarted.get("/api/config").json()["background_available"] is True
