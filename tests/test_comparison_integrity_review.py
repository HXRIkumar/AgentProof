"""Independent raw-evidence and publication-window review; temporary files only."""

import importlib.util
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from agentproof.comparison import ComparisonError, compare_reports

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_document():
    return json.loads((ROOT / "reports/fixture-v1.json").read_bytes())


@pytest.fixture
def command():
    spec = importlib.util.spec_from_file_location(
        "comparison_independent_review", ROOT / "scripts/compare.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path, fixture_document):
    raw = tmp_path / "raw"
    derived = tmp_path / "derived"
    raw.mkdir()
    derived.mkdir()
    original = json.dumps(fixture_document).encode()
    reference = raw / "reference.json"
    candidate = raw / "candidate.json"
    reference.write_bytes(original)
    candidate.write_bytes(original)
    return reference, candidate, derived, original


def configure(monkeypatch, inputs, *, overwrite=False):
    reference, candidate, derived, _ = inputs
    argv = ["compare.py", str(reference), str(candidate), "--output", str(derived / "reference")]
    if overwrite:
        argv.append("--overwrite")
    monkeypatch.setattr(sys, "argv", argv)


@pytest.mark.parametrize("metric", ["latency_ms", "model_calls", "token_usage", "retries"])
def test_unrepresentably_large_metric_is_a_clean_evidence_refusal(fixture_document, metric):
    fixture_document["runs"][0][metric] = 10**400
    with pytest.raises(ComparisonError, match="Invalid run metric"):
        compare_reports(fixture_document, deepcopy(fixture_document))


@pytest.mark.parametrize("overwrite", [False, True])
def test_parent_swap_before_directory_open_cannot_replace_input(
    command, inputs, monkeypatch, tmp_path, capsys, overwrite
):
    reference, candidate, derived, original = inputs
    configure(monkeypatch, inputs, overwrite=overwrite)
    real_open = os.open
    saved_directory = tmp_path / "original-derived"
    swapped = False

    def swap_before_pin(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and flags & os.O_DIRECTORY:
            assert Path(path) == derived
            swapped = True
            derived.rename(saved_directory)
            derived.symlink_to(reference.parent, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(command.os, "open", swap_before_pin)
    with pytest.raises(SystemExit) as exc:
        command.main()
    assert exc.value.code == 2
    assert swapped
    assert "input report" in capsys.readouterr().err
    assert reference.read_bytes() == candidate.read_bytes() == original
    assert list(saved_directory.iterdir()) == []
    assert {p.name for p in reference.parent.iterdir()} == {"reference.json", "candidate.json"}


def test_second_publication_failure_keeps_first_complete_and_preserves_other_writer(
    command, inputs, monkeypatch, capsys
):
    reference, candidate, derived, original = inputs
    configure(monkeypatch, inputs)
    real_publish = command.publish
    calls = []

    def concurrent_markdown(directory_fd, name, contents, **kwargs):
        calls.append(name)
        if name.endswith(".md"):
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write("Other writer's Markdown\n")
        return real_publish(directory_fd, name, contents, **kwargs)

    monkeypatch.setattr(command, "publish", concurrent_markdown)
    with pytest.raises(SystemExit) as exc:
        command.main()
    assert exc.value.code == 2
    assert "output already exists" in capsys.readouterr().err
    assert calls == ["reference.json", "reference.md"]
    assert json.loads((derived / "reference.json").read_bytes())["gate"]["passed"]
    assert (derived / "reference.md").read_text() == "Other writer's Markdown\n"
    assert {p.name for p in derived.iterdir()} == {"reference.json", "reference.md"}
    assert reference.read_bytes() == candidate.read_bytes() == original


@pytest.mark.parametrize("ambiguity", ["budget", "counter", "NaN", "Infinity", "1e400"])
def test_cli_rejects_ambiguous_or_nonfinite_raw_json_before_publication(
    command, inputs, monkeypatch, capsys, ambiguity
):
    reference, candidate, derived, original = inputs
    configure(monkeypatch, inputs)
    text = original.decode()
    if ambiguity == "budget":
        malformed = text.replace(
            '"max_proposals": 3', '"max_proposals": 1, "max_proposals": 3', 1
        )
    elif ambiguity == "counter":
        malformed = text.replace('"token_usage": 0', '"token_usage": -1, "token_usage": 0', 1)
    else:
        # Metadata is not used for grading, but must still be unambiguous valid JSON.
        malformed = '{"review_metadata": {"value": ' + ambiguity + '},' + text[1:]
    assert malformed != text
    reference.write_text(malformed)
    candidate.write_text(malformed)
    before = reference.read_bytes()
    with pytest.raises(SystemExit) as exc:
        command.main()
    assert exc.value.code == 2
    assert "Comparison refused" in capsys.readouterr().err
    assert reference.read_bytes() == candidate.read_bytes() == before
    assert list(derived.iterdir()) == []
