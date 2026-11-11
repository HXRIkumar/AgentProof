"""Real API/browser regression for release comparison; no fabricated report grades.

Two controlled scripted-provider revisions run the same ten cases, three times:
reference refuses cases 1/2, candidate refuses case3. Guarded correctness improves
24/30 to27/30 while case3 regresses3/3 to0/3. All grades come from executed engine
runs and ledger regrading. This is UI integration evidence, never model quality.
Run: uv run --with playwright==1.64.0 python web/qa/comparison_smoke.py
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

    counter = [0]

    class RevisionFixture(ScriptedProvider):
        model = "scripted-comparison-revisions-v1"

        def __init__(self):
            self.profile = Path(os.environ["QA_PROFILE"]).read_text()

        def propose(self, observation, *args, **kwargs):
            counter[0] += 1
            if self.profile == "slow":
                time.sleep(0.15)
            raw, tokens = super().propose(observation, *args, **kwargs)
            proposal = json.loads(raw)
            order_id = observation["order"]["id"]
            refusals = {"ORD-01", "ORD-02"} if self.profile == "reference" else {"ORD-03"}
            if order_id in refusals:
                proposal.update(
                    action="reject",
                    amount_cents=0,
                    reason="Controlled QA refusal; tests release regression review.",
                )
            return json.dumps(proposal), tokens

    app = create_app(os.environ["QA_DB"], provider_factory=lambda _: RevisionFixture())

    @app.get("/qa/provider-count")
    def provider_count():
        return {"calls": counter[0]}

    # Keep this QA-only observation route before the application's static mount.
    app.router.routes.insert(0, app.router.routes.pop())
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["QA_PORT"]), log_level="warning")


def check():
    import httpx
    from playwright.sync_api import expect, sync_playwright

    output = Path(os.environ.get("SCREENSHOT_DIR", str(ROOT / "artifacts/browser-comparison")))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentproof-comparison-") as temp:
        temp = Path(temp)
        profile = temp / "profile.txt"
        profile.write_text("reference")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "QA_DB": str(temp / "qa.sqlite3"),
            "QA_PORT": str(port),
            "QA_PROFILE": str(profile),
            "PYTHONPATH": str(ROOT / "src"),
        }
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
                scenarios = [
                    {
                        "id": f"review-{i:02}",
                        "name": f"Refund scenario {i:02}",
                        "category": "comparison_fixture",
                        "description": "Eligible synthetic refund for controlled release-comparison QA.",
                        "order": {"id": f"ORD-{i:02}"},
                    }
                    for i in range(1, 11)
                ]
                with httpx.Client(base_url=origin, timeout=120) as client:

                    def run(name, suite):
                        response = client.post(
                            "/api/experiments",
                            json={
                                "name": name,
                                "provider": "scripted",
                                "scenarios": suite,
                                "repeats": 3,
                            },
                        )
                        response.raise_for_status()
                        result = response.json()
                        assert result["status"] == "completed", result.get("error")
                        return result

                    reference = run("Reference · two known refusals", scenarios)
                    other = run("Different suite · incompatible", scenarios[:1])
                    profile.write_text("candidate")
                    equivalent = run("Previous candidate · same outcomes", scenarios)
                    approval_suite = [
                        {
                            "id": "approval-snapshot",
                            "name": "High-value snapshot check",
                            "category": "approval",
                            "description": "Snapshot keeps pre-approval evidence consistent.",
                            "order": {"id": "ORD-APPROVAL", "paid_cents": 18000},
                            "requested_cents": 18000,
                            "expected_outcome": "approval_required",
                        }
                    ]
                    approval_reference = run("Approval snapshot reference", approval_suite)
                    approval_candidate = run("Approval snapshot candidate", approval_suite)
                    candidate = run("Candidate · aggregate improves, case regresses", scenarios)
                    assert reference["summary"]["guarded"]["passed"] == 24
                    assert candidate["summary"]["guarded"]["passed"] == 27
                    assert candidate["summary"]["gate"]["passed"]
                    count_before = client.get("/qa/provider-count").json()["calls"]

                    with sync_playwright() as p:
                        browser = p.chromium.launch(
                            headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
                        )
                        page = browser.new_page(
                            viewport={"width": 1440, "height": 1000}, device_scale_factor=1
                        )
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(origin)
                        page.wait_for_load_state("networkidle")
                        expect(
                            page.get_by_role("heading", name=candidate["name"], exact=True)
                        ).to_be_visible()
                        page.get_by_role(
                            "button", name="Compare with reference", exact=True
                        ).click()
                        panel = page.get_by_role("region", name="Release comparison", exact=True)
                        panel.get_by_label("Reference experiment").select_option(reference["id"])
                        panel.get_by_role("button", name="Compare releases", exact=True).click()
                        expect(
                            panel.get_by_role(
                                "heading", name="Release comparison failed", exact=True
                            )
                        ).to_be_visible()
                        expect(
                            panel.get_by_text("Guarded regression in review-03", exact=True)
                        ).to_be_visible()
                        metrics = panel.get_by_role("region", name="guarded release metrics")
                        expect(metrics.get_by_text("24/30", exact=True)).to_be_visible()
                        expect(metrics.get_by_text("27/30", exact=True)).to_be_visible()
                        expect(panel.get_by_label("Case change filter")).to_have_value("regressed")
                        regression = panel.get_by_role(
                            "button",
                            name="Inspect Refund scenario 03 guarded comparison",
                            exact=True,
                        )
                        expect(regression).to_be_visible()
                        panel.scroll_into_view_if_needed()
                        page.screenshot(path=str(output / "comparison-gate.png"))
                        regression.click()
                        evidence = panel.get_by_role("region", name="Compared case evidence")
                        ref_pane = evidence.get_by_role("region", name="Reference evidence")
                        cand_pane = evidence.get_by_role("region", name="Candidate evidence")
                        expect(ref_pane.get_by_text("Pass", exact=True)).to_be_visible()
                        expect(cand_pane.get_by_text("Fail", exact=True)).to_be_visible()
                        expect(cand_pane.get_by_text("task outcome", exact=True)).to_be_visible()
                        assert (
                            cand_pane.get_by_label("Candidate trial").locator("option").count() == 3
                        )
                        cand_pane.get_by_label("Candidate trial").select_option(index=2)
                        cand_pane.get_by_role("tab", name="Trace", exact=True).click()
                        expect(cand_pane.locator(".comparison-event").first).to_be_visible()
                        cand_pane.locator(".comparison-event").first.locator("summary").click()
                        cand_pane.get_by_role("tab", name="Final state", exact=True).click()
                        assert json.loads(cand_pane.locator("pre").inner_text())["effects"] == []
                        ref_pane.get_by_role("tab", name="Final state", exact=True).click()
                        assert len(json.loads(ref_pane.locator("pre").inner_text())["effects"]) == 1
                        evidence.scroll_into_view_if_needed()
                        page.screenshot(path=str(output / "comparison-evidence.png"))
                        panel.get_by_label("Case change filter").select_option("improved")
                        expect(
                            panel.get_by_role(
                                "button",
                                name="Inspect Refund scenario 01 guarded comparison",
                                exact=True,
                            )
                        ).to_be_visible()
                        expect(
                            panel.get_by_role(
                                "button",
                                name="Inspect Refund scenario 02 guarded comparison",
                                exact=True,
                            )
                        ).to_be_visible()
                        expect(
                            panel.get_by_role(
                                "button",
                                name="Inspect Refund scenario 03 guarded comparison",
                                exact=True,
                            )
                        ).to_have_count(0)
                        with page.expect_download() as downloaded:
                            panel.get_by_role(
                                "button", name="Export comparison", exact=True
                            ).click()
                        downloaded.value.save_as(output / "comparison-export.json")
                        export = json.loads((output / "comparison-export.json").read_text())
                        assert (
                            export["reference_id"] == reference["id"]
                            and export["candidate_id"] == candidate["id"]
                        )
                        assert not export["gate"]["passed"]
                        measured = export["variants"]["guarded"]
                        assert metrics.locator("tbody tr").nth(1).locator("td").all_text_contents()[
                            :2
                        ] == ["30/30", "30/30"]
                        assert metrics.locator("tbody tr").nth(3).locator("td").all_text_contents()[
                            :2
                        ] == [
                            f"{measured['before']['p95_ms']:.1f}",
                            f"{measured['after']['p95_ms']:.1f}",
                        ]
                        page.set_viewport_size({"width": 390, "height": 844})
                        panel.scroll_into_view_if_needed()
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        ), "Mobile overflow"
                        page.screenshot(path=str(output / "comparison-mobile.png"))
                        page.set_viewport_size({"width": 1440, "height": 1000})

                        panel.get_by_label("Reference experiment").select_option(equivalent["id"])
                        panel.get_by_role("button", name="Compare releases", exact=True).click()
                        expect(
                            panel.get_by_role(
                                "heading", name="Comparison checks passed", exact=True
                            )
                        ).to_be_visible()
                        expect(panel.get_by_label("Case change filter")).to_have_value("changed")
                        expect(
                            panel.get_by_text("No cases match this filter.", exact=False)
                        ).to_be_visible()

                        panel.get_by_label("Reference experiment").select_option(other["id"])
                        expect(
                            panel.get_by_role(
                                "heading", name="Release comparison failed", exact=True
                            )
                        ).to_have_count(0)
                        panel.get_by_role("button", name="Compare releases", exact=True).click()
                        expect(panel.get_by_role("alert")).to_contain_text("Embedded suites differ")
                        expect(
                            panel.get_by_role("button", name="Export comparison", exact=True)
                        ).to_have_count(0)
                        assert client.get("/qa/provider-count").json()["calls"] == count_before, (
                            "Comparison executed provider calls"
                        )

                        # Delay delivery of an actual comparison response; mutate its saved
                        # candidate with an approval before the browser receives the snapshot.
                        page.get_by_role("navigation", name="Experiment history").get_by_role(
                            "button", name="Approval snapshot candidate", exact=False
                        ).click()
                        page.get_by_role(
                            "button", name="Compare with reference", exact=True
                        ).click()
                        panel.get_by_label("Reference experiment").select_option(
                            approval_reference["id"]
                        )
                        pending_run = next(
                            run for run in approval_candidate["runs"] if run["variant"] == "guarded"
                        )
                        captured = []
                        detail_requests = []

                        def track_detail(request):
                            if request.method == "GET" and "/api/experiments/" in request.url:
                                detail_requests.append(request.url)

                        def approve_after_capture(route):
                            response = route.fetch()
                            assert response.status == 200
                            snapshot = response.json()
                            captured.append(snapshot)
                            assert snapshot["captured_at"]
                            before = next(
                                run
                                for run in snapshot["candidate_snapshot"]["runs"]
                                if run["id"] == pending_run["id"]
                            )
                            assert (
                                before["status"] == "awaiting_approval"
                                and before["final_state"]["effects"] == []
                            )
                            committed = client.post(
                                f"/api/runs/{pending_run['id']}/approve", json={"approved": True}
                            )
                            committed.raise_for_status()
                            assert len(committed.json()["final_state"]["effects"]) == 1
                            route.fulfill(response=response)

                        page.on("request", track_detail)
                        page.route("**/api/comparisons", approve_after_capture)
                        panel.get_by_role("button", name="Compare releases", exact=True).click()
                        expect(
                            panel.get_by_role(
                                "heading", name="Comparison checks passed", exact=True
                            )
                        ).to_be_visible()
                        expect(panel.get_by_text("Snapshot captured", exact=False)).to_be_visible()
                        panel.get_by_label("Case change filter").select_option("all")
                        panel.get_by_role(
                            "button",
                            name="Inspect High-value snapshot check guarded comparison",
                            exact=True,
                        ).click()
                        snapshot_pane = panel.get_by_role("region", name="Candidate evidence")
                        expect(
                            snapshot_pane.get_by_text("approval required", exact=True)
                        ).to_be_visible()
                        snapshot_pane.get_by_role("tab", name="Final state", exact=True).click()
                        assert (
                            json.loads(snapshot_pane.locator("pre").inner_text())["effects"] == []
                        )
                        assert captured and not detail_requests, (
                            "Comparison must use response snapshots, not refetched details"
                        )
                        stored = client.get(f"/api/runs/{pending_run['id']}").json()
                        assert (
                            stored["status"] == "completed"
                            and len(stored["final_state"]["effects"]) == 1
                        )
                        with page.expect_download() as snapshot_download:
                            panel.get_by_role(
                                "button", name="Export comparison", exact=True
                            ).click()
                        snapshot_download.value.save_as(output / "comparison-snapshot-race.json")
                        saved_snapshot = json.loads(
                            (output / "comparison-snapshot-race.json").read_text()
                        )
                        assert saved_snapshot == captured[0]
                        page.unroute("**/api/comparisons", approve_after_capture)
                        page.remove_listener("request", track_detail)

                        profile.write_text("slow")
                        running_response = client.post(
                            "/api/experiments?background=true",
                            json={
                                "name": "Incomplete comparison candidate",
                                "provider": "scripted",
                                "scenarios": scenarios,
                                "repeats": 5,
                            },
                        )
                        assert running_response.status_code == 202
                        running_id = running_response.json()["id"]
                        page.reload()
                        expect(
                            page.get_by_role(
                                "heading", name="Incomplete comparison candidate", exact=True
                            )
                        ).to_be_visible()
                        page.get_by_role(
                            "button", name="Compare with reference", exact=True
                        ).click()
                        panel.get_by_label("Reference experiment").select_option(reference["id"])
                        expect(
                            panel.get_by_role("button", name="Compare releases", exact=True)
                        ).to_be_disabled()
                        expect(
                            panel.get_by_text("Comparison requires", exact=False)
                        ).to_be_visible()
                        refused = client.post(
                            "/api/comparisons",
                            json={"reference_id": reference["id"], "candidate_id": running_id},
                        )
                        assert (
                            refused.status_code == 422 and "completed" in refused.json()["detail"]
                        )
                        client.post(
                            f"/api/experiments/{running_id}/cancel", json={}
                        ).raise_for_status()
                        assert not errors, errors
                        browser.close()
                        print(
                            json.dumps(
                                {
                                    "status": "passed",
                                    "provider": "controlled scripted revisions, not LLM accuracy",
                                    "reference_guarded": "24/30",
                                    "candidate_guarded": "27/30",
                                    "regressed_case": "review-03: 3/3 -> 0/3",
                                    "candidate_experiment_gate": True,
                                    "comparison_gate": False,
                                    "checks": [
                                        "real executed and regraded ledger evidence",
                                        "aggregate-hidden regression",
                                        "compatible unchanged candidate passes comparison",
                                        "correct/invariant/token/latency metrics",
                                        "independent repeat selection",
                                        "trace/checks/final-state panes",
                                        "improvement filters",
                                        "JSON export",
                                        "incompatible suite refusal clears old result",
                                        "partial candidate UI+API refusal",
                                        "comparison triggers no provider calls",
                                        "approval race retains exact captured snapshot with no detail refetch",
                                        "390px no overflow",
                                        "no JS errors",
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
