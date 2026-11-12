"""Inspect the real SupportDesk UI. Never makes model calls or invents replies.

Default is read-only. --prepare deliberately uploads one small knowledge document,
creates a ticket, imports CSV and JSON tickets, then archives the test document.
Use --prepare only with a disposable local workspace, never a customer workspace.
--recorded verifies zero API requests and disabled mutation controls.
"""

import argparse
import json
import os
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def inspect_ticket(page, output):
    detail = page.get_by_role("region", name="Selected ticket")
    expect(detail).to_be_visible()
    page.screenshot(path=str(output / "ticket-desktop.png"))
    detail.get_by_role("button", name="Evidence", exact=False).click()
    page.screenshot(path=str(output / "evidence-desktop.png"))
    detail.get_by_role("button", name="Activity", exact=True).click()
    expect(detail.get_by_role("heading", name="Ticket activity")).to_be_visible()
    detail.get_by_role("button", name="Draft", exact=True).click()
    trace = detail.get_by_role("button", name="Model trace", exact=True)
    if trace.count():
        trace.click()
        expect(page.get_by_role("dialog", name="Model trace")).to_be_visible()
        page.screenshot(path=str(output / "trace-desktop.png"))
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).not_to_be_visible()


def prepare_workspace(page, output):
    tag = "ui-check-" + uuid.uuid4().hex[:8]
    filename = tag + ".md"
    page.get_by_label("Upload knowledge files").set_input_files({
        "name": filename, "mimeType": "text/markdown",
        "buffer": b"# Browser verification\nThis is a temporary browser-check document. No model calls are needed.\n",
    })
    expect(page.get_by_role("heading", name=filename, exact=True)).to_be_visible()
    expect(page.locator(".sd-document-text")).to_contain_text("No model calls are needed.")
    page.get_by_role("navigation", name="Support navigation").get_by_role("button", name="Work queue").click()
    page.get_by_role("button", name="New ticket", exact=True).first.click()
    page.get_by_label("Ticket title", exact=True).fill(tag + " manual")
    page.get_by_label("Ticket request", exact=True).fill("A real saved browser-check ticket. Do not run inference.")
    page.get_by_label("External ticket ID", exact=True).fill(tag + "-manual")
    page.get_by_role("button", name="Add ticket", exact=True).click()
    expect(page.get_by_role("region", name="Selected ticket").get_by_role("heading", name=tag + " manual")).to_be_visible()
    inspect_ticket(page, output)
    for extension, content, mime in [
        ("csv", f'title,body,external_id\n{tag} CSV,CSV input verification.,{tag}-csv\n', "text/csv"),
        ("json", json.dumps([{"title": tag + " JSON", "body": "JSON input verification.", "external_id": tag + "-json"}]), "application/json"),
    ]:
        page.get_by_label("Import ticket file").set_input_files({"name": tag + "." + extension, "mimeType": mime, "buffer": content.encode()})
        expect(page.locator(".sd-ticket-list")).to_contain_text(tag + " " + extension.upper())
    page.get_by_label("Search tickets").fill(tag)
    expect(page.locator(".sd-queue-row")).to_have_count(3)
    page.get_by_label("Search tickets").fill("")
    page.get_by_role("navigation", name="Support navigation").get_by_role("button", name="Knowledge").click()
    page.locator(".sd-document-row").filter(has_text=filename).click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Archive document", exact=True).click()
    expect(page.locator(".sd-document-row").filter(has_text=filename)).to_have_count(0)
    return {"tag": tag, "document_read_and_archived": True, "manual_csv_json_tickets": 3, "model_calls": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010/")
    parser.add_argument("--output", type=Path, default=Path("artifacts/support-browser"))
    parser.add_argument("--recorded", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.recorded and args.prepare:
        parser.error("A recorded workflow cannot be modified")
    args.output.mkdir(parents=True, exist_ok=True)
    errors, requests = [], []
    evidence = {"recorded": args.recorded, "base": args.base}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.getenv("PLAYWRIGHT_CHANNEL", "chrome"))
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append({"method": request.method, "url": request.url}))
        page.goto(args.base)
        page.wait_for_load_state("networkidle")
        nav = page.get_by_role("navigation", name="Support navigation")
        expect(nav).to_be_visible()
        expect(page.get_by_role("heading", name="Work queue", exact=True)).to_be_visible()
        expect(page.get_by_role("alert")).to_have_count(0)
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Desktop overflow"
        page.screenshot(path=str(args.output / "queue-desktop.png"))
        evidence["tickets"] = page.locator(".sd-queue-row").count()
        if evidence["tickets"]:
            page.locator(".sd-queue-row > button").first.click()
            inspect_ticket(page, args.output)
        if args.recorded:
            expect(page.get_by_role("button", name="New ticket", exact=True).first).to_be_disabled()
            expect(page.get_by_role("button", name="Import", exact=True)).to_be_disabled()
            for button in page.locator(".sd-ticket-actions button").all():
                if "Download record" not in button.inner_text():
                    expect(button).to_be_disabled()
        else:
            page.get_by_role("button", name="New ticket", exact=True).first.click()
            expect(page.get_by_role("dialog", name="New support ticket")).to_be_visible()
            page.get_by_label("Ticket title").fill("Unsubmitted UI check")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).not_to_be_visible()
        if args.prepare:
            evidence["preparation"] = prepare_workspace(page, args.output)
        nav.get_by_role("button", name="Knowledge").click()
        expect(page.get_by_role("heading", name="Knowledge", exact=True)).to_be_visible()
        evidence["documents"] = page.locator(".sd-document-row").count()
        if evidence["documents"]:
            page.locator(".sd-document-row").first.click()
            expect(page.get_by_role("region", name="Document preview").get_by_role("heading")).to_be_visible()
        if args.recorded:
            expect(page.get_by_role("button", name="Upload", exact=True)).to_be_disabled()
        page.screenshot(path=str(args.output / "knowledge-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile overflow"
        page.screenshot(path=str(args.output / "knowledge-mobile.png"))
        nav.get_by_role("button", name="Work queue").click()
        back = page.get_by_role("region", name="Selected ticket").get_by_role("button", name="Work queue", exact=True)
        if back.is_visible():
            back.click()
        page.screenshot(path=str(args.output / "queue-mobile.png"))
        if page.locator(".sd-queue-row").count():
            page.locator(".sd-queue-row > button").first.click()
            expect(page.get_by_role("region", name="Selected ticket")).to_be_visible()
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile ticket overflow"
            page.screenshot(path=str(args.output / "ticket-mobile.png"))
        browser.close()
    api_requests = [r for r in requests if "/api/" in r["url"]]
    mutations = [r for r in requests if r["method"] not in ("GET", "HEAD", "OPTIONS")]
    assert not [r for r in requests if r["url"].endswith("/process") or r["url"].endswith("/answers/run")], "Unexpected inference"
    assert not errors, errors
    if args.recorded:
        assert not api_requests, api_requests
    if not args.prepare:
        assert not mutations, mutations
    evidence.update({"javascript_errors": errors, "api_requests": len(api_requests), "mutations": len(mutations), "model_calls": 0})
    (args.output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
