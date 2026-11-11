"""Fresh-database browser inspection of real recorded evidence, without inference.

Starts a disposable API with no live provider. Only one explicit scripted demo
executes; the archive is read from the actual pinned repository reports.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def serve():
    import uvicorn

    from agentproof.api import create_app
    from agentproof.evidence import EvidenceLibrary
    from agentproof.providers import ScriptedProvider

    counter = [0]

    class CountingFixture(ScriptedProvider):
        def propose(self, *args, **kwargs):
            counter[0] += 1
            return super().propose(*args, **kwargs)

    def factory(name):
        assert name == "scripted", "This QA server forbids live providers"
        return CountingFixture()

    app = create_app(os.environ["QA_DB"], provider_factory=factory)

    @app.get("/qa/provider-count")
    def provider_count():
        return {"calls": counter[0]}

    app.router.routes.insert(0, app.router.routes.pop())

    @app.post("/qa/id-collision")
    def create_collision():
        # QA-only setup: copy an actually executed scripted pending run under the
        # historical identifiers, then commit a real local approval. No archive
        # content is imported; only its IDs identify the deliberate collision.
        _, envelope = EvidenceLibrary().load("original-v01")
        archived = envelope["experiment"]
        archived_pending = next(r for r in archived["runs"] if r["status"] == "awaiting_approval")
        store = app.state.store
        local = store.get_experiment(store.experiments()[0]["id"])
        pending = next(
            store.get_run(rid)
            for rid in local["run_ids"]
            if store.get_run(rid)["status"] == "awaiting_approval"
        )
        scenario = store.get_scenario(pending["id"])
        pending["id"] = archived_pending["id"]
        store.save_run(pending, scenario)
        approved = app.state.engine.approve(pending["id"], True)
        assert len(approved["final_state"]["effects"]) == 1
        local.update(id=archived["id"], name="Workspace ID collision", run_ids=[pending["id"]])
        store.save_experiment(local)
        return {
            "experiment_id": local["id"],
            "run_id": pending["id"],
            "scenario_name": pending["scenario_name"],
        }

    app.router.routes.insert(0, app.router.routes.pop())
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["QA_PORT"]), log_level="warning")


def check():
    import httpx
    from playwright.sync_api import expect, sync_playwright

    output = Path(os.environ.get("SCREENSHOT_DIR", str(ROOT / "artifacts/browser-archive")))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentproof-archive-") as temp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "QA_DB": str(Path(temp) / "qa.sqlite3"),
            "QA_PORT": str(port),
            "AGENTPROOF_BASE_URL": "",
            "AGENTPROOF_MODEL": "",
            "AGENTPROOF_API_KEY": "",
        }
        origin = f"http://127.0.0.1:{port}"
        with (output / "server.log").open("w") as log:
            server = subprocess.Popen(
                [sys.executable, __file__, "--serve"], cwd=ROOT, env=env, stdout=log, stderr=log
            )
            try:
                for _ in range(100):
                    try:
                        if httpx.get(origin + "/api/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError("Archive QA server failed; inspect server.log")
                    time.sleep(0.1)
                else:
                    raise TimeoutError("Archive QA server did not start")
                with httpx.Client(base_url=origin, trust_env=False) as client:
                    assert client.get("/api/experiments").json() == []
                    assert client.get("/api/config").json()["live_configured"] is False
                    original = client.get("/api/evidence/original-v01").json()
                    recorded = original["experiment"]
                    failed = next(
                        r for r in recorded["runs"] if r["variant"] == "guarded" and not r["passed"]
                    )
                    pending = next(
                        r for r in recorded["runs"] if r["status"] == "awaiting_approval"
                    )
                    with sync_playwright() as p:
                        browser = p.chromium.launch(
                            headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
                        )
                        page = browser.new_page(viewport={"width": 1440, "height": 1000})
                        errors, mutations = [], []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on(
                            "request",
                            lambda request: (
                                mutations.append(request.url)
                                if request.method not in ("GET", "HEAD", "OPTIONS")
                                else None
                            ),
                        )
                        page.goto(origin)
                        page.wait_for_load_state("networkidle")
                        page.screenshot(path=str(output / "archive-fresh.png"))
                        expect(
                            page.get_by_role("button", name="Inspect recorded model evidence")
                        ).to_be_visible()
                        page.get_by_role(
                            "button", name="Open recorded Original suite · v0.1", exact=True
                        ).click()
                        expect(
                            page.get_by_role("heading", name="Original suite · v0.1", exact=True)
                        ).to_be_visible()
                        expect(
                            page.get_by_text("Read-only · recorded model evidence", exact=True)
                        ).to_be_visible()
                        page.get_by_label("Search scenarios").fill(failed["scenario_name"])
                        page.get_by_role(
                            "button",
                            name=f"Inspect {failed['scenario_name']}, guarded, trial 1",
                            exact=True,
                        ).click()
                        inspector = page.get_by_role("region", name="Run inspector")
                        inspector.get_by_role("tab", name="Checks").click()
                        expect(inspector.locator(".check-row.fail")).to_have_count(1)
                        expect(
                            inspector.get_by_role("button", name="Replay in fresh sandbox")
                        ).to_have_count(0)
                        expect(
                            page.get_by_role("button", name="Compare with reference")
                        ).to_have_count(0)
                        page.locator(".results-layout").evaluate(
                            "element => element.scrollIntoView()"
                        )
                        page.screenshot(path=str(output / "archive-failed-trial.png"))
                        page.get_by_label("Search scenarios").fill(pending["scenario_name"])
                        page.get_by_role(
                            "button",
                            name=f"Inspect {pending['scenario_name']}, guarded, trial 1",
                            exact=True,
                        ).click()
                        expect(
                            inspector.get_by_text("Historically pending approval", exact=True)
                        ).to_be_visible()
                        expect(
                            inspector.get_by_role("button", name="Approve refund", exact=True)
                        ).to_have_count(0)
                        expect(
                            inspector.get_by_role("button", name="Reject", exact=True)
                        ).to_have_count(0)
                        inspector.get_by_role("tab", name="Final state", exact=True).click()
                        assert (
                            json.loads(inspector.locator(".state-code").inner_text())["effects"]
                            == []
                        )
                        page.screenshot(path=str(output / "archive-pending.png"))
                        with page.expect_download() as download_info:
                            page.get_by_role(
                                "link", name="Download recorded JSON", exact=True
                            ).click()
                        path = output / "download-original.json"
                        download_info.value.save_as(path)
                        assert (
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            == original["archive"]["sha256"]
                        )
                        assert not mutations, mutations
                        assert client.get("/api/experiments").json() == []
                        assert client.get("/qa/provider-count").json()["calls"] == 0

                        # A genuinely executed scripted experiment retains normal workspace actions.
                        page.get_by_role("button", name="New experiment", exact=True).click()
                        page.get_by_label("Experiment name", exact=True).fill(
                            "Archive workspace regression"
                        )
                        page.get_by_role("button", name="Run 48 trials", exact=True).click()
                        expect(
                            page.get_by_role(
                                "heading", name="Archive workspace regression", exact=True
                            )
                        ).to_be_visible(timeout=60000)
                        expect(page.locator(".experiment-status")).to_have_text(
                            "completed", ignore_case=True, timeout=60000
                        )
                        page.get_by_role(
                            "button",
                            name="Inspect High-value approval, guarded, trial 1",
                            exact=True,
                        ).click()
                        expect(
                            inspector.get_by_role("button", name="Approve refund", exact=True)
                        ).to_be_visible()
                        expect(
                            inspector.get_by_role("button", name="Replay in fresh sandbox")
                        ).to_be_visible()
                        calls_after_demo = client.get("/qa/provider-count").json()["calls"]
                        assert calls_after_demo > 0
                        assert len(mutations) == 1
                        history = client.get("/api/experiments").json()
                        local_id = history[0]["id"]

                        # Delay delivery of real responses, not their contents. Latest selection wins.
                        page.evaluate("""() => {
                          const nativeFetch = window.fetch.bind(window);
                          window.fetch = async (...args) => {
                            const response = await nativeFetch(...args);
                            if (window.holdPath && String(args[0]).endsWith(window.holdPath)) {
                              window.responseHeld = true;
                              return await new Promise(resolve => { window.releaseHeld = () => resolve(response); });
                            }
                            return response;
                          };
                          window.holdPath = '/api/evidence/original-v01';
                        }""")
                        page.get_by_role(
                            "button", name="Open recorded Original suite · v0.1", exact=True
                        ).click()
                        page.wait_for_function("window.responseHeld === true")
                        page.get_by_role(
                            "button", name="Open recorded Challenge suite · v0.2", exact=True
                        ).click()
                        expect(
                            page.get_by_role("heading", name="Challenge suite · v0.2", exact=True)
                        ).to_be_visible()
                        page.evaluate("window.holdPath = null; window.releaseHeld()")
                        page.wait_for_timeout(150)
                        expect(
                            page.get_by_role("heading", name="Challenge suite · v0.2", exact=True)
                        ).to_be_visible()
                        page.evaluate(
                            "path => { window.holdPath = path; window.responseHeld = false; }",
                            "/api/experiments/" + local_id,
                        )
                        page.get_by_role("navigation", name="Experiment history").get_by_role(
                            "button"
                        ).first.click()
                        page.wait_for_function("window.responseHeld === true")
                        page.get_by_role(
                            "button",
                            name="Open recorded Independent verification · v0.3",
                            exact=True,
                        ).click()
                        expect(
                            page.get_by_role(
                                "heading", name="Independent verification · v0.3", exact=True
                            )
                        ).to_be_visible()
                        page.evaluate("window.holdPath = null; window.releaseHeld()")
                        page.wait_for_timeout(150)
                        expect(
                            page.get_by_role(
                                "heading", name="Independent verification · v0.3", exact=True
                            )
                        ).to_be_visible()
                        expect(
                            page.get_by_role("button", name="Compare with reference")
                        ).to_have_count(0)
                        assert len(mutations) == 1
                        assert client.get("/qa/provider-count").json()["calls"] == calls_after_demo
                        assert len(client.get("/api/experiments").json()) == 1

                        collision_response = client.post("/qa/id-collision")
                        collision_response.raise_for_status()
                        collision = collision_response.json()
                        assert collision["experiment_id"] == recorded["id"]
                        assert collision["run_id"] == pending["id"]
                        page.get_by_role("button", name="Refresh experiments", exact=True).click()
                        expect(
                            page.get_by_role(
                                "heading", name="Independent verification · v0.3", exact=True
                            )
                        ).to_be_visible()
                        local_button = page.get_by_role(
                            "navigation", name="Experiment history"
                        ).get_by_role("button", name="Workspace ID collision", exact=False)
                        expect(local_button).to_be_visible()
                        page.get_by_role(
                            "button", name="Open recorded Original suite · v0.1", exact=True
                        ).click()
                        expect(
                            page.get_by_role("heading", name="Original suite · v0.1", exact=True)
                        ).to_be_visible()
                        local_button.click()
                        expect(
                            page.get_by_role("heading", name="Workspace ID collision", exact=True)
                        ).to_be_visible()
                        page.get_by_role(
                            "button",
                            name=f"Inspect {collision['scenario_name']}, guarded, trial 1",
                            exact=True,
                        ).click()
                        inspector.get_by_role("tab", name="Final state", exact=True).click()
                        assert (
                            len(
                                json.loads(inspector.locator(".state-code").inner_text())["effects"]
                            )
                            == 1
                        )
                        expect(
                            inspector.get_by_role("button", name="Replay in fresh sandbox")
                        ).to_be_visible()
                        page.get_by_role(
                            "button", name="Open recorded Original suite · v0.1", exact=True
                        ).click()
                        expect(
                            page.get_by_role("heading", name="Original suite · v0.1", exact=True)
                        ).to_be_visible()
                        page.get_by_label("Search scenarios").fill(pending["scenario_name"])
                        page.get_by_role(
                            "button",
                            name=f"Inspect {pending['scenario_name']}, guarded, trial 1",
                            exact=True,
                        ).click()
                        expect(
                            inspector.get_by_text("Historically pending approval", exact=True)
                        ).to_be_visible()
                        expect(
                            inspector.get_by_role("button", name="Replay in fresh sandbox")
                        ).to_have_count(0)
                        inspector.get_by_role("tab", name="Final state", exact=True).click()
                        assert (
                            json.loads(inspector.locator(".state-code").inner_text())["effects"]
                            == []
                        )
                        assert (
                            client.get("/api/runs/" + pending["id"]).json()["outcome"] == "refunded"
                        )
                        raw = client.get("/api/evidence/original-v01/download").content
                        assert hashlib.sha256(raw).hexdigest() == original["archive"]["sha256"]
                        assert len(mutations) == 1
                        assert client.get("/qa/provider-count").json()["calls"] == calls_after_demo
                        page.get_by_role(
                            "button",
                            name="Open recorded Independent verification · v0.3",
                            exact=True,
                        ).click()
                        expect(
                            page.get_by_role(
                                "heading", name="Independent verification · v0.3", exact=True
                            )
                        ).to_be_visible()

                        page.evaluate("window.scrollTo(0, 0)")
                        page.screenshot(path=str(output / "archive-desktop.png"))
                        page.get_by_text("Recorded provenance", exact=True).click()
                        expect(
                            page.get_by_text(original["archive"]["model_revision"], exact=True)
                        ).to_be_visible()
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.evaluate("window.scrollTo(0, 0)")
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        ), "Mobile overflow"
                        page.screenshot(path=str(output / "archive-mobile.png"))
                        assert not errors, errors
                        browser.close()
                    report = {
                        "status": "passed",
                        "archive_count": 5,
                        "live_model_calls": 0,
                        "scripted_demo_calls": calls_after_demo,
                        "download_sha256": original["archive"]["sha256"],
                        "checks": [
                            "fresh empty database",
                            "failed live trial",
                            "historical approval",
                            "no archive mutations",
                            "exact raw download",
                            "normal scripted workspace",
                            "archive selection race",
                            "workspace-to-archive race",
                            "same-ID local approval cannot change archive",
                            "mobile layout",
                            "no JS errors",
                        ],
                    }
                    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
                    print(json.dumps(report, indent=2))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else check()
