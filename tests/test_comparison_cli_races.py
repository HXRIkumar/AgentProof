"""Deterministic publication races use temporary copies, never historical evidence."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def comparison_command():
    spec = importlib.util.spec_from_file_location("comparison_cli_review", ROOT / "scripts/compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paths(tmp_path):
    raw = tmp_path / "raw"
    derived = tmp_path / "derived"
    raw.mkdir()
    derived.mkdir()
    original = (ROOT / "reports/fixture-v1.json").read_bytes()
    reference = raw / "reference.json"
    candidate = raw / "candidate.json"
    reference.write_bytes(original)
    candidate.write_bytes(original)
    return reference, candidate, derived, original


def configure(monkeypatch, paths, *, overwrite):
    reference, candidate, derived, _ = paths
    arguments = ["compare.py", str(reference), str(candidate), "--output", str(derived / "reference")]
    if overwrite:
        arguments.append("--overwrite")
    monkeypatch.setattr(sys, "argv", arguments)


@pytest.mark.parametrize("overwrite", [False, True])
def test_parent_directory_swap_cannot_redirect_publication(
    comparison_command, paths, monkeypatch, tmp_path, overwrite, capsys
):
    reference, candidate, derived, original = paths
    configure(monkeypatch, paths, overwrite=overwrite)
    real_publish = comparison_command.publish
    pinned = tmp_path / "original-derived-directory"
    swapped = False

    def swap_parent_then_publish(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            derived.rename(pinned)
            derived.symlink_to(reference.parent, target_is_directory=True)
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(comparison_command, "publish", swap_parent_then_publish)
    with pytest.raises(SystemExit) as exc:
        comparison_command.main()
    assert exc.value.code == 2
    assert "Output directory changed" in capsys.readouterr().err
    assert reference.read_bytes() == candidate.read_bytes() == original
    assert not reference.with_suffix(".md").exists()
    assert json.loads((pinned / "reference.json").read_text())["gate"]["passed"]
    assert (pinned / "reference.md").read_text().startswith("# Release comparison")
    assert {path.name for path in pinned.iterdir()} == {"reference.json", "reference.md"}


def test_publication_checks_actual_open_input_identity_after_source_path_changes(
    comparison_command, paths, monkeypatch, capsys
):
    reference, candidate, derived, original = paths
    configure(monkeypatch, paths, overwrite=True)
    real_publish = comparison_command.publish
    saved_input = reference.with_name("original-open-input.json")

    def replace_source_name_then_publish(*args, **kwargs):
        reference.rename(saved_input)
        reference.write_bytes(original)  # Same bytes, different inode from the opened source.
        (derived / "reference.json").hardlink_to(saved_input)
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(comparison_command, "publish", replace_source_name_then_publish)
    with pytest.raises(SystemExit) as exc:
        comparison_command.main()
    assert exc.value.code == 2
    assert "input report" in capsys.readouterr().err
    assert saved_input.read_bytes() == reference.read_bytes() == candidate.read_bytes() == original
    assert (derived / "reference.json").read_bytes() == original
    assert not (derived / "reference.md").exists()
    assert {path.name for path in derived.iterdir()} == {"reference.json"}


def test_default_publish_cannot_clobber_a_writer_after_destination_validation(
    comparison_command, paths, monkeypatch, capsys
):
    reference, candidate, derived, original = paths
    configure(monkeypatch, paths, overwrite=False)
    real_link = os.link

    def concurrent_destination(source, target, **kwargs):
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
            dir_fd=kwargs["dst_dir_fd"],
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write("Concurrent writer\n")
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(comparison_command.os, "link", concurrent_destination)
    with pytest.raises(SystemExit) as exc:
        comparison_command.main()
    assert exc.value.code == 2
    assert "output refused" in capsys.readouterr().err
    assert (derived / "reference.json").read_text() == "Concurrent writer\n"
    assert reference.read_bytes() == candidate.read_bytes() == original
    assert not (derived / "reference.md").exists()
    assert {path.name for path in derived.iterdir()} == {"reference.json"}
