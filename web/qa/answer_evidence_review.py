"""Capture and verify completed Answer Lab evidence without any inference or API.

Builds a private recorded viewer at a nested base. Report bytes are copied only
into that temporary site, never into published evidence or web/dist. Development
screenshots are named and captioned separately from formal evaluation captures.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = "/review/answers/"


def assert_cost(text, value):
    if value is None:
        assert text == "Unknown", text
        return
    match = re.search(r"\$([\d,.]+)", text)
    assert match, text
    assert abs(float(match.group(1).replace(",", "")) - value) < 0.00000051


def inspect_report(page, report, output, prefix):
    page.get_by_label("Experiment report").select_option(report["id"])
    expect(page.locator(".al-cases-table tbody tr")).to_have_count(report["suite"]["case_count"])
    provider = report["configuration"]["runtime"]["provider"]
    metadata = page.locator(".al-model-metadata").first
    expect(metadata.locator("dd").nth(0)).to_have_text(report["model"])
    expect(metadata.locator("dd").nth(1)).to_have_text(provider.get("critic_model", "Unrecorded"))
    row = page.get_by_role("row", name="Estimated API cost · policy")
    for index, strategy in enumerate(("baseline", "validated", "adaptive")):
        metrics = report["summary"]["strategies"].get(strategy)
        if metrics:
            assert_cost(row.locator("td").nth(index).inner_text(),
                        metrics.get("estimated_cost_usd") if metrics.get("cost_known") else None)
    actual = report.get("actual_usage", {})
    study = page.get_by_role("region", name="Actual study accounting")
    if actual.get("cost_known"):
        assert_cost(study.locator("dt", has_text="Study API estimate").locator("+ dd").inner_text(),
                    actual["estimated_cost_usd"])
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(output / f"{prefix}-overview-desktop.png"))
    study.scroll_into_view_if_needed()
    page.screenshot(path=str(output / f"{prefix}-cost-desktop.png"))
    first_case = report["trials"][0]["case_id"]
    page.get_by_label("Search benchmark cases").fill(first_case)
    page.locator(".al-cases-table tbody th button").first.click()
    drawer = page.get_by_role("complementary", name="Case detail")
    for strategy, label in (("baseline", "Direct answer"), ("adaptive", "Critique + refine")):
        trial = next(t for t in report["trials"] if t["case_id"] == first_case and t["strategy"] == strategy)
        drawer.get_by_role("button", name=label, exact=True).click()
        expect(drawer.locator(".al-reference-grade b")).to_have_text(
            "Task passed reference grading" if trial["grade"]["correct"] else "Task did not pass reference grading")
        page.get_by_role("tab", name="Correction trace").click()
        expect(drawer.locator(".al-attempt")).to_have_count(len(trial["result"]["attempts"]))
        page.screenshot(path=str(output / f"{prefix}-{strategy}-case-desktop.png"))
    page.get_by_role("button", name="Close case detail").click()
    inspected = {"comparison_case": first_case, "escalations": [], "abstentions": []}
    for kind in ("escalations", "abstentions"):
        for trial in report["trials"]:
            if trial["strategy"] != "adaptive":
                continue
            for attempt in trial["result"]["attempts"]:
                qualifies = (attempt.get("route") == "critic_escalation" if kind == "escalations" else
                             attempt["abstained"] and attempt.get("critic") and
                             not any(c["name"] == "critic_supported" for c in attempt["checks"]))
                if not qualifies:
                    continue
                page.get_by_label("Search benchmark cases").fill(trial["case_id"])
                page.locator(".al-cases-table tbody th button").first.click()
                page.get_by_role("tab", name="Correction trace").click()
                panel = page.locator(".al-attempt").nth(attempt["index"] - 1)
                if panel.get_attribute("open") is None:
                    panel.locator("summary").click()
                expect(panel.locator(".al-attempt-model code")).to_have_text(attempt["generation"]["model"])
                if kind == "escalations":
                    expect(panel.locator(".al-escalation-note")).to_contain_text(attempt["escalation_reason"])
                else:
                    expect(panel.locator(".al-critic-flags")).to_contain_text("Supported · N/A")
                    expect(panel.locator(".al-critic-flags")).to_contain_text("Responsive · N/A")
                panel.scroll_into_view_if_needed()
                if not inspected[kind]:
                    page.screenshot(path=str(output / f"{prefix}-{kind}-desktop.png"))
                    page.set_viewport_size({"width": 390, "height": 844})
                    panel.scroll_into_view_if_needed()
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.screenshot(path=str(output / f"{prefix}-{kind}-mobile.png"))
                    page.set_viewport_size({"width": 1440, "height": 1100})
                inspected[kind].append({"case": trial["case_id"], "attempt": attempt["index"]})
                page.get_by_role("button", name="Close case detail").click()
    page.get_by_label("Search benchmark cases").fill("")
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("window.scrollTo(0, 0)")
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.screenshot(path=str(output / f"{prefix}-overview-mobile.png"))
    study.scroll_into_view_if_needed()
    page.screenshot(path=str(output / f"{prefix}-cost-mobile.png"))
    page.set_viewport_size({"width": 1440, "height": 1100})
    return inspected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", default=[])
    parser.add_argument("--development-report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = [(p, "formal") for p in args.report] + [(p, "development") for p in args.development_report]
    if not inputs:
        parser.error("Provide at least one completed report")
    reports = []
    for path, kind in inputs:
        raw = path.read_bytes()
        report = json.loads(raw)
        if report["status"] != "completed" or not report["summary"]["complete"]:
            parser.error(f"Report is not complete: {path}")
        if kind == "formal" and report["suite"]["split"] != "evaluation":
            parser.error("Use --development-report for a non-evaluation suite")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", report["id"]):
            parser.error("Unsafe report identifier")
        if any(item[3]["id"] == report["id"] for item in reports):
            parser.error("Report identifiers must be unique within one review")
        reports.append((path.resolve(), kind, raw, report))
    args.output.mkdir(parents=True, exist_ok=True)

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix="agentproof-answer-evidence-review-") as temp:
        site = Path(temp) / "site"
        dist = site / BASE.strip("/")
        source = Path(temp) / "reports"
        source.mkdir()
        for _, _, raw, report in reports:
            (source / f"{report['id']}.json").write_bytes(raw)
        subprocess.run(["npm", "--prefix", "web", "run", "build:recorded", "--", "--base", BASE,
                        "--outDir", str(dist), "--emptyOutDir"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/build_answer_evidence.py", "--source", str(source),
                        "--output", str(dist / "answers"), "--cache-source", str(Path(temp) / "no-cache-evidence"),
                        "--cache-output", str(dist / "answers-cache")], cwd=ROOT, check=True)
        for _, _, raw, report in reports:
            assert (dist / "answers" / f"{report['id']}.json").read_bytes() == raw
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site)))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        errors, requests, results = [], [], []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"))
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.emulate_media(reduced_motion="reduce")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append((request.method, request.url)))
                page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + BASE) else route.abort())
                page.goto(origin + BASE + "?workspace=answers")
                expect(page.get_by_role("heading", name="Experiments", exact=True)).to_be_visible()
                expect(page.get_by_text("Recorded model experiments", exact=True)).to_be_visible()
                for path, kind, raw, report in reports:
                    inspected = inspect_report(page, report, args.output, f"{kind}-{report['id']}")
                    assert path.read_bytes() == raw, "Source changed during review"
                    results.append({"id": report["id"], "kind": kind, "path": str(path),
                                    "sha256": hashlib.sha256(raw).hexdigest(), **inspected})
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
        assert not errors, errors
        assert all(method == "GET" and url.startswith(origin + BASE) and "/api/" not in url for method, url in requests), requests
        proof = {"reports": results, "base": BASE, "javascript_errors": errors, "api_requests": 0,
                 "model_calls": 0, "public_evidence_modified": False, "responsive": "1440 desktop and 390 mobile passed"}
        (args.output / "verification.json").write_text(json.dumps(proof, indent=2))
        (args.output / "CAPTIONS.md").write_text("\n\n".join(
            f"{kind.title()} study `{report['id']}`: recorded results from `{path}`. "
            + ("Development evidence only; not held-out evaluation." if kind == "development" else "Completed formal evaluation; metrics apply to this frozen suite.")
            for path, kind, _, report in reports) + "\n")
        print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
