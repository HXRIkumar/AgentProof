"""Integration smoke against a running AgentProof server, using real API responses.

Run from repository root: uv run --with playwright python web/qa/browser_smoke.py
Uses locally installed Chrome headless; set BASE_URL to change origin.
Only the scripted provider is exercised. No paid model requests are made.
"""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[2]
origin = os.environ.get("BASE_URL", "http://127.0.0.1:8010")
output = Path(os.environ.get("SCREENSHOT_DIR", str(root / "docs/screenshots")))
output.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"))
    context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(origin)
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Experiment workbench")).to_be_visible()

    page.get_by_role("button", name="New experiment", exact=True).click()
    page.get_by_label("Experiment name", exact=True).fill("Refund resilience · browser verification")
    expect(page.get_by_label("Decision provider")).to_have_value("scripted")
    expect(page.get_by_role("button", name="Run 48 trials", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Run 48 trials", exact=True).click()
    expect(page.get_by_role("heading", name="Refund resilience · browser verification")).to_be_visible(timeout=60000)
    expect(page.get_by_text("48 trials", exact=True)).to_be_visible()
    expect(page.get_by_text("Scripted fixture", exact=True)).to_be_visible()
    page.get_by_role("button", name="Dismiss notification").click()

    page.get_by_role("button", name="Recovered", exact=True).click()
    expect(page.get_by_role("button", name="Inspect Committed, then timed out, guarded, trial 1")).to_be_visible()
    page.screenshot(path=str(output / "workbench.png"))
    page.get_by_role("button", name="Inspect Committed, then timed out, guarded, trial 1").click()
    inspector = page.get_by_role("region", name="Run inspector")
    expect(inspector.get_by_role("heading", name="Committed, then timed out")).to_be_visible()
    expect(inspector.get_by_text("refunded", exact=True)).to_be_visible()
    page.locator(".results-layout").evaluate("element => window.scrollTo(0, element.getBoundingClientRect().top + window.scrollY - 20)")
    page.screenshot(path=str(output / "trace.png"))

    inspector.get_by_role("tab", name="Checks").click()
    expect(inspector.locator(".check-row").first).to_be_visible()
    inspector.get_by_role("tab", name="Final state", exact=True).click()
    expect(inspector.locator(".state-code")).to_contain_text("effects")
    state_before = json.loads(inspector.locator(".state-code").inner_text())
    assert len(state_before["effects"]) == 1, state_before
    inspector.get_by_role("button", name="Replay in fresh sandbox").click()
    expect(inspector.locator(".replay-note")).to_be_visible(timeout=30000)
    inspector.get_by_role("tab", name="Final state", exact=True).click()
    state_after = json.loads(inspector.locator(".state-code").inner_text())
    assert len(state_after["effects"]) == 1, state_after
    page.get_by_role("button", name="Close run inspector").click()
    page.get_by_role("button", name="Dismiss notification").click()

    page.get_by_role("button", name="Approval 1", exact=True).click()
    page.get_by_role("button", name="Inspect High-value approval, guarded, trial 1").click()
    expect(inspector.get_by_text("Review required", exact=True)).to_be_visible()
    inspector.get_by_role("tab", name="Final state", exact=True).click()
    pending = json.loads(inspector.locator(".state-code").inner_text())
    assert len(pending["effects"]) == 0, pending
    inspector.get_by_role("button", name="Approve refund", exact=True).click()
    expect(inspector.get_by_text("refunded", exact=True)).to_be_visible(timeout=30000)
    expect(inspector.get_by_role("button", name="Approve refund", exact=True)).to_have_count(0)
    inspector.get_by_role("tab", name="Final state", exact=True).click()
    approved = json.loads(inspector.locator(".state-code").inner_text())
    assert len(approved["effects"]) == 1, approved
    page.get_by_role("button", name="Close run inspector").click()
    page.get_by_role("button", name="Dismiss notification").click()

    with page.expect_download() as download_info:
        page.get_by_role("link", name="Export JSON", exact=True).click()
    download = download_info.value
    export = root / "artifacts/ui-export.json"
    export.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(export)
    payload = json.loads(export.read_text())
    assert len(payload["runs"]) == 48
    assert payload["provider"] == "scripted"
    assert all(run["safe"] for run in payload["runs"] if run["variant"] == "guarded")

    page.get_by_role("button", name="All", exact=True).click()
    page.get_by_label("Search scenarios").fill("no such scenario")
    expect(page.get_by_role("heading", name="No matching scenarios")).to_be_visible()
    page.get_by_role("button", name="Reset filters", exact=True).click()
    expect(page.get_by_role("button", name="Inspect Eligible full refund, guarded, trial 1")).to_be_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("window.scrollTo(0, 0)")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile horizontal overflow"
    page.screenshot(path=str(output / "mobile.png"))
    page.get_by_role("button", name="New experiment", exact=True).click()
    expect(page.get_by_label("Experiment name", exact=True)).to_be_visible()
    page.get_by_role("button", name="Clear", exact=True).click()
    expect(page.get_by_role("button", name="Run 0 trials", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Close experiment configuration").click()
    assert not errors, errors
    print(json.dumps({"status": "passed", "browser": "Chrome headless", "desktop": "1440x900", "mobile": "390x844", "trial_count": len(payload["runs"]), "checks": ["scripted experiment", "filtering", "trace", "checks", "final state", "replay without duplicate effects", "approval", "JSON export", "mobile overflow", "empty selection", "no JS errors"]}, indent=2))
    browser.close()
