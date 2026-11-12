#!/usr/bin/env python3
"""Compare raw benchmark exports; nonzero exit on incompatible evidence or a failed gate."""

import argparse
import hashlib
import json
import math
import os
import stat
import uuid
from contextlib import ExitStack
from pathlib import Path

from agentproof.comparison import ComparisonError, compare_reports


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ComparisonError("Comparison input contains duplicate JSON keys")
        result[key] = value
    return result


def invalid_constant(_value):
    raise ComparisonError("Comparison input contains a non-finite JSON number")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        invalid_constant(value)
    return number


def decode_report(raw):
    return json.loads(
        raw, object_pairs_hook=unique_object,
        parse_constant=invalid_constant, parse_float=finite_float,
    )


def output_paths(prefix, inputs, *, overwrite):
    paths = [prefix.with_suffix(extension) for extension in (".json", ".md")]
    for path in paths:
        for source in inputs:
            if path.resolve() == source.resolve() or (
                path.exists() and source.exists() and path.samefile(source)
            ):
                raise ValueError("Comparison output must not replace an input report")
        if path.is_symlink():
            raise ValueError("Comparison output must not replace a symbolic link")
        if path.exists() and not overwrite:
            raise ValueError("Comparison output already exists; choose a new path or --overwrite")
    return paths


def file_identity(metadata):
    return metadata.st_dev, metadata.st_ino


def check_destination(directory_fd, name, input_identities, *, overwrite):
    try:
        destination = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if file_identity(destination) in input_identities:
        raise ValueError("Comparison output must not replace an input report")
    if stat.S_ISLNK(destination.st_mode):
        raise ValueError("Comparison output must not replace a symbolic link")
    if not overwrite:
        raise ValueError("Comparison output already exists; choose a new path or --overwrite")
    if not stat.S_ISREG(destination.st_mode):
        raise ValueError("Comparison output must be a regular file")


def publish(directory_fd, name, contents, *, overwrite, input_identities):
    """Publish through a pinned POSIX directory, never a re-resolved parent path."""
    temporary = ".agentproof-compare-" + uuid.uuid4().hex + ".tmp"
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd
    )
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        check_destination(directory_fd, name, input_identities, overwrite=overwrite)
        if overwrite:
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        else:
            os.link(
                temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-rate", type=float, default=.9)
    parser.add_argument("--overwrite", action="store_true", help="Replace derived outputs, never inputs")
    args = parser.parse_args()
    with ExitStack() as stack:
        return execute(args, parser, stack)


def execute(args, parser, stack):
    try:
        paths = output_paths(args.output, (args.reference, args.candidate), overwrite=args.overwrite)
        sources = [stack.enter_context(path.open("rb")) for path in (args.reference, args.candidate)]
        input_identities = {file_identity(os.fstat(source.fileno())) for source in sources}
        old, new = (source.read() for source in sources)
        report = compare_reports(decode_report(old), decode_report(new), args.minimum_rate)
    except (OSError, ValueError, ComparisonError) as exc:
        parser.exit(2, f"Comparison refused: {exc}\n")
    report["reference_sha256"] = hashlib.sha256(old).hexdigest()
    report["candidate_sha256"] = hashlib.sha256(new).hexdigest()
    lines = ["# Release comparison", "", "| Strategy | Before | After | Tokens before / after | p95 ms before / after |", "|---|---:|---:|---:|---:|"]
    for name, row in report["variants"].items():
        a, b = row["before"], row["after"]
        lines.append(f"| {name} | {a['correct']}/{a['trials']} | {b['correct']}/{b['trials']} | {a['tokens']} / {b['tokens']} | {a['p95_ms']:.1f} / {b['p95_ms']:.1f} |")
    lines += ["", "## Changed cases", "", "| Case | Strategy | Correct before / after |", "|---|---|---:|"]
    for row in report["case_changes"]:
        if row["correct_delta"] or row["safe_delta"]:
            lines.append(f"| {row['scenario_id']} | {row['variant']} | {row['before_correct']} / {row['after_correct']} |")
    lines += ["", "Gate: " + ("PASS" if report["gate"]["passed"] else "FAIL"), ""]
    lines += ["- " + reason for reason in report["gate"]["reasons"]]
    lines += ["", "## Limits", ""] + ["- " + item for item in report["limitations"]]
    lines += ["", f"Reference SHA-256: `{report['reference_sha256']}`", f"Candidate SHA-256: `{report['candidate_sha256']}`", ""]
    try:
        if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
            raise ValueError("Safe comparison publication requires POSIX directory handles (macOS/Linux)")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output_paths(args.output, (args.reference, args.candidate), overwrite=args.overwrite)
        directory_fd = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, directory_fd)
        # These checks use the actually opened input files and pinned destination
        # directory. Replacing a parent path later cannot redirect the writes.
        for path in paths:
            check_destination(directory_fd, path.name, input_identities, overwrite=args.overwrite)
        for path, contents in zip(paths, (json.dumps(report, indent=2) + "\n", "\n".join(lines))):
            publish(
                directory_fd, path.name, contents, overwrite=args.overwrite,
                input_identities=input_identities,
            )
        if file_identity(args.output.parent.stat()) != file_identity(os.fstat(directory_fd)):
            raise ValueError("Output directory changed; outputs remain in the originally opened directory")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Comparison output refused: {exc}\n")
    print(json.dumps({"gate": report["gate"], "variants": report["variants"]}, indent=2))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
