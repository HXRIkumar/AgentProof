"""Verify SupportDesk persistence in a disposable production container, without a model.

Run prepare before docker restart and verify afterwards. Only test knowledge and
unprocessed tickets are written. No artificial LLM results or reviews are created.
"""

import argparse
import base64
import json
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--state", type=Path, default=Path("artifacts/container-support.json"))
    args = parser.parse_args()

    def request(path, body=None, *, expected=200):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(args.base.rstrip("/") + "/api/support" + path,
                                     data=data, headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            assert response.status == expected, (path, response.status, expected)
            return json.load(response)

    config = request("/config")
    assert config["configured"] is False and config["worker_available"] is True
    if args.phase == "prepare":
        assert not args.state.exists(), "Use a new persistence record"
        assert request("/documents") == [] and request("/tickets") == []
        content = "# Container proof\nUse the documented reset link for account access.\n"
        payload = {"filename": "container-proof.md", "content_base64": base64.b64encode(content.encode()).decode()}
        first = request("/documents", payload, expected=201)
        assert request("/documents", payload, expected=201)["id"] == first["id"]
        payload["content_base64"] = base64.b64encode((content + "Check the spam folder.\n").encode()).decode()
        second = request("/documents", payload, expected=201)
        assert second["version"] == 2 and second["id"] != first["id"]
        assert [doc["id"] for doc in request("/documents")] == [second["id"]]
        original = request("/documents/" + first["id"])
        assert original["active"] is False and original["text"] == content
        ticket = request("/tickets", {"title": "Container persistence proof", "body": "Unprocessed test ticket.",
                                      "external_id": "container-manual-1"}, expected=201)
        imported = {"filename": "container-tickets.csv", "content_base64": base64.b64encode(
            b"title,body,external_id\nCSV persistence proof,Another unprocessed ticket.,container-csv-1\n"
        ).decode()}
        assert request("/tickets/import", imported)["created_count"] == 1
        assert request("/tickets/import", imported)["duplicate_count"] == 1
        request("/tickets/" + ticket["id"] + "/process", {"idempotency_key": "container-model-disabled"}, expected=503)
        request("/tickets/" + ticket["id"] + "/export", expected=409)
        tickets = [request("/tickets/" + item["id"]) for item in request("/tickets")]
        assert len(tickets) == 2
        assert all(item["status"] == "open" and item["result"] is None and item["active_job"] is None for item in tickets)
        recorded = {"status": "prepared", "model_calls": 0,
                    "knowledge_revision": request("/config")["knowledge_revision"],
                    "documents": [original, request("/documents/" + second["id"])], "tickets": tickets}
        args.state.parent.mkdir(parents=True, exist_ok=True)
        with args.state.open("x") as stream:
            json.dump(recorded, stream, indent=2)
            stream.write("\n")
        print("Prepared real document versions and unprocessed tickets; model-disabled and review guards passed")
    else:
        before = json.loads(args.state.read_text())
        assert config["knowledge_revision"] == before["knowledge_revision"]
        for document in before["documents"]:
            assert request("/documents/" + document["id"]) == document
        assert len(request("/documents")) == 1
        assert len(request("/tickets")) == len(before["tickets"])
        for ticket in before["tickets"]:
            assert request("/tickets/" + ticket["id"]) == ticket
        after = {**before, "status": "passed", "restart_preserved_document_history": True,
                 "restart_preserved_ticket_activity": True}
        destination = args.state.with_name(args.state.stem + "-verified.json")
        with destination.open("x") as stream:
            json.dump(after, stream, indent=2)
            stream.write("\n")
        print("Container restart preserved historical document versions, tickets and activity; no model calls")


if __name__ == "__main__":
    main()
