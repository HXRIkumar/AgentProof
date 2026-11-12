"""Credential setup must neither leak nor overwrite local files."""

import importlib.util
import stat
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "configure_openai_key", Path(__file__).parents[1] / "scripts/configure_openai_key.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FAKE_KEY = "sk-test-only-not-a-real-credential"


def test_private_permissions_and_no_overwrite(tmp_path):
    directory = tmp_path / "private"
    MODULE.save_key(FAKE_KEY, directory)
    target = directory / "openai-key"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text() == FAKE_KEY + "\n"
    with pytest.raises(FileExistsError):
        MODULE.save_key(FAKE_KEY + "-replacement", directory)
    assert target.read_text() == FAKE_KEY + "\n"


def test_refuses_symlink_and_nonprivate_directory(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    victim = tmp_path / "other-file"
    victim.write_text("unchanged")
    (directory / "openai-key").symlink_to(victim)
    with pytest.raises(FileExistsError):
        MODULE.save_key(FAKE_KEY, directory)
    assert victim.read_text() == "unchanged"
    directory.chmod(0o755)
    with pytest.raises(ValueError, match="private permissions"):
        MODULE.save_key(FAKE_KEY, directory)


def test_refuses_symlink_directory(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="directory owned"):
        MODULE.save_key(FAKE_KEY, link)
    assert list(real.iterdir()) == []


@pytest.mark.parametrize("key", ["short", "sk-hello\nnot-allowed-here", "sk-" + "x" * 1100])
def test_invalid_input_not_saved_or_exposed(tmp_path, key):
    directory = tmp_path / "private"
    with pytest.raises(ValueError) as caught:
        MODULE.save_key(key, directory)
    assert key not in str(caught.value)
    assert not directory.exists()
