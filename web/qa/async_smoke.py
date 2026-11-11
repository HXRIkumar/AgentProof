"""Browser check of real background jobs, cancellation and custom JSON import.

Runs an isolated SQLite API with a scripted provider delayed 120ms per proposal.
No paid API, fabricated server responses, or existing user database are used.
Run: uv run --with playwright==1.64.0 python web/qa/async_smoke.py
"""

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
    from agentproof.providers import ScriptedProvider

    class DelayedFixture(ScriptedProvider):
        def propose(self, *args, **kwargs):
            time.sleep(0.12)
            return super().propose(*args, **kwargs)

    uvicorn.run(
        create_app(os.environ["QA_DB"], provider_factory=lambda _: DelayedFixture()),
        host="127.0.0.1",
        port=int(os.environ["QA_PORT"]),
        log_level="warning",
    )


def check():
    import httpx
    from playwright.sync_api import expect, sync_playwright

    output = Path(os.environ.get("SCREENSHOT_DIR", str(ROOT / "artifacts/browser-async")))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentproof-browser-") as temp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "QA_DB": str(Path(temp) / "qa.sqlite3"), "QA_PORT": str(port)}
        origin = f"http://127.0.0.1:{port}"
        log_path = output / "server.log"
        with log_path.open("w") as log:
            server = subprocess.Popen(
                [sys.executable, __file__, "--serve"], cwd=ROOT, env=env, stdout=log, stderr=log
            )
            try:
                for _ in range(100):
                    try:
                        if httpx.get(origin + "/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError(log_path.read_text())
                    time.sleep(0.1)
                else:
                    raise RuntimeError("QA server did not start")
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
                    )
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 900}, device_scale_factor=1
                    )
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(origin)
                    page.wait_for_load_state("networkidle")

                    def start(name, trials, repeats=None):
                        page.get_by_role("button", name="New experiment", exact=True).click()
                        page.get_by_label("Experiment name", exact=True).fill(name)
                        if repeats:
                            page.get_by_label("Trials per scenario").select_option(str(repeats))
                        return submit(trials)

                    def submit(trials):
                        with page.expect_response(
                            lambda response: (
                                response.request.method == "POST"
                                and "/experiments?background=true" in response.url
                            )
                        ) as response:
                            page.get_by_role(
                                "button", name=f"Run {trials} trials", exact=True
                            ).click()
                        assert response.value.status == 202
                        return response.value

                    def details(experiment_id):
                        return page.request.get(origin + "/api/experiments/" + experiment_id).json()

                    created = start("Background progress verification", 48).json()
                    expect(
                        page.get_by_role("progressbar", name="Experiment progress")
                    ).to_be_visible()
                    expect(page.get_by_text("Evaluation in progress", exact=True)).to_be_visible()
                    page.get_by_label("Search scenarios").fill("Eligible full refund")
                    inspect = page.get_by_role(
                        "button", name="Inspect Eligible full refund, guarded, trial 1"
                    )
                    expect(inspect).to_be_visible(timeout=15000)
                    inspect.click()
                    page.wait_for_timeout(1600)
                    expect(page.get_by_label("Search scenarios")).to_have_value(
                        "Eligible full refund"
                    )
                    expect(page.get_by_role("region", name="Run inspector")).to_be_visible()
                    expect(
                        page.get_by_role("button", name="Replay in fresh sandbox")
                    ).to_be_disabled()
                    page.screenshot(path=str(output / "background-progress.png"))
                    page.reload()
                    expect(
                        page.get_by_role("heading", name="Background progress verification")
                    ).to_be_visible()
                    expect(page.get_by_text("48 trials", exact=True)).to_be_visible(timeout=30000)
                    expect(page.locator(".experiment-status")).to_have_text(
                        "completed", ignore_case=True
                    )
                    original = details(created["id"])
                    assert original["status"] == "completed" and len(original["runs"]) == 48

                    page.get_by_role("button", name="New experiment", exact=True).click()
                    page.get_by_label("Experiment name", exact=True).fill(
                        "Imported suite verification"
                    )
                    with page.expect_download() as downloaded:
                        page.get_by_role("button", name="Download example", exact=True).click()
                    downloaded.value.save_as(Path(temp) / "example.json")
                    custom = json.loads((Path(temp) / "example.json").read_text())
                    assert custom[0]["id"] == "custom-refund-01"
                    custom.append(
                        {
                            **custom[0],
                            "id": "custom-expired-02",
                            "name": "Expired custom refund",
                            "order": {**custom[0]["order"], "age_days": 31},
                            "expected_outcome": "rejected",
                        }
                    )
                    upload = page.get_by_label("Import scenario JSON")
                    upload.set_input_files(
                        {
                            "name": "custom.json",
                            "mimeType": "application/json",
                            "buffer": json.dumps(custom).encode(),
                        }
                    )
                    expect(page.get_by_text("Imported scenario suite", exact=True)).to_be_visible()
                    expect(
                        page.get_by_role("button", name="Run 4 trials", exact=True)
                    ).to_be_enabled()
                    upload.set_input_files(
                        {"name": "bad.json", "mimeType": "application/json", "buffer": b"{broken"}
                    )
                    expect(page.get_by_role("alert")).to_contain_text("not valid JSON")
                    expect(
                        page.get_by_role("button", name="Run 4 trials", exact=True)
                    ).to_be_enabled()
                    page.screenshot(path=str(output / "custom-import-validation.png"))
                    response = submit(4)
                    request_body = response.request.post_data_json
                    assert (
                        len(request_body["scenarios"]) == 2 and "scenario_ids" not in request_body
                    )
                    imported_id = response.json()["id"]
                    expect(page.get_by_text("4 trials", exact=True)).to_be_visible(timeout=15000)
                    expect(page.locator(".experiment-status")).to_have_text(
                        "completed", ignore_case=True
                    )
                    imported = details(imported_id)
                    assert imported["suite_version"] == "custom" and len(imported["runs"]) == 4
                    assert all(run["passed"] for run in imported["runs"])

                    running_id = start("Cancel running verification", 240, repeats=5).json()["id"]
                    expect(
                        page.get_by_role(
                            "button", name="Inspect Eligible full refund, guarded, trial 1"
                        )
                    ).to_be_visible(timeout=15000)
                    history = page.get_by_role("navigation", name="Experiment history")
                    history.get_by_role(
                        "button", name="Imported suite verification", exact=False
                    ).click()
                    page.wait_for_timeout(1600)
                    expect(
                        page.get_by_role("heading", name="Imported suite verification")
                    ).to_be_visible()
                    history.get_by_role(
                        "button", name="Cancel running verification", exact=False
                    ).click()
                    page.get_by_role("button", name="Stop after current trial", exact=True).click()
                    expect(page.locator(".experiment-status")).to_have_text(
                        "cancelled", ignore_case=True, timeout=15000
                    )
                    cancelled = details(running_id)
                    assert cancelled["status"] == "cancelled" and 0 < len(cancelled["runs"]) < 240
                    assert not cancelled["summary"]["gate"]["passed"]
                    page.screenshot(path=str(output / "cancelled-evidence.png"))
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.evaluate("window.scrollTo(0, 0)")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), "Mobile overflow"
                    page.screenshot(path=str(output / "cancelled-mobile.png"))

                    # Occupy the single worker, then cancel a second job before any trial starts.
                    page.set_viewport_size({"width": 1440, "height": 900})
                    blocker_response = page.request.post(
                        origin + "/api/experiments?background=true",
                        data={
                            "name": "Queue occupancy fixture",
                            "provider": "scripted",
                            "repeats": 5,
                        },
                    )
                    assert blocker_response.status == 202
                    blocker_id = blocker_response.json()["id"]
                    queued_id = start("Queued cancellation verification", 48).json()["id"]
                    expect(page.locator(".experiment-status")).to_have_text(
                        "queued", ignore_case=True
                    )
                    page.get_by_role("button", name="Stop after current trial", exact=True).click()
                    expect(page.locator(".experiment-status")).to_have_text(
                        "cancelled", ignore_case=True
                    )
                    queued = details(queued_id)
                    assert queued["status"] == "cancelled" and len(queued["runs"]) == 0
                    assert not queued["summary"]["gate"]["passed"]
                    page.request.post(
                        origin + "/api/experiments/" + blocker_id + "/cancel", data={}
                    )
                    assert not errors, errors
                    browser.close()
                    print(
                        json.dumps(
                            {
                                "status": "passed",
                                "completed_fixture_trials": 48,
                                "custom_trials": 4,
                                "cancelled_trial_count": len(cancelled["runs"]),
                                "cancelled_queued_trials": len(queued["runs"]),
                                "checks": [
                                    "202 background submission",
                                    "progress polling",
                                    "preserved search and inspector",
                                    "reload persistence",
                                    "custom suite download/import",
                                    "invalid import preserves suite",
                                    "mutually exclusive custom payload",
                                    "history selection during active work",
                                    "real cancellation retains evidence",
                                    "queued cancellation executes no trials",
                                    "partial gate fails",
                                    "mobile overflow",
                                    "no JavaScript errors",
                                ],
                            },
                            indent=2,
                        )
                    )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else check()
