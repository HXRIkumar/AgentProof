"""Package completed answer studies for the read-only web console, without inference."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from agentproof.answer_eval import summarize_report
from agentproof.answers.models import parse_json


def build_answer_evidence(source: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty; rebuild the web distribution first")
    packaged = []
    files = {}
    for path in sorted(source.glob("*.json"), reverse=True):
        if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", path.stem):
            raise ValueError("Invalid evidence file")
        raw = path.read_bytes()
        if len(raw) > 30_000_000:
            raise ValueError("Evidence exceeds the 30 MB limit")
        report = parse_json(raw.decode())
        if report.get("format_version") != "answer-lab-study-v1":
            continue
        recalculated = summarize_report(copy.deepcopy(report))
        if not recalculated["complete"]:
            raise ValueError(f"Incomplete answer study: {path.name}")
        if report["summary"] != recalculated:
            raise ValueError(f"Stored summary disagrees with raw evidence: {path.name}")
        files[path.name] = raw
        packaged.append(
            {
                "id": path.stem,
                "title": report["title"],
                "model": report["model"],
                "created_at": report["created_at"],
                "summary": recalculated,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    # Empty is a valid honest state before a model study exists.
    files["catalog.json"] = (
        json.dumps(packaged, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()
    manifest = {
        "format": "answer-lab-static-v1",
        "models_executed_by_site": False,
        "reports": {entry["id"]: entry["sha256"] for entry in packaged},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (output / name).write_bytes(content)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("reports/answers"))
    parser.add_argument("--output", type=Path, default=Path("web/dist/answers"))
    args = parser.parse_args()
    result = build_answer_evidence(args.source, args.output)
    print(f"Packaged {len(result['reports'])} completed answer studies, no model calls")
