"""Browser checks against the actual Answer Lab API, with no fabricated responses.

Run against the running application. --run permits one local-model run and one
repeat to exercise verified caching; otherwise this only edits client input and
reads saved evidence. Public-viewer --recorded asserts there are no API requests.
"""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--output", type=Path, default=Path("artifacts/answer-browser"))
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--recorded", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.recorded and args.run:
        parser.error("A recorded viewer cannot run inference")
    evidence = {"base": args.base, "recorded": args.recorded, "live_runs_requested": args.run}
    errors, api_calls = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"))
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: api_calls.append(request.url) if "/api/" in request.url else None)
        page.goto(args.base)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("navigation", name="Answer Lab navigation")).to_be_visible()
        page.get_by_role("button", name="Workspace", exact=True).click()
        expect(page.get_by_role("heading", name="Workspace", exact=True)).to_be_visible()
        page.get_by_label("Load example").select_option("extraction")
        expect(page.get_by_label("Task type")).to_have_value("extraction")
        expect(page.get_by_label("Output schema")).to_contain_text("incident_id")
        page.get_by_label("Add source", exact=True).click()
        page.get_by_label("Source title", exact=True).fill("Supplement")
        page.get_by_label("Source content", exact=True).fill("Additional source material.")
        page.get_by_role("button", name="Remove source", exact=True).click()
        expect(page.get_by_label("Source title", exact=True)).to_have_value("Incident 042 · service report")
        page.get_by_label("Load example").select_option("release")
        page.screenshot(path=str(args.output / "workspace-desktop.png"))
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Desktop overflow"
        evidence["source_editor"] = "passed"

        if args.run:
            expect(page.get_by_role("button", name="Generate answer", exact=True)).to_be_enabled()
            with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/answers/run"), timeout=180000) as response:
                page.get_by_role("button", name="Generate answer", exact=True).click()
            assert response.value.status == 200
            result = response.value.json()
            evidence["run_id"] = result["id"]
            evidence["run_status"] = result["status"]
            expect(page.get_by_role("region", name="Answer result")).to_be_visible()
            page.get_by_role("tab", name="Correction trace").click()
            expect(page.locator(".al-attempt")).to_have_count(len(result["attempts"]))
            page.screenshot(path=str(args.output / "actual-trace.png"))
            page.get_by_role("tab", name="Answer & sources").click()
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="Download run JSON").click()
            saved = args.output / "downloaded-run.json"
            downloaded.value.save_as(saved)
            assert json.loads(saved.read_text()) == result
            if result["status"] == "accepted":
                with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/answers/run"), timeout=180000) as replay:
                    page.get_by_role("button", name="Generate answer", exact=True).click()
                repeated = replay.value.json()
                assert repeated["cache"]["status"] == "exact_hit"
                assert repeated["usage"]["calls"] == 0
                evidence["exact_cache"] = "passed"
            page.get_by_role("button", name="Run history", exact=False).first.click()
            expect(page.get_by_role("heading", name="Run history", exact=True)).to_be_visible()
            page.locator(".al-history-list > button").first.click()
            expect(page.get_by_role("region", name="Answer result")).to_be_visible()
            evidence["history"] = "passed"

        page.get_by_role("button", name="Experiments", exact=False).first.click()
        expect(page.get_by_role("heading", name="Experiments", exact=True)).to_be_visible()
        page.wait_for_load_state("networkidle")
        if page.get_by_label("Experiment report").count():
            expect(page.locator(".al-cases-table tbody tr").first).to_be_visible(timeout=30000)
            evidence["report_rows"] = page.locator(".al-cases-table tbody tr").count()
            page.screenshot(path=str(args.output / "experiment-desktop.png"))
            page.locator(".al-cases-table tbody th button").first.click()
            expect(page.get_by_role("complementary", name="Case detail")).to_be_visible()
            page.get_by_role("tab", name="Correction trace").click()
            page.screenshot(path=str(args.output / "case-trace.png"))
            page.get_by_role("button", name="Close case detail").click()
            page.get_by_label("Search benchmark cases").fill("there-is-no-case-like-this-unique-test")
            expect(page.get_by_text("No cases match this filter.")).to_be_visible()
            page.get_by_label("Search benchmark cases").fill("")
            page.get_by_label("Filter case outcomes").select_option("recovered")
            assert all("Recovered" in row.inner_text() or "recovered" in row.inner_text() for row in page.locator(".al-cases-table tbody tr").all())
            page.get_by_label("Filter case outcomes").select_option("all")
            evidence["experiment_inspection"] = "passed"
        else:
            expect(page.get_by_role("heading", name="No benchmark reports yet")).to_be_visible()
            evidence["experiment_inspection"] = "no_reports_available"
        page.get_by_role("button", name="Cache performance", exact=True).click()
        expect(page.get_by_role("heading", name="Cache performance", exact=True)).to_be_visible()
        if page.get_by_label("Cache study report").count():
            expect(page.locator(".al-cache-latency")).to_be_visible(timeout=30000)
            page.screenshot(path=str(args.output / "cache-desktop.png"))
            page.locator(".al-cache-table tbody th button").first.click()
            expect(page.get_by_role("complementary", name="Cache result detail")).to_be_visible()
            page.get_by_role("button", name="Close cache result detail").click()
            evidence["cache_inspection"] = "passed"
        else:
            expect(page.get_by_role("heading", name="No cache study yet")).to_be_visible()
            evidence["cache_inspection"] = "no_cache_study_available"
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile cache overflow"
        page.screenshot(path=str(args.output / "cache-mobile.png"), full_page=True)
        page.get_by_role("button", name="Experiments", exact=False).first.click()
        page.wait_for_load_state("networkidle")
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile experiment overflow"
        page.screenshot(path=str(args.output / "experiment-mobile.png"), full_page=True)
        page.get_by_role("button", name="Workspace", exact=True).click()
        page.screenshot(path=str(args.output / "workspace-mobile.png"), full_page=True)
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile workspace overflow"
        page.get_by_role("button", name="Measurements", exact=True).click()
        expect(page.get_by_role("heading", name="What we measure")).to_be_visible()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile method overflow"
        evidence["responsive"] = "1440x1100 and 390x844 passed"
        # Read failures must be visible, not presented as an empty collection.
        # The controlled response is a browser-only fault; saved reports remain untouched.
        for label, endpoint, message, empty_heading in (
            ("Experiments", "reports", "Experiment reports could not be loaded", "No benchmark reports yet"),
            ("Cache performance", "cache-reports", "Cache reports could not be loaded", "No cache study yet"),
        ):
            resource = (
                "**/answers/catalog.json" if endpoint == "reports" else "**/answers-cache/catalog.json"
            ) if args.recorded else f"**/api/answers/{endpoint}"
            page.route(resource, lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"detail":"Controlled report read failure"}'
            ))
            page.get_by_role("button", name=label, exact=False).first.click()
            page.get_by_role("button", name="Refresh connection", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text(message)
            expect(page.get_by_role("heading", name=empty_heading, exact=True)).to_have_count(0)
            page.unroute(resource)
            page.get_by_role("button", name="Retry", exact=True).click()
            expect(page.get_by_role("alert")).to_have_count(0)
        evidence["collection_error_recovery"] = "reports and cache reports passed"
        assert not errors, errors
        if args.recorded:
            assert not api_calls, api_calls
        evidence["javascript_errors"] = errors
        evidence["api_requests"] = api_calls
        browser.close()
    (args.output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
