"""Independent static-export isolation and all-or-nothing validation checks."""

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentproof.evidence import CATALOG, EvidenceError, EvidenceLibrary

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("review_static_builder", ROOT / "scripts/build_static_evidence.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def file_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_ambient_credentials_and_private_workspace_files_never_enter_export(tmp_path):
    secret = "STATIC_REVIEW_PRIVATE_CREDENTIAL_SENTINEL"
    private_db = tmp_path / "private-workspace.sqlite3"
    private_db.write_text(secret)
    (tmp_path / ".env").write_text("AGENTPROOF_API_KEY=" + secret)
    (tmp_path / "unlisted-private-report.json").write_text('{"secret":"' + secret + '"}')
    code = """
import importlib.abc, importlib.util, socket, sqlite3, sys
from pathlib import Path
def forbidden(*args, **kwargs):
    raise AssertionError('Static export attempted a network or database operation')
socket.socket = forbidden
sqlite3.connect = forbidden
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in {'agentproof.api', 'agentproof.store', 'agentproof.providers', 'agentproof.jobs'}:
            raise AssertionError('Static export imported a runtime module: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
spec = importlib.util.spec_from_file_location('builder', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.build_evidence(Path(sys.argv[2]))
"""
    output = tmp_path / "evidence"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "AGENTPROOF_DB": str(private_db),
        "AGENTPROOF_API_KEY": secret,
        "AGENTPROOF_BASE_URL": "https://private.invalid/" + secret,
    }
    subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts/build_static_evidence.py"), str(output)],
        cwd=tmp_path, env=env, check=True, timeout=30,
    )
    exported = file_bytes(output)
    expected = {"catalog.json", "manifest.json"}
    expected.update(f"{entry.id}.json" for entry in CATALOG)
    expected.update(f"raw/{entry.sha256}.json" for entry in CATALOG)
    assert set(exported) == expected
    assert all(secret.encode() not in value for value in exported.values())
    assert private_db.read_text() == secret
    assert list(tmp_path.glob("*.sqlite*")) == [private_db]
    assert not list(tmp_path.glob("*.db*"))


def test_invalid_last_report_prevents_any_partial_static_distribution(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    for entry in CATALOG:
        raw = (ROOT / "reports" / entry.filename).read_bytes()
        (reports / entry.filename).write_bytes(raw)
    last = reports / CATALOG[-1].filename
    last.write_bytes(last.read_bytes() + b" ")
    output = tmp_path / "evidence"
    with pytest.raises(EvidenceError, match="integrity"):
        BUILDER.build_evidence(output, EvidenceLibrary(reports))
    assert not output.exists()


def test_static_exports_are_deterministic_and_leave_all_pinned_inputs_unchanged(tmp_path):
    inputs = {ROOT / "reports" / entry.filename: entry.sha256 for entry in CATALOG}
    first, second = tmp_path / "first", tmp_path / "second"
    a = BUILDER.build_evidence(first)
    b = BUILDER.build_evidence(second)
    assert a == b
    assert file_bytes(first) == file_bytes(second)
    for path, sha256 in inputs.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256
