"""Independent nested-base/reload check; builds into a private temporary outDir.

Leaves web/dist unchanged. Uses a static server only, with no API/model process.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = "/review/AgentProof_v2/"


def main():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix="agentproof-static-review-") as temp:
        site = Path(temp) / "site"
        dist = site / BASE.strip("/")
        subprocess.run(
            ["npm", "--prefix", "web", "run", "build:recorded", "--", "--base", BASE,
             "--outDir", str(dist), "--emptyOutDir"],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, "scripts/build_static_evidence.py", "--output", str(dist / "evidence")],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, "scripts/build_answer_evidence.py", "--output", str(dist / "answers"),
             "--cache-output", str(dist / "answers-cache")],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, "scripts/build_support_demo.py", "--output", str(dist / "support")],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        catalog = json.loads((dist / "evidence/catalog.json").read_text())
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site)))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        requests, errors = [], []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"),
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(10000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append((request.method, request.url)))
                fail_next = False

                def route_request(route):
                    nonlocal fail_next
                    url = route.request.url
                    if not url.startswith(origin + "/"):
                        route.abort()  # External fonts are unnecessary for this behavior check.
                    elif fail_next and url.endswith("/evidence/independent-v03.json"):
                        fail_next = False
                        route.fulfill(status=503, content_type="application/json",
                                      body='{"detail":"Controlled static evidence read failure"}')
                    else:
                        route.continue_()

                page.route("**/*", route_request)
                page.goto(origin + BASE + "?workspace=legacy")
                expect(page.get_by_role("heading", name="Independent verification · v0.3",
                                        exact=True)).to_be_visible()
                fail_next = True
                page.get_by_role("button", name="Open recorded Independent verification · v0.3",
                                 exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("Controlled static evidence read failure")
                # A real second GET is required: merely hiding the error and keeping
                # the old snapshot does not implement 'Reload evidence'.
                with page.expect_response(
                    lambda response: response.url.endswith("/evidence/independent-v03.json")
                    and response.status == 200,
                ):
                    page.get_by_role("button", name="Reload evidence", exact=True).click()
                expect(page.get_by_role("alert")).to_have_count(0)

                for item in catalog:
                    page.get_by_role("button", name=f"Open recorded {item['title']}", exact=True).click()
                    expect(page.get_by_role("heading", name=item["title"], exact=True)).to_be_visible()
                    with page.expect_download() as download:
                        page.get_by_role("link", name="Download recorded JSON", exact=True).click()
                    target = Path(temp) / f"{item['id']}.json"
                    download.value.save_as(target)
                    assert hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]
                for label in ("New experiment", "Approve refund", "Reject", "Replay in fresh sandbox",
                              "Stop after current trial", "Compare with reference"):
                    assert page.get_by_role("button", name=label, exact=True).count() == 0
                assert page.get_by_role("link", name="API reference", exact=True).count() == 0
                browser.close()
            subprocess.run(
                [sys.executable, "web/qa/answer_static_archives.py", "--base", origin + BASE,
                 "--dist", str(dist), "--output", "artifacts/answer-static-nested"],
                cwd=ROOT, check=True,
            )
            subprocess.run(
                [sys.executable, "web/qa/support_smoke.py", "--recorded", "--base", origin + BASE,
                 "--output", "artifacts/support-static-nested"],
                cwd=ROOT, check=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
        assert not errors, errors
        assert all(method in ("GET", "HEAD", "OPTIONS") for method, _ in requests)
        assert not any("/api/" in url for _, url in requests)
        local = [url for _, url in requests if url.startswith(origin + "/")]
        assert all(url.startswith(origin + BASE) for url in local), local
        print(json.dumps({
            "status": "passed", "base": BASE, "exact_downloads": len(catalog),
            "selected_archive_reload_refetched": True, "api_calls": 0,
            "mutations": 0, "model_calls": 0, "page_errors": errors,
        }, indent=2))


if __name__ == "__main__":
    main()
