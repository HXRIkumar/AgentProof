"""Build only validated, curated recorded evidence; never import the API or Store."""

import argparse
import json
from pathlib import Path

from agentproof.evidence import EvidenceLibrary
from agentproof.summary import summarize


def build_evidence(output: Path, library: EvidenceLibrary | None = None) -> dict:
    library = library or EvidenceLibrary()
    files = {}
    catalog = []
    hashes = {}
    # Validate every report before creating output; fail closed on any bad entry.
    for archive_id in library.entries:
        raw, envelope = library.load(archive_id)
        archive = envelope["archive"]
        filename = f"raw/{archive['sha256']}.json"
        archive["download_url"] = f"evidence/{filename}"
        archive["integrity_note"] = (
            "Validated at build time against the repository SHA-256 catalog; "
            "not a signed attestation."
        )
        document = envelope["experiment"]
        document["summary"] = summarize(
            document["runs"], document["provider"], status=document["status"],
            expected_run_count=len(document["scenarios"]) * document["configuration"]["repeats"] * 2,
        )
        files[filename] = raw
        files[f"{archive_id}.json"] = json.dumps(envelope, allow_nan=False).encode() + b"\n"
        catalog.append({**archive, "available": True})
        hashes[filename] = archive["sha256"]
    manifest = {"format": "agentproof-recorded-evidence-v1", "raw_sha256": hashes}
    files["catalog.json"] = json.dumps(catalog, allow_nan=False).encode() + b"\n"
    files["manifest.json"] = json.dumps(manifest, indent=2).encode() + b"\n"
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output is not empty; rebuild the static web distribution first")
    for name, raw in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("web/dist/evidence"))
    arguments = parser.parse_args()
    result = build_evidence(arguments.output)
    print(f"Built {len(result['raw_sha256'])} validated historical reports; no API or model started.")
