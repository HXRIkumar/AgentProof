#!/usr/bin/env python3
"""Compare raw benchmark exports; nonzero exit on incompatible evidence or a failed gate."""

import argparse
import hashlib
import json
from pathlib import Path

from agentproof.comparison import ComparisonError, compare_reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-rate", type=float, default=.9)
    args = parser.parse_args()
    try:
        old, new = args.reference.read_bytes(), args.candidate.read_bytes()
        report = compare_reports(json.loads(old), json.loads(new), args.minimum_rate)
    except (OSError, ValueError, ComparisonError) as exc:
        parser.exit(2, f"Comparison refused: {exc}\n")
    report["reference_sha256"] = hashlib.sha256(old).hexdigest()
    report["candidate_sha256"] = hashlib.sha256(new).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
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
    args.output.with_suffix(".md").write_text("\n".join(lines))
    print(json.dumps({"gate": report["gate"], "variants": report["variants"]}, indent=2))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
