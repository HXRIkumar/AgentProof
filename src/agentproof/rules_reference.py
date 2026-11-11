"""A separately labelled deterministic policy control for completed live exports."""

import hashlib
import json
import math
import os
import platform
import tempfile
from pathlib import Path

from .comparison import ComparisonError, _validated_report
from .engine import Engine, now
from .models import Scenario
from .store import Store

EXCLUDED_FAULTS = {
    "model_outage": "Injected model unavailability is inapplicable to a rules function.",
    "malformed": "Injected malformed model output is inapplicable to a typed rules function.",
}


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def _write(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def metrics(runs):
    latencies = sorted(run["latency_ms"] for run in runs)
    return {
        "trials": len(runs),
        "distinct_cases": len({run["scenario_id"] for run in runs}),
        "correct": sum(run["passed"] for run in runs),
        "effect_invariants": sum(run["safe"] for run in runs),
        "model_calls": sum(run["model_calls"] for run in runs),
        "reported_tokens": sum(run["token_usage"] for run in runs),
        "pending_approvals": sum(run["status"] == "awaiting_approval" for run in runs),
        "p50_ms": latencies[math.ceil(len(runs) * .50) - 1] if runs else None,
        "p95_ms": latencies[math.ceil(len(runs) * .95) - 1] if runs else None,
    }


def run_reference(reference_path, output_dir):
    original = Path(reference_path).read_bytes()
    reference = json.loads(original)
    validated = _validated_report(reference)
    if reference["provider"] != "openai":
        raise ComparisonError("The rules control requires a completed live-model export")
    if reference["configuration"]["max_proposals"] != 3:
        raise ComparisonError("The rules control preserves the default three-proposal budget")
    applicability = [
        {
            "scenario_id": case["id"],
            "applicable": case["fault"] not in EXCLUDED_FAULTS,
            "reason": EXCLUDED_FAULTS.get(case["fault"], "Same observed task and tool boundaries."),
        }
        for case in validated["suite"]
    ]
    included_ids = {row["scenario_id"] for row in applicability if row["applicable"]}
    if not included_ids:
        raise ComparisonError("No applicable cases remain; no comparison can be made")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    document = {
        "format": "agentproof-rules-reference-v1",
        "kind": "rules-only policy control; not model inference or a release gate",
        "created_at": now(),
        "status": "running",
        "source_sha256": source_fingerprint(),
        "platform": platform.platform(),
        "reference_sha256": hashlib.sha256(original).hexdigest(),
        "reference": reference,
        "applicability": applicability,
        "repeats": reference["configuration"]["repeats"],
        "max_proposals": 3,
        "rules_runs": [],
        "active_case": None,
    }
    checkpoint = directory / "raw.json"
    _write(checkpoint, document)
    engine = Engine(Store(directory / "ledger.sqlite3"))
    try:
        for case in validated["suite"]:
            if case["id"] not in included_ids:
                continue
            for repeat in range(document["repeats"]):
                if source_fingerprint() != document["source_sha256"]:
                    raise RuntimeError("Source changed during rules control")
                document["active_case"] = {"scenario_id": case["id"], "repeat": repeat + 1}
                _write(checkpoint, document)
                result = engine.run(Scenario.model_validate(case), "guarded", "rules")
                document["rules_runs"].append(result)
                document["active_case"] = None
                _write(checkpoint, document)
        if source_fingerprint() != document["source_sha256"]:
            raise RuntimeError("Source changed during rules control")
        document["status"] = "completed"
    except BaseException as exc:
        document["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        document["error_type"] = type(exc).__name__
        raise
    finally:
        document["finished_at"] = now()
        _write(checkpoint, document)
    live = [
        run for run in reference["runs"]
        if run["variant"] == "guarded" and run["scenario_id"] in included_ids
    ]
    rules = document["rules_runs"]
    summary = {
        "kind": document["kind"],
        "reference_sha256": document["reference_sha256"],
        "raw_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "status": document["status"],
        "suite_cases": len(validated["suite"]),
        "applicable_cases": len(included_ids),
        "excluded_cases": len(validated["suite"]) - len(included_ids),
        "applicability": applicability,
        "live_guarded": metrics(live),
        "rules_guarded": metrics(rules),
        "case_results": [
            {
                "scenario_id": case_id,
                "live_correct": sum(r["passed"] for r in live if r["scenario_id"] == case_id),
                "rules_correct": sum(r["passed"] for r in rules if r["scenario_id"] == case_id),
                "trials_each": document["repeats"],
            }
            for case_id in sorted(included_ids)
        ],
        "limitations": [
            "This structured refund policy can be decided without an LLM.",
            "Rules and earlier live trials are different runs with separately recorded source hashes.",
            "Latency is descriptive across nonconcurrent runs, not a controlled speedup experiment.",
            "Model-specific fault exclusions are declared per case; no expected label was changed.",
            "Both use the guarded runtime, including synthetic tool faults and approval boundaries.",
            "The rules provider ignores notes; it cannot interpret unstructured requests.",
            "Repeated deterministic cases are correlated; no general model-quality claim is made.",
        ],
    }
    _write(directory / "summary.json", summary)
    lines = [
        "# Rules-only policy reference", "", document["kind"], "",
        (f"Applicable: {len(included_ids)}/{len(validated['suite'])} distinct cases. "
         f"Repeats: {document['repeats']} per case, with identical labels and inputs."), "",
        "| Method | Correct | Effect invariants | Model HTTP calls | Reported tokens | p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("live_guarded", "rules_guarded"):
        m = summary[name]
        lines.append(
            f"| {name} | {m['correct']}/{m['trials']} | {m['effect_invariants']}/{m['trials']} | "
            f"{m['model_calls']} | {m['reported_tokens']} | {m['p95_ms']} |"
        )
    lines += ["", "## Declared exclusions", ""]
    lines += [f"- {row['scenario_id']}: {row['reason']}" for row in applicability if not row["applicable"]]
    lines += ["", "## Every applicable case", "", "| Case | Live correct | Rules correct | Trials each |", "|---|---:|---:|---:|"]
    lines += [
        f"| {r['scenario_id']} | {r['live_correct']} | {r['rules_correct']} | {r['trials_each']} |"
        for r in summary["case_results"]
    ]
    lines += ["", "## Interpretation", ""] + ["- " + item for item in summary["limitations"]]
    lines += ["", f"Raw SHA-256: `{summary['raw_sha256']}`", ""]
    (directory / "report.md").write_text("\n".join(lines))
    return summary
