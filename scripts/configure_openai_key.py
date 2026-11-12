#!/usr/bin/env python3
"""Save a key through a hidden local prompt; never validate it over the network."""

import getpass
import os
import stat
import sys
import warnings
from pathlib import Path


def save_key(key: str, directory: Path) -> None:
    key = key.strip()
    if not key.startswith("sk-") or not 20 <= len(key) <= 1024 or any(c.isspace() for c in key):
        raise ValueError("That does not look like an API key. Nothing was saved.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_info = directory.lstat()
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != os.getuid():
        raise ValueError("The configuration directory must be a directory owned by you.")
    if stat.S_IMODE(directory_info.st_mode) & 0o077:
        raise ValueError("The configuration directory must have private permissions (700).")
    target = directory / "openai-key"
    # Exclusive creation refuses existing credentials and symlinks; never clobber a key.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(key + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main() -> int:
    if not sys.stdin.isatty():
        print("Run this command in your own Terminal. Piped input is not accepted.")
        return 1
    directory = Path.home() / ".config" / "agentproof"
    print("AgentProof local API-key setup. No network requests or charges.")
    print("Paste the key at the hidden prompt, then press Return. No characters will appear.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("OpenAI API key (hidden): ")
        save_key(key, directory)
    except FileExistsError:
        print("An existing key was found and was left unchanged. Setup stopped.")
        return 1
    except (ValueError, OSError, getpass.GetPassWarning) as exc:
        # Never echo input or arbitrary OS exception text.
        print(str(exc) if isinstance(exc, ValueError) else "Could not save the key securely.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. No key was saved.")
        return 1
    print("Key saved privately outside the repository (owner read/write only).")
    print("No API request was made. You can now tell Codex: Key configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
