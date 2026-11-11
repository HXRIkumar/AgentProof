"""Exercise evidence preservation through the real comparison command."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/compare.py"
FIXTURE = ROOT / "reports/fixture-v1.json"


def invoke(source, output, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), str(source), "--output", str(output), *extra],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_raw_input_cannot_be_overwritten_even_explicitly(tmp_path):
    source = tmp_path / "raw.json"
    original = FIXTURE.read_bytes()
    source.write_bytes(original)
    for args in ((), ("--overwrite",)):
        result = invoke(source, source, *args)
        assert result.returncode == 2
        assert "input report" in result.stderr
        assert source.read_bytes() == original
        assert not source.with_suffix(".md").exists()


def test_existing_derived_output_requires_explicit_overwrite(tmp_path):
    output = tmp_path / "comparison"
    output.with_suffix(".md").write_text("Existing human notes\n")
    result = invoke(FIXTURE, output)
    assert result.returncode == 2
    assert "already exists" in result.stderr
    assert output.with_suffix(".md").read_text() == "Existing human notes\n"
    assert not output.with_suffix(".json").exists()
    result = invoke(FIXTURE, output, "--overwrite")
    assert result.returncode == 0, result.stderr
    assert json.loads(output.with_suffix(".json").read_text())["gate"]["passed"]
    assert output.with_suffix(".md").read_text().startswith("# Release comparison")


def test_hardlink_or_symlink_to_raw_evidence_is_protected(tmp_path):
    source = tmp_path / "raw.json"
    original = FIXTURE.read_bytes()
    source.write_bytes(original)
    for name, link in (("hard", "hardlink_to"), ("symbolic", "symlink_to")):
        output = tmp_path / name
        getattr(output.with_suffix(".json"), link)(source)
        result = invoke(source, output, "--overwrite")
        assert result.returncode == 2
        assert "input report" in result.stderr
        assert source.read_bytes() == original
        assert not output.with_suffix(".md").exists()


def test_successful_pair_has_recorded_input_hash_and_no_temporary_files(tmp_path):
    import hashlib

    output = tmp_path / "comparison"
    result = invoke(FIXTURE, output)
    assert result.returncode == 0, result.stderr
    data = json.loads(output.with_suffix(".json").read_text())
    expected = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert data["reference_sha256"] == data["candidate_sha256"] == expected
    assert {p.name for p in tmp_path.iterdir()} == {"comparison.json", "comparison.md"}
