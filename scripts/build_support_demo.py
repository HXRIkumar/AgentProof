"""Package a real SupportDesk recording byte-for-byte; never synthesize demo replies."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MAX_RECORDING_BYTES = 20_000_000


def _object_pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            raise ValueError("Duplicate JSON keys in support recording")
        result[name] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-finite JSON value in support recording")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_demo(demo):
    _require(isinstance(demo, dict) and demo.get("format") == "agentproof-support-demo-v1",
             "Expected a recorded agentproof-support-demo-v1 document")
    _require(isinstance(demo.get("config"), dict), "Recorded support configuration is missing")
    forbidden = {"api_key", "apikey", "authorization", "access_token", "secret", "password"}
    pending = [demo["config"]]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            _require(not any(str(key).lower() in forbidden for key in item),
                     "Recording configuration contains a private credential field")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    documents, tickets = demo.get("documents"), demo.get("tickets")
    _require(isinstance(documents, list) and bool(documents), "Recorded knowledge documents are required")
    _require(isinstance(tickets, list) and bool(tickets), "Recorded tickets are required")
    for kind, records in (("document", documents), ("ticket", tickets)):
        identifiers = []
        for record in records:
            _require(isinstance(record, dict) and isinstance(record.get("id"), str)
                     and bool(record["id"]), f"Recorded {kind} ID is missing")
            identifiers.append(record["id"])
        _require(len(set(identifiers)) == len(identifiers), f"Duplicate recorded {kind} IDs")
    for document in documents:
        _require(isinstance(document.get("filename"), str) and bool(document["filename"]),
                 "Recorded document filename is missing")
        _require(type(document.get("version")) is int and document["version"] >= 1,
                 "Recorded document version is missing")
        _require(isinstance(document.get("text"), str) and bool(document["text"].strip()),
                 "Full extracted document text is required for the static preview")
    runs = []
    for ticket in tickets:
        _require(isinstance(ticket.get("events"), list), "Full recorded ticket activity is required")
        result = ticket.get("result")
        if result is None:
            continue  # Open, cancelled and failed tickets are retained, not fabricated.
        _require(isinstance(result, dict) and isinstance(result.get("answer_run"), dict),
                 "Recorded ticket result is missing its answer trace")
        run = result["answer_run"]
        _require(isinstance(run.get("id"), str) and isinstance(run.get("attempts"), list),
                 "Recorded answer trace is incomplete")
        _require(all(isinstance(attempt, dict) for attempt in run["attempts"]),
                 "Recorded answer attempts must be objects")
        if any(isinstance(attempt.get("generation"), dict)
               and isinstance(attempt["generation"].get("text"), str)
               and bool(attempt["generation"]["text"].strip())
               for attempt in run["attempts"]):
            runs.append(run["id"])
    _require(bool(runs), "A real recorded answer-generation trace is required; empty demos cannot publish")
    return {"document_count": len(documents), "ticket_count": len(tickets),
            "recorded_answer_runs": len(set(runs))}


def build_support_demo(source: Path, output: Path) -> dict:
    if not source.is_file() or source.is_symlink():
        raise ValueError("Real support recording is missing; publication cannot use placeholder data")
    if source.stat().st_size > MAX_RECORDING_BYTES:
        raise ValueError("Support recording exceeds the 20 MB packaging limit")
    raw = source.read_bytes()
    demo = json.loads(raw, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
    counts = validate_demo(demo)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Support output must be empty; rebuild the distribution first")
    fingerprint = hashlib.sha256(raw).hexdigest()
    manifest = {"format": "agentproof-support-static-v1", "recorded_only": True,
                "models_executed_by_site": False, "source": source.name,
                "files": {"demo.json": fingerprint}, **counts}
    output.mkdir(parents=True, exist_ok=True)
    (output / "demo.json").write_bytes(raw)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("reports/support-demo-v1.json"))
    parser.add_argument("--output", type=Path, default=Path("web/dist/support"))
    args = parser.parse_args()
    manifest = build_support_demo(args.source, args.output)
    print(json.dumps({"packaged": "support/demo.json", **manifest}))
