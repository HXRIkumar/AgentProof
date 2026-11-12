import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentproof.evidence import CATALOG, EvidenceError, EvidenceLibrary

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("static_builder", ROOT / "scripts/build_static_evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_static_export_keeps_all_original_bytes_and_derived_summaries(tmp_path):
    manifest = module.build_evidence(tmp_path / "evidence")
    output = tmp_path / "evidence"
    catalog = json.loads((output / "catalog.json").read_text())
    assert len(catalog) == len(CATALOG) == 5
    assert len(list(output.rglob("*.json"))) == 12
    for item in catalog:
        raw = (output.parent / item["download_url"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert manifest["raw_sha256"][f"raw/{item['sha256']}.json"] == item["sha256"]
        envelope = json.loads((output / f"{item['id']}.json").read_text())
        assert envelope["archive"] == {k: v for k, v in item.items() if k != "available"}
        assert envelope["experiment"]["summary"]["total_runs"] == item["trial_count"]
        assert item["read_only"] and "build time" in item["integrity_note"]
    challenge = json.loads((output / "challenge-v02.json").read_text())
    assert challenge["experiment"]["summary"]["guarded"]["passed"] == 54
    assert any(not r["passed"] for r in challenge["experiment"]["runs"])
    assert any(r["status"] == "awaiting_approval" for r in challenge["experiment"]["runs"])


def test_builder_fails_before_writing_on_tampering_or_missing_report(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / CATALOG[0].filename).write_text("{}")
    output = tmp_path / "output"
    with pytest.raises(EvidenceError, match="integrity"):
        module.build_evidence(output, EvidenceLibrary(reports))
    assert not output.exists()
    with pytest.raises(EvidenceError, match="not included"):
        module.build_evidence(output, EvidenceLibrary(reports, entries=CATALOG[1:]))
    assert not output.exists()


def test_builder_does_not_overwrite_output(tmp_path):
    (tmp_path / "existing.txt").write_text("keep")
    with pytest.raises(ValueError, match="not empty"):
        module.build_evidence(tmp_path)
    assert (tmp_path / "existing.txt").read_text() == "keep"


def test_fresh_process_builder_never_imports_api_store_or_providers(tmp_path):
    code = """
import importlib.util, socket, sys
from pathlib import Path
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network access'))
spec = importlib.util.spec_from_file_location('builder', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.build_evidence(Path(sys.argv[2]))
assert not {'agentproof.api', 'agentproof.store', 'agentproof.providers', 'agentproof.jobs'} & set(sys.modules)
"""
    env = {**os.environ, "AGENTPROOF_DB": str(tmp_path / "must-not-exist.sqlite3")}
    subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts/build_static_evidence.py"),
         str(tmp_path / "out")], cwd=tmp_path, env=env, check=True, timeout=30,
    )
    assert not list(tmp_path.glob("*.sqlite*"))
    assert not list(tmp_path.glob("*.db*"))
