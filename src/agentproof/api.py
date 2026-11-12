import asyncio
import hashlib
import json
import os
import platform
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .answers import AnswerService
from .answers import create_router as create_answer_router
from .comparison import ComparisonError, compare_reports
from .engine import ApprovalConflict, Engine, now
from .evidence import EvidenceError, EvidenceLibrary
from .jobs import ExperimentWorker
from .middleware import RequestBodyLimitMiddleware
from .models import ApprovalRequest, ComparisonRequest, ExperimentRequest, Scenario
from .providers import PROMPT_HASH, LiveProvider, provider_for
from .scenarios import SCENARIOS, SUITE_HASH, SUITE_VERSION, public_scenario
from .store import Store
from .summary import summarize
from .support import SupportService
from .support import create_router as create_support_router


def runtime_configuration(adapter) -> dict:
    """Effective, non-secret provider settings used to reject changed queued configurations."""
    return {
        "model": adapter.model,
        "timeout_seconds": getattr(adapter, "timeout", None),
        "max_tokens": getattr(adapter, "max_tokens", None),
        "disable_thinking": getattr(adapter, "disable_thinking", False),
        "model_revision": os.getenv("AGENTPROOF_MODEL_REVISION", "unrecorded"),
        "base_url_sha256": hashlib.sha256(getattr(adapter, "base_url", "").encode()).hexdigest(),
    }


def create_app(
    db_path: str | Path | None = None, provider_factory=None, *, evidence_root: Path | None = None,
    answer_service=None, support_service=None,
) -> FastAPI:
    # Snapshot at app construction, not request time; no hostnames, usernames or absolute paths.
    source_hash = hashlib.sha256()
    for module in sorted(Path(__file__).parent.glob("*.py")):
        source_hash.update(module.name.encode() + b"\0" + module.read_bytes())
    server_metadata = {
        "backend_source_sha256": source_hash.hexdigest(),
        "source_snapshot": "Python source files present at application creation",
        "python_version": platform.python_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
    }

    @asynccontextmanager
    async def lifespan(app):
        app.state.worker.start()
        try:
            app.state.support_service.start()
            yield
        finally:
            await asyncio.gather(
                asyncio.to_thread(app.state.worker.stop),
                asyncio.to_thread(app.state.support_service.stop),
            )

    application = FastAPI(
        title="AgentProof",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url="/api/redoc",
        description="Document-grounded support drafting, explicit human review, and an inspectable LLM reliability runtime.",
        lifespan=lifespan,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        post_path_limits={
            "/api/support/documents": 8 * 1024 * 1024,
            "/api/support/tickets/import": 2 * 1024 * 1024,
        },
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
        www_redirect=False,
    )
    store = Store(db_path or os.getenv("AGENTPROOF_DB", "data/agentproof.sqlite3"))
    engine = Engine(store, provider_factory)
    execution_lock = threading.Lock()
    application.state.store, application.state.engine = store, engine
    application.state.answer_service = answer_service or AnswerService(
        os.getenv("ANSWER_LAB_DB", str(Path(store.path).with_name("answers.sqlite3")))
    )
    application.include_router(
        create_answer_router(
            application.state.answer_service,
            reports_dir=Path(__file__).resolve().parents[2] / "reports" / "answers",
        )
    )
    support_path = Path(store.path).with_name(Path(store.path).stem + ".support.sqlite3")
    application.state.support_service = support_service or SupportService(
        os.getenv("AGENTPROOF_SUPPORT_DB", str(support_path)),
        application.state.answer_service,
    )
    application.include_router(create_support_router(application.state.support_service))
    evidence_library = EvidenceLibrary(evidence_root)
    max_queued = max(1, min(100, int(os.getenv("AGENTPROOF_MAX_QUEUED", "8"))))

    def find_run(run_id):
        try:
            return store.get_run(run_id)
        except KeyError:
            raise HTTPException(404, "Run not found") from None

    def find_experiment(experiment_id):
        try:
            experiment = store.get_experiment(experiment_id)
        except KeyError:
            raise HTTPException(404, "Experiment not found") from None
        experiment["runs"] = [store.get_run(rid) for rid in experiment.pop("run_ids")]
        planned = (
            len(experiment["configuration"]["scenario_ids"])
            * experiment["configuration"]["repeats"]
            * 2
        )
        experiment["summary"] = summarize(
            experiment["runs"],
            experiment["provider"],
            status=experiment["status"],
            expected_run_count=planned,
        )
        if experiment.get("error"):
            experiment["summary"]["gate"]["reasons"].append(experiment["error"]["message"])
        return experiment

    @application.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @application.get("/api/ready")
    def readiness():
        worker_available = application.state.worker.available
        database_available = False
        try:
            # Read-only open cannot accidentally recreate a deleted evidence database.
            uri = Path(store.path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as connection:
                connection.execute("SELECT id FROM experiments LIMIT 1").fetchone()
            database_available = True
        except (sqlite3.Error, OSError):
            pass
        ready = worker_available and database_available
        return JSONResponse(
            {
                "status": "ready" if ready else "not_ready",
                "worker_available": worker_available,
                "database_available": database_available,
            },
            status_code=200 if ready else 503,
        )

    @application.get("/api/config")
    def config():
        try:
            LiveProvider()
            configured = True
        except ValueError:
            configured = False
        return {
            "providers": ["scripted", "openai"],
            "default_provider": "scripted",
            "model": os.getenv("AGENTPROOF_MODEL", ""),
            "live_configured": configured,
            "suite_version": SUITE_VERSION,
            "suite_hash": SUITE_HASH,
            "background_available": application.state.worker.available,
            "max_queued": max_queued,
        }

    @application.get("/api/scenarios")
    def scenarios():
        return [public_scenario(s) for s in SCENARIOS]

    def prepare_experiment(request: ExperimentRequest, background: bool = False):
        if request.scenarios is not None and request.scenario_ids is not None:
            raise HTTPException(422, "Use either scenarios or scenario_ids, not both")
        selected = request.scenarios if request.scenarios is not None else SCENARIOS
        by_id = {scenario.id: scenario for scenario in selected}
        ids = request.scenario_ids if request.scenario_ids is not None else [s.id for s in selected]
        if not ids or len(set(ids)) != len(ids) or any(sid not in by_id for sid in ids):
            raise HTTPException(422, "Select a nonempty list of unique known scenario IDs")
        try:
            configured_provider = (provider_factory or provider_for)(request.provider)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        experiment_id = uuid.uuid4().hex
        configuration = {
            "scenario_ids": ids,
            "repeats": request.repeats,
            "max_proposals": Engine.MAX_PROPOSALS,
            "provider": request.provider,
            **runtime_configuration(configured_provider),
            "temperature": 0,
            "variant_order": "alternating_by_scenario_and_repeat",
        }
        suite_hash = hashlib.sha256(
            json.dumps([by_id[sid].model_dump() for sid in ids], sort_keys=True).encode()
        ).hexdigest()
        experiment = {
            "id": experiment_id,
            "name": request.name or f"Refund release check · {now()[:16]}",
            "created_at": now(),
            "provider": request.provider,
            "status": "queued",
            "background": background,
            "cancel_requested": False,
            "run_ids": [],
            "summary": summarize(
                [],
                request.provider,
                status="queued",
                expected_run_count=len(ids) * request.repeats * 2,
            ),
            "suite_version": "custom" if request.scenarios is not None else SUITE_VERSION,
            "suite_hash": suite_hash,
            "scenarios": [by_id[sid].model_dump() for sid in ids],
            "prompt_hash": PROMPT_HASH,
            "configuration": configuration,
            "server_metadata": dict(server_metadata),
            "config_hash": hashlib.sha256(
                json.dumps(configuration, sort_keys=True).encode()
            ).hexdigest(),
            "notes": [
                "Authored synthetic scenarios; no real customer data or transactions.",
                "Baseline and guarded share the same initial prompt; guarded adds bounded feedback, policy enforcement and idempotency.",
                "Scripted outcomes are fault-fixture tests, not model benchmark accuracy.",
                "Live experiments include deliberately injected tool/model failures; per-run model_calls counts actual HTTP attempts.",
            ],
        }
        return experiment

    def execute_experiment(experiment, stop_event=None):
        # Replays use the same lock so local inference timing is not contaminated by
        # another request to this workbench. Other clients of the model server are outside scope.
        with execution_lock:
            execute_trials(experiment, stop_event)

    def execute_trials(experiment, stop_event=None):
        experiment_id = experiment["id"]
        provider = experiment["provider"]
        configuration = experiment["configuration"]
        ids = configuration["scenario_ids"]
        try:
            by_id = {item["id"]: Scenario.model_validate(item) for item in experiment["scenarios"]}
            configured_provider = engine.provider_factory(provider)
            effective = runtime_configuration(configured_provider)
            if (
                any(configuration.get(key) != value for key, value in effective.items())
                or experiment["prompt_hash"] != PROMPT_HASH
                or experiment["server_metadata"]["backend_source_sha256"]
                != server_metadata["backend_source_sha256"]
            ):
                store.finish_experiment(
                    experiment_id,
                    "failed",
                    {
                        "type": "ConfigurationChanged",
                        "message": "Provider settings or backend source changed after submission. No further trials were executed; submit a new experiment with the current configuration.",
                    },
                )
                return
            # Pin endpoint, model, credentials and limits for this experiment in memory.
            execution_engine = Engine(store, lambda _: configured_provider)
            for repeat in range(configuration["repeats"]):
                for index, sid in enumerate(ids):
                    variants = (
                        ("baseline", "guarded")
                        if (repeat + index) % 2 == 0
                        else ("guarded", "baseline")
                    )
                    for variant in variants:
                        current = store.get_experiment(experiment_id)
                        if current.get("cancel_requested"):
                            store.finish_experiment(experiment_id, "cancelled")
                            return
                        if stop_event is not None and stop_event.is_set():
                            store.finish_experiment(
                                experiment_id,
                                "failed",
                                {
                                    "type": "ServerShutdown",
                                    "message": "The server stopped between trials. Partial evidence is preserved; start a new experiment to run the complete suite.",
                                },
                            )
                            return
                        if runtime_configuration(engine.provider_factory(provider)) != effective:
                            store.finish_experiment(
                                experiment_id,
                                "failed",
                                {
                                    "type": "ConfigurationChanged",
                                    "message": "Provider configuration changed during execution. Partial evidence is preserved; start a new experiment with one consistent configuration.",
                                },
                            )
                            return
                        run = execution_engine.run(by_id[sid], variant, provider)
                        store.record_experiment_run(experiment_id, run["id"])
        except Exception as exc:  # noqa: BLE001 - persist failures at the experiment boundary
            # Preserve completed evidence but never certify a truncated suite. Persist only
            # the exception type; provider exception strings may contain credentials/data.
            error = {
                "type": type(exc).__name__,
                "message": "Execution stopped unexpectedly. The saved partial results cannot pass the release gate; start a new experiment after resolving the runtime error.",
            }
            store.finish_experiment(experiment_id, "failed", error)
        else:
            store.finish_experiment(experiment_id, "completed")

    application.state.worker = ExperimentWorker(store, execute_experiment)
    application.state.prepare_experiment = prepare_experiment
    application.state.execute_experiment = execute_experiment

    @application.post("/api/experiments", status_code=201)
    def experiment_create(request: ExperimentRequest, background: bool = False):
        if not application.state.worker.available:
            raise HTTPException(
                503, "Experiment worker is unavailable; start the server with its lifespan enabled"
            )
        experiment = prepare_experiment(request, background)
        experiment_id = experiment["id"]
        try:
            store.enqueue_experiment(experiment, max_queued)
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from None
        application.state.worker.wake()
        if background:
            return JSONResponse(find_experiment(experiment_id), status_code=202)
        # Keep the original synchronous response contract, but use the same durable
        # queue and worker as async requests. Disconnecting does not discard the job.
        while store.get_experiment(experiment_id)["status"] in ("queued", "running"):
            if not application.state.worker.available:
                raise HTTPException(
                    503,
                    f"Worker stopped; inspect experiment {experiment_id} after server recovery",
                )
            time.sleep(0.05)
        return find_experiment(experiment_id)

    @application.get("/api/evidence")
    def evidence_catalog():
        return JSONResponse(evidence_library.catalog(), headers={"Cache-Control": "no-store"})

    def verified_evidence(archive_id):
        try:
            return evidence_library.load(archive_id)
        except KeyError:
            raise HTTPException(404, "Recorded evidence not found") from None
        except EvidenceError as exc:
            raise HTTPException(422, str(exc)) from None

    @application.get("/api/evidence/{archive_id}")
    def evidence_get(archive_id: str):
        _, envelope = verified_evidence(archive_id)
        document = envelope["experiment"]
        document["summary"] = summarize(
            document["runs"], document["provider"], status=document["status"],
            expected_run_count=len(document["scenarios"]) * document["configuration"]["repeats"] * 2,
        )
        return JSONResponse(envelope, headers={"Cache-Control": "no-store"})

    @application.get("/api/evidence/{archive_id}/download")
    def evidence_download(archive_id: str):
        raw, envelope = verified_evidence(archive_id)
        return Response(
            raw, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="agentproof-{archive_id}.json"',
                     "Cache-Control": "no-store", "ETag": '"' + envelope["archive"]["sha256"] + '"'},
        )

    @application.get("/api/experiments")
    def experiments():
        results = []
        for item in store.experiments():
            full = find_experiment(item["id"])
            results.append(
                {
                    k: full[k]
                    for k in (
                        "id",
                        "name",
                        "created_at",
                        "provider",
                        "status",
                        "summary",
                        "cancel_requested",
                    )
                    if k in full
                }
            )
        return results

    @application.post("/api/comparisons")
    def experiment_compare(request: ComparisonRequest):
        reference = find_experiment(request.reference_id)
        candidate = find_experiment(request.candidate_id)
        captured_at = now()
        try:
            comparison = compare_reports(reference, candidate)
        except ComparisonError as exc:
            raise HTTPException(422, str(exc)) from None
        # Return the same detached JSON snapshots that were graded. Fetching fresh
        # details afterward could show a human approval that changed the stored run.
        return {
            **comparison,
            "captured_at": captured_at,
            "reference_snapshot": reference,
            "candidate_snapshot": candidate,
        }

    @application.get("/api/experiments/{experiment_id}")
    def experiment_get(experiment_id: str):
        return find_experiment(experiment_id)

    @application.post("/api/experiments/{experiment_id}/cancel")
    def experiment_cancel(experiment_id: str):
        try:
            store.cancel_experiment(experiment_id)
        except KeyError:
            raise HTTPException(404, "Experiment not found") from None
        return find_experiment(experiment_id)

    @application.get("/api/experiments/{experiment_id}/export")
    def experiment_export(experiment_id: str):
        return JSONResponse(
            find_experiment(experiment_id),
            headers={
                "Content-Disposition": f'attachment; filename="agentproof-{experiment_id}.json"'
            },
        )

    @application.get("/api/runs/{run_id}")
    def run_get(run_id: str):
        return find_run(run_id)

    @application.post("/api/runs/{run_id}/replay", status_code=201)
    def run_replay(run_id: str):
        find_run(run_id)
        if not execution_lock.acquire(blocking=False):
            raise HTTPException(409, "An experiment is running; replay after it finishes")
        try:
            return engine.replay(run_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        finally:
            execution_lock.release()

    @application.post("/api/runs/{run_id}/approve")
    def run_approve(run_id: str, request: ApprovalRequest):
        find_run(run_id)
        try:
            return engine.approve(run_id, request.approved)
        except ApprovalConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @application.get("/api/{unknown:path}")
    def unknown_api(unknown: str):
        raise HTTPException(404, "API route not found")

    web_dist = Path(
        os.getenv("AGENTPROOF_WEB_DIST", str(Path(__file__).resolve().parents[2] / "web" / "dist"))
    )
    if web_dist.is_dir():
        if (web_dist / "assets").is_dir():
            application.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @application.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            return FileResponse(web_dist / "index.html")

    return application


app = create_app()
