#!/usr/bin/env python3
"""Run paired trials through the real API; retain raw evidence and honest summaries."""

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


def wilson(successes, total):
    if not total:
        return [0.0, 0.0]
    z = 1.96
    p = successes / total
    den = 1 + z * z / total
    mid = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return [round(mid - half, 4), round(mid + half, 4)]


def percentile(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)], 2)


def analyse(experiment):
    result = {}
    for variant in ("baseline", "guarded"):
        runs = [r for r in experiment["runs"] if r["variant"] == variant]
        n = len(runs)
        passed = sum(r["passed"] for r in runs)
        safe = sum(r["safe"] for r in runs)
        result[variant] = {
            "trials": n,
            "distinct_scenarios": len({r["scenario_id"] for r in runs}),
            "passed": passed,
            "safe": safe,
            "completion_rate": passed / n if n else 0,
            "safety_rate": safe / n if n else 0,
            "completion_wilson95_descriptive": wilson(passed, n),
            "safety_wilson95_descriptive": wilson(safe, n),
            "p50_ms": percentile([r["latency_ms"] for r in runs], 0.5),
            "p95_ms": percentile([r["latency_ms"] for r in runs], 0.95),
            "model_calls": sum(r["model_calls"] for r in runs),
            "tokens": sum(r["token_usage"] for r in runs),
            "retries": sum(r["retries"] for r in runs),
            "pending_approvals": sum(r["status"] == "awaiting_approval" for r in runs),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--provider", choices=["scripted", "openai"], default="scripted")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--scenarios", nargs="+")
    parser.add_argument("--suite", type=Path, help="JSON array of custom typed scenarios")
    parser.add_argument("--output", type=Path, default=Path("reports/fixture"))
    parser.add_argument("--require-gate", action="store_true")
    parser.add_argument("--background", action="store_true", help="Submit a durable job and poll progress")
    parser.add_argument("--experiment-id", help="Wait for and export an already submitted experiment")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace existing output files")
    args = parser.parse_args()
    if args.experiment_id and (args.background or args.scenarios or args.suite):
        parser.error("--experiment-id cannot be combined with a new submission")
    outputs = [args.output.with_suffix(suffix) for suffix in (".json", ".summary.json", ".md")]
    if not args.overwrite and any(path.exists() for path in outputs):
        parser.error("Output already exists; choose another --output or explicitly use --overwrite")
    payload = {
        "name": f"{args.provider} benchmark",
        "provider": args.provider,
        "repeats": args.repeats,
    }
    if args.scenarios:
        payload["scenario_ids"] = args.scenarios
    if args.suite:
        if args.scenarios:
            parser.error("--suite and --scenarios are mutually exclusive")
        payload["scenarios"] = json.loads(args.suite.read_text())
    base_url = args.url.rstrip("/")
    if args.experiment_id:
        if not args.experiment_id.isalnum():
            parser.error("Invalid experiment ID")
        with urlopen(base_url + "/api/experiments/" + args.experiment_id, timeout=30) as response:
            experiment = json.load(response)
    else:
        req = Request(
            base_url + "/api/experiments" + ("?background=true" if args.background else ""),
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=30 if args.background else 7200) as response:
            experiment = json.load(response)
    if experiment["status"] in ("queued", "running"):
        print(f"Experiment {experiment['id']} persists on the server; use --experiment-id to reconnect.", file=sys.stderr)
    progress = None
    while experiment["status"] in ("queued", "running"):
        count = experiment["summary"]["total_runs"]
        if count != progress:
            print(f"{experiment['status']}: {count}/{experiment['summary']['expected_runs']} trials", file=sys.stderr)
            progress = count
        time.sleep(1)
        with urlopen(base_url + "/api/experiments/" + experiment["id"], timeout=30) as response:
            experiment = json.load(response)
    if args.experiment_id:
        payload = {"experiment_id": args.experiment_id, "configuration": experiment["configuration"]}
    raw = json.dumps(experiment, indent=2).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_bytes(raw)
    try:
        revision = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"]).strip())
    except subprocess.CalledProcessError:
        revision, dirty = "uncommitted-development", True
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "evidence_kind": "scripted integration test"
        if experiment["provider"] == "scripted"
        else "live model experiment",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_revision": revision,
        "source_revision_scope": "Reporting client checkout at export time; server_metadata.backend_source_sha256 identifies the executed backend source snapshot.",
        "working_tree_dirty": dirty,
        "platform": platform.platform(),
        "requested": payload,
        "metrics": analyse(experiment),
        "gate": experiment["summary"]["gate"],
        "limitations": [
            "Authored regression set; not held out.",
            "Correlated cases; Wilson intervals are descriptive, not calibrated.",
            "Composite guardrail intervention; no causal ablation.",
            "Pending approval is a correct stop, not an executed refund.",
        ],
    }
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "# AgentProof experiment",
        "",
        summary["evidence_kind"],
        "",
        "| Strategy | Correct outcome | Safe | Model calls | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant, m in summary["metrics"].items():
        lines.append(
            f"| {variant} | {m['passed']}/{m['trials']} | {m['safe']}/{m['trials']} | {m['model_calls']} | {m['p50_ms']} | {m['p95_ms']} |"
        )
    lines += [
        "",
        "## Scope",
        "",
        *["- " + item for item in summary["limitations"]],
        "",
        "Gate: " + json.dumps(summary["gate"]),
        "",
        "Raw evidence SHA-256: `" + summary["raw_sha256"] + "`",
        "",
    ]
    args.output.with_suffix(".md").write_text("\n".join(lines))
    print(json.dumps(summary, indent=2))
    if args.require_gate and not summary["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
