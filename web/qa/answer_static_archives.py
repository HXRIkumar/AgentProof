"""Verify every packaged answer archive in the real recorded viewer; no model/API.

Raw HTTP downloads must match catalog SHA-256 values and local packaged bytes.
The UI Export JSON action is a reserialized export and is checked for content
equality. A release manifest, when present, pins the exact published archive set.
"""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from answer_evidence_review import inspect_report

ROOT = Path(__file__).resolve().parents[2]


def read_catalog(dist, folder):
    catalog = json.loads((dist / folder / "catalog.json").read_text())
    assert isinstance(catalog, list)
    assert len({item["id"] for item in catalog}) == len(catalog), "Duplicate archive IDs"
    for item in catalog:
        assert re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item["id"])
        assert re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "web/dist")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/answer-static-archives")
    parser.add_argument("--release-manifest", type=Path, default=ROOT / "reports/answer-release-manifest.json")
    parser.add_argument("--require-release-manifest", action="store_true")
    args = parser.parse_args()
    base = args.base.rstrip("/") + "/"
    assert urlparse(base).hostname in {"localhost", "127.0.0.1", "::1"}, "Use a local static server"
    catalogs = {"answers": read_catalog(args.dist, "answers"),
                "cache": read_catalog(args.dist, "answers-cache")}
    pins = {key: {item["id"]: item["sha256"] for item in catalog} for key, catalog in catalogs.items()}
    if args.release_manifest.exists():
        release = json.loads(args.release_manifest.read_text())
        assert {key: release[key] for key in pins} == pins, "Published archive set differs from release manifest"
    else:
        assert not args.require_release_manifest, "Release manifest is required before publication"
    args.output.mkdir(parents=True, exist_ok=True)
    errors, requests, checked = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"))
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))
        page.route("**/*", lambda route: route.continue_() if route.request.method == "GET" and
                   route.request.url.startswith(base) and "/api/" not in route.request.url else route.abort())
        page.goto(base)
        expect(page.get_by_role("heading", name="Experiments", exact=True)).to_be_visible()
        expect(page.get_by_text("Recorded model experiments", exact=True)).to_be_visible()
        if catalogs["answers"]:
            labels = page.get_by_label("Experiment report").locator("option").all_text_contents()
            assert len(labels) == len(set(labels)) == len(catalogs["answers"]), "Report labels must be distinct"
        else:
            expect(page.get_by_role("heading", name="No benchmark reports yet", exact=True)).to_be_visible()
        for key, catalog in catalogs.items():
            folder = "answers" if key == "answers" else "answers-cache"
            for item in catalog:
                url = base + folder + "/" + item["id"] + ".json"
                response = page.request.get(url)
                assert response.status == 200, url
                raw = response.body()
                assert hashlib.sha256(raw).hexdigest() == item["sha256"], "HTTP archive hash mismatch"
                assert raw == (args.dist / folder / (item["id"] + ".json")).read_bytes()
                report = json.loads(raw)
                assert report["summary"] == item["summary"], "Catalog summary differs from archive"
                if key == "answers":
                    inspect_report(page, report, args.output, item["id"])
                    for strategy_index, strategy in enumerate(("baseline", "validated", "adaptive")):
                        metrics = report["summary"]["strategies"].get(strategy)
                        if not metrics:
                            continue
                        answer = page.get_by_role("row", name="Answer error recovery", exact=False).locator("td").nth(strategy_index)
                        expect(answer).to_contain_text(f"{metrics['recovered']} / {metrics['initial_failures']} initially incorrect answers")
                        task = page.get_by_role("row", name="Task delivery recovery", exact=False).locator("td").nth(strategy_index)
                        if "task_recovered" in metrics:
                            expect(task).to_contain_text(f"{metrics['task_recovered']} / {metrics['initial_task_failures']} initially unsuccessful tasks")
                else:
                    page.get_by_role("button", name="Cache performance", exact=True).click()
                    page.get_by_label("Cache study report").select_option(item["id"])
                    expect(page.locator(".al-cache-latency")).to_be_visible()
                    expect(page.locator(".al-cache-table tbody tr")).to_have_count(len(report["groups"]))
                    page.locator(".al-cache-table tbody th button").first.click()
                    expect(page.get_by_role("complementary", name="Cache result detail")).to_be_visible()
                    page.get_by_role("button", name="Close cache result detail").click()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.set_viewport_size({"width": 1440, "height": 1100})
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export JSON", exact=True).click()
                destination = args.output / f"{folder}-{item['id']}-export.json"
                download.value.save_as(destination)
                assert json.loads(destination.read_text()) == report, "UI export differs from archive"
                checked.append({"kind": key, "id": item["id"], "sha256": item["sha256"],
                                "raw_http_hash": True, "ui_export_content": True})
        page.get_by_role("button", name="Workspace", exact=True).click()
        expect(page.get_by_role("button", name="Generate answer", exact=True)).to_be_disabled()
        browser.close()
    assert not errors, errors
    assert all(method == "GET" and url.startswith(base) and "/api/" not in url for method, url in requests), requests
    proof = {"archives": checked, "counts": {key: len(value) for key, value in catalogs.items()},
             "release_manifest_verified": args.release_manifest.exists(), "api_calls": 0, "model_calls": 0,
             "page_errors": errors, "distinct_report_labels": True, "recovery_denominators_checked": True}
    (args.output / "verification.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
