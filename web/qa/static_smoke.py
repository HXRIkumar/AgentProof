"""Exercise the actual recorded-only distribution beneath a GitHub Pages-style subpath."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web/dist"
OUTPUT = ROOT / "artifacts/browser-static"
OUTPUT.mkdir(parents=True, exist_ok=True)
PORT = int(os.getenv("STATIC_DEMO_PORT", "8051"))
ORIGIN = f"http://127.0.0.1:{PORT}"
errors, requests, mutations = [], [], []
catalog = json.loads((DIST / "evidence/catalog.json").read_text())
assert len(catalog) == 5


def capture(request):
    requests.append(request.url)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        mutations.append(request.url)


def assert_read_only(page):
    expect(page.get_by_role("region", name="Recorded-only demonstration")).to_be_visible()
    for name in ("New experiment", "Configure first experiment", "Approve refund",
                 "Reject", "Replay in fresh sandbox", "Stop after current trial"):
        assert page.get_by_role("button", name=name, exact=True).count() == 0, name
    assert page.get_by_text("API connected", exact=True).count() == 0
    assert page.get_by_role("link", name="API reference", exact=True).count() == 0
    assert page.get_by_role("navigation", name="Experiment history").count() == 0


with tempfile.TemporaryDirectory(prefix="agentproof-static-") as folder:
    shutil.copytree(DIST, Path(folder) / "AgentProof")
    with (OUTPUT / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind",
                                   "127.0.0.1", "--directory", folder], stdout=log, stderr=log)
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(ORIGIN + "/AgentProof/", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("Static server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True,
                                            channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"))
                context = browser.new_context(viewport={"width": 1440, "height": 1100})
                context.on("request", capture)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(ORIGIN + "/AgentProof/")
                expect(page.get_by_role("heading", name="Independent verification · v0.3",
                                        exact=True)).to_be_visible()
                assert_read_only(page)
                page.screenshot(path=str(OUTPUT / "desktop.png"))
                for item in catalog:
                    page.get_by_role("button", name=f"Open recorded {item['title']}", exact=True).click()
                    expect(page.get_by_role("heading", name=item["title"], exact=True)).to_be_visible()
                    assert_read_only(page)
                    with page.expect_download() as download:
                        page.get_by_role("link", name="Download recorded JSON", exact=True).click()
                    destination = OUTPUT / f"{item['id']}.json"
                    download.value.save_as(destination)
                    assert hashlib.sha256(destination.read_bytes()).hexdigest() == item["sha256"]
                page.get_by_role("button", name="Inspect recorded challenge failures", exact=True).click()
                expect(page.get_by_role("heading", name="Challenge suite · v0.2", exact=True)).to_be_visible()
                expect(page.locator(".filter-pills button.active")).to_contain_text("Failures")
                page.get_by_label("Search scenarios").fill("Suggested nominal refund")
                page.get_by_role("button", name="Inspect Suggested nominal refund, guarded, trial 1",
                                 exact=True).click()
                inspector = page.get_by_role("region", name="Run inspector")
                inspector.get_by_role("tab", name="Checks").click()
                inspector.locator(".check-row.fail").scroll_into_view_if_needed()
                expect(inspector.locator(".check-row.fail")).to_be_visible()
                page.screenshot(path=str(OUTPUT / "failure.png"))
                inspector.get_by_role("tab", name="Final state", exact=True).click()
                assert json.loads(inspector.locator(".state-code").inner_text())["effects"] == []
                inspector.get_by_role("tab", name="Trace").click()
                page.get_by_role("button", name="Open recorded Original suite · v0.1", exact=True).click()
                original = json.loads((DIST / "evidence/original-v01.json").read_text())
                pending = next(r for r in original["experiment"]["runs"]
                               if r["variant"] == "guarded" and r["status"] == "awaiting_approval")
                page.get_by_label("Search scenarios").fill(pending["scenario_name"])
                page.get_by_role("button", name=f"Inspect {pending['scenario_name']}, guarded, trial 1",
                                 exact=True).click()
                expect(page.get_by_text("Historically pending approval", exact=True)).to_be_visible()
                assert_read_only(page)
                context.close()
                context = browser.new_context(viewport={"width": 390, "height": 844})
                context.on("request", capture)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(ORIGIN + "/AgentProof/")
                expect(page.get_by_role("heading", name="Independent verification · v0.3",
                                        exact=True)).to_be_visible()
                assert_read_only(page)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(OUTPUT / "mobile.png"))
                page.get_by_role("button", name="Inspect recorded challenge failures", exact=True).click()
                expect(page.get_by_role("heading", name="Challenge suite · v0.2", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                context.close()
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
assert not errors, errors
assert not mutations, mutations
assert not any("/api/" in url for url in requests), requests
local = [url for url in requests if url.startswith(ORIGIN)]
assert all(url.startswith(ORIGIN + "/AgentProof/") for url in local), local
(OUTPUT / "verification.json").write_text(json.dumps({
    "status": "passed", "archive_count": len(catalog), "exact_download_hashes": True,
    "api_requests": 0, "mutation_requests": 0, "model_calls": 0, "page_errors": errors,
    "project_subpath": "/AgentProof/", "mobile_overflow": False,
}, indent=2) + "\n")
print("Static subpath browser checks passed: five reports, exact downloads, failure, historical approval, mobile.")
