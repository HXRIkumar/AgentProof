"""Read-only browser verification of an existing completed live experiment.

No trials, replays, approvals, or other mutations are issued.
Usage: EXPERIMENT_ID=... uv run --with playwright python web/qa/live_readonly.py
"""

import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[2]
origin = os.environ.get("BASE_URL", "http://127.0.0.1:8010")
experiment_id = os.environ["EXPERIMENT_ID"]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="chrome")
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    experiment = page.request.get(f"{origin}/api/experiments/{experiment_id}").json()
    assert experiment["status"] == "completed", experiment["status"]
    assert experiment["provider"] == "openai"
    assert len(experiment["runs"]) == 144
    page.goto(origin)
    page.wait_for_load_state("networkidle")
    history = page.request.get(f"{origin}/api/experiments").json()
    index = next(i for i, e in enumerate(history) if e["id"] == experiment_id)
    page.locator(".history-item").nth(index).click()
    expect(page.locator(".experiment-title .eyebrow")).to_contain_text(experiment_id[:8])
    expect(page.get_by_text("144 trials", exact=True)).to_be_visible()
    expect(page.locator(".experiment-meta").get_by_text("Live model", exact=True)).to_be_visible()
    for variant in ("baseline", "guarded"):
        for trial in (1, 2, 3):
            expect(page.get_by_role("button", name=f"Inspect Eligible full refund, {variant}, trial {trial}", exact=True)).to_have_count(1)
    page.get_by_role("button", name=f"Failures {sum(not r['passed'] for r in experiment['runs'])}", exact=True).click()
    candidate = next(r for r in experiment["runs"] if not r["passed"] and r["model_calls"] > 0)
    similar = [r for r in experiment["runs"] if r["scenario_id"] == candidate["scenario_id"] and r["variant"] == candidate["variant"]]
    trial = similar.index(candidate) + 1
    page.get_by_role("button", name=f"Inspect {candidate['scenario_name']}, {candidate['variant']}, trial {trial}", exact=True).click()
    inspector = page.get_by_role("region", name="Run inspector")
    expect(inspector.locator(".run-meta .mono")).to_have_text(candidate["id"][:8])
    expect(inspector.locator(".run-stats b").nth(1)).to_have_text(str(candidate["model_calls"]))
    expect(inspector.locator(".run-stats b").nth(3)).to_have_text(str(candidate["token_usage"]))
    expect(inspector.get_by_role("tab", name=f"Trace · {len(candidate['events'])}", exact=True)).to_be_visible()
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(root / "docs/screenshots/live-evaluation.png"))
    assert not errors, errors
    print(json.dumps({"status": "passed", "experiment_id": experiment_id, "runs": len(experiment["runs"]), "trials_per_variant_per_scenario": 3, "trace_run_id": candidate["id"], "model_calls": candidate["model_calls"], "tokens": candidate["token_usage"], "screenshot": "docs/screenshots/live-evaluation.png", "mutations": 0}, indent=2))
    browser.close()
