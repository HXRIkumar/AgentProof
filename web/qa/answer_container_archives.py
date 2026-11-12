"""Check container Answer Lab archive reads against checkout evidence without inference."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/container-answer-archives.json")
    args = parser.parse_args()

    def read(path):
        with urllib.request.urlopen(args.base.rstrip("/") + path, timeout=30) as response:
            return json.load(response)

    assert read("/api/answers/config")["configured"] is False
    assert read("/api/answers/runs") == []
    archives, pins = [], {}
    for kind, directory, endpoint in (("answers", "answers", "reports"),
                                      ("cache", "answers-cache", "cache-reports")):
        files = {path.stem: path for path in (ROOT / "reports" / directory).glob("*.json")}
        catalog = read("/api/answers/" + endpoint)
        assert {item["id"] for item in catalog} == set(files), f"Container {kind} archive set differs from checkout"
        pins[kind] = {}
        for item in catalog:
            raw = files[item["id"]].read_bytes()
            expected = json.loads(raw)
            assert read("/api/answers/" + endpoint + "/" + item["id"]) == expected
            assert item["summary"] == expected["summary"]
            digest = hashlib.sha256(raw).hexdigest()
            pins[kind][item["id"]] = digest
            archives.append({"kind": kind, "id": item["id"], "source_sha256": digest,
                             "api_content_matches_source": True})
    manifest = ROOT / "reports/answer-release-manifest.json"
    if manifest.exists():
        release = json.loads(manifest.read_text())
        assert {key: release[key] for key in pins} == pins, "Container archive set differs from pinned release"
    assert read("/api/answers/runs") == [], "Archive reads created a workspace run"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    proof = {"archives": archives, "release_manifest_verified": manifest.exists(),
             "model_configured": False, "workspace_runs": 0, "model_calls": 0, "status": "passed"}
    args.output.write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
