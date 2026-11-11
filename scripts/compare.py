#!/usr/bin/env python3
"""Compare raw benchmark exports; nonzero exit on incompatible evidence or a failed gate."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from agentproof.comparison import ComparisonError, compare_reports


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


def publish(path, contents, *, overwrite):
    """Publish a complete file; default mode cannot clobber a concurrent writer."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-rate", type=float, default=.9)
    parser.add_argument("--overwrite", action="store_true", help="Replace derived outputs, never inputs")
    args = parser.parse_args()
    try:
        paths = output_paths(args.output, (args.reference, args.candidate), overwrite=args.overwrite)
        old, new = args.reference.read_bytes(), args.candidate.read_bytes()
        report = compare_reports(json.loads(old), json.loads(new), args.minimum_rate)
    except (OSError, ValueError, ComparisonError) as exc:
        parser.exit(2, f"Comparison refused: {exc}\n")
    report["reference_sha256"] = hashlib.sha256(old).hexdigest()
    report["candidate_sha256"] = hashlib.sha256(new).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
        # Recheck input aliases immediately before publishing. --overwrite applies
        # only to derived reports, never the raw evidence used in this invocation.
        output_paths(args.output, (args.reference, args.candidate), overwrite=args.overwrite)
        publish(paths[0], json.dumps(report, indent=2) + "\n", overwrite=args.overwrite)
        publish(paths[1], "\n".join(lines), overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Comparison output refused: {exc}\n")
    print(json.dumps({"gate": report["gate"], "variants": report["variants"]}, indent=2))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
