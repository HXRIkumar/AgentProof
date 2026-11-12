#!/usr/bin/env python3
"""Plot completed, hash-pinned observations; never execute a provider or benchmark.

Run: uv run --with matplotlib==3.10.7 python scripts/plot_evidence.py
"""

import argparse
import hashlib
import json
import math
import platform
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from agentproof.comparison import compare_reports, validate_experiment_export
from agentproof.grading import grade
from agentproof.models import Scenario

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "reports/qwen35-4b-live-v1.json": "3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7",
    "reports/qwen35-4b-live-v02.json": "2bc665369b0e943663485a3255cb4ddd5c503ff3997b77559c64d0604a985bad",
    "reports/challenge-v1-before.json": "4350df2a927427b391c077722705107d5680cd1f4997092439363fd5a7e09ea8",
    "reports/challenge-v1-after.json": "df2f8062a6202444bbfbea908bbaff7a7bf6d5c04e892d6507e5e4610771223f",
    "reports/independent-verification-v1.json": "6ce7c8c54e49279fdc1cd6c9cff003a54955282323e85208d96c4ab7f093e797",
    "reports/rules-original-v1/raw.json": "faf4c140bcdf15743ba9eab647a25bb361ee8d2128cd7c39919962c0ed8d5158",
    "reports/rules-original-v1/summary.json": "faecbbad2335e0e01ebfbccd753b3a103237a5c46486c230ed406ee2ffdfac7b",
    "reports/rules-challenge-v1/raw.json": "3aea13e5b4b280f361fe1e6a84ed4ca38db4351f59c29fea77b67a3e0e35de2c",
    "reports/rules-challenge-v1/summary.json": "1a3f3581815ac70ed9493f6d3cf91d3ea08600c3fb44ac5a46178b834cef1724",
}
INK, MUTED, GRID = "#182C3A", "#546575", "#DDE5EC"
OLD, GUARDED, RULES = "#718096", "#087F83", "#A85B14"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_inputs():
    documents = {}
    for name, expected in INPUTS.items():
        path = ROOT / name
        require(digest(path) == expected, f"Pinned evidence changed: {name}")
        documents[name] = json.loads(path.read_bytes())
    return documents


def counts(runs):
    require(bool(runs), "Cannot plot an empty denominator")
    require(
        all(type(run["passed"]) is bool and type(run["safe"]) is bool for run in runs),
        "Grades must be booleans",
    )
    for run in runs:
        for field in ("model_calls", "token_usage"):
            require(type(run[field]) is int and run[field] >= 0, "Invalid usage counter")
        require(
            not (run["model_calls"] > 0 and run["token_usage"] == 0),
            "Unknown token usage cannot support a token-overhead figure",
        )
    return {
        "trials": len(runs),
        "distinct_cases": len({run["scenario_id"] for run in runs}),
        "correct": sum(run["passed"] for run in runs),
        "effect_invariants": sum(run["safe"] for run in runs),
        "model_calls": sum(run["model_calls"] for run in runs),
        "reported_tokens": sum(run["token_usage"] for run in runs),
    }


def select(document, variant="guarded", ids=None):
    return [
        run
        for run in document["runs"]
        if run["variant"] == variant and (ids is None or run["scenario_id"] in ids)
    ]


def rules_counts(documents, suite, reference_name):
    raw_name = f"reports/rules-{suite}-v1/raw.json"
    raw, reference = documents[raw_name], documents[reference_name]
    summary = documents[f"reports/rules-{suite}-v1/summary.json"]
    require(
        raw["status"] == "completed"
        and raw.get("error_type") is None
        and raw["active_case"] is None,
        "Rules study must be complete",
    )
    require(
        raw["reference"] == reference and raw["reference_sha256"] == INPUTS[reference_name],
        "Rules study does not refer to the plotted live export",
    )
    require(
        summary["raw_sha256"] == INPUTS[raw_name]
        and summary["reference_sha256"] == INPUTS[reference_name],
        "Rules summary hash mismatch",
    )
    cases = {case["id"]: Scenario.model_validate(case) for case in reference["scenarios"]}
    ids = {key for key, case in cases.items() if case.fault not in ("malformed", "model_outage")}
    applicability = raw["applicability"]
    require(
        len(applicability) == len(cases)
        and {row["scenario_id"] for row in applicability} == set(cases),
        "Rules applicability must cover every original case exactly once",
    )
    require(
        all(
            type(row["applicable"]) is bool and row["applicable"] == (row["scenario_id"] in ids)
            for row in applicability
        ),
        "Only declared model-specific failures may be excluded",
    )
    repeats = reference["configuration"]["repeats"]
    require(
        raw["repeats"] == repeats and raw["max_proposals"] == 3,
        "Rules budget or repeat count changed",
    )
    runs = raw["rules_runs"]
    require(
        Counter(run["scenario_id"] for run in runs) == dict.fromkeys(ids, repeats)
        and len({run["id"] for run in runs}) == len(runs),
        "Incomplete rules coverage",
    )
    for run in runs:
        case = cases[run["scenario_id"]]
        require(
            run["variant"] == "guarded"
            and run["provider"] == "rules"
            and run["status"] in ("completed", "awaiting_approval")
            and run["parent_run_id"] is None
            and run.get("approval_decision") is None,
            "Rules run is not a completed, original pre-approval trial",
        )
        require(
            run["scenario_hash"] == hashlib.sha256(case.model_dump_json().encode()).hexdigest(),
            "Rules scenario differs from the frozen live input",
        )
        checks = grade(case, run, run["final_state"]["effects"])
        require(
            run["passed"] is all(check["passed"] for check in checks)
            and run["safe"]
            is all(check["passed"] for check in checks if check["name"] != "task_outcome"),
            "Rules regrading mismatch",
        )
        require(run["model_calls"] == run["token_usage"] == 0, "Rules control used inference")
    groups = {"live_guarded": counts(select(reference, ids=ids)), "rules_guarded": counts(runs)}
    for key, values in groups.items():
        require(
            all(summary[key][metric] == value for metric, value in values.items()),
            f"Rules summary differs from raw observations: {key}",
        )
    return {
        **groups,
        "suite_cases": len(cases),
        "excluded_cases": len(cases) - len(ids),
        "repeats": repeats,
        "rules_source_sha256": raw["source_sha256"],
    }


def derive(documents):
    live_names = list(INPUTS)[:5]
    for name in live_names:
        validate_experiment_export(documents[name])
        require(documents[name]["provider"] == "openai", "Expected recorded live evidence")
    require(
        len({documents[name]["configuration"]["model_revision"] for name in live_names}) == 1,
        "The figure assumes one model revision",
    )
    require(
        all(documents[name]["configuration"]["temperature"] == 0 for name in live_names),
        "Figure scope requires temperature-zero runs",
    )
    pairs = {
        "original": (live_names[0], live_names[1]),
        "challenge": (live_names[2], live_names[3]),
    }
    recovery = {}
    for suite, (before_name, after_name) in pairs.items():
        before, after = documents[before_name], documents[after_name]
        compare_reports(before, after)  # Checks exact suite/labels and comparable settings.
        require(
            before["prompt_hash"] == after["prompt_hash"]
            and before["configuration"]["max_proposals"] == 3,
            "Figure scope requires the unchanged initial prompt and three-proposal budget",
        )
        a, b = counts(select(before)), counts(select(after))
        require(a["trials"] == b["trials"], "Before/after denominators differ")
        delta = b["reported_tokens"] - a["reported_tokens"]
        recovery[suite] = {
            "before": a,
            "after": b,
            "repeats": before["configuration"]["repeats"],
            "correct_delta": b["correct"] - a["correct"],
            "reported_token_delta": delta,
            "reported_token_delta_percent": 100 * delta / a["reported_tokens"],
        }
    independent = documents[live_names[4]]
    return {
        "recovery": recovery,
        "independent": {
            "baseline": counts(select(independent, "baseline")),
            "guarded": counts(select(independent)),
            "repeats": independent["configuration"]["repeats"],
        },
        "rules": {suite: rules_counts(documents, suite, pair[1]) for suite, pair in pairs.items()},
        "model": independent["configuration"]["model"],
        "model_revision": independent["configuration"]["model_revision"],
    }


def style():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "text.color": INK,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.spines.bottom": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "svg.fonttype": "none",
            "svg.hashsalt": "agentproof-completed-evidence-v1",
        }
    )


def bar_pair(ax, values, labels, colors, limit, *, denominator=None, token_axis=False):
    ax.barh([1, 0], values, height=0.32, color=colors, zorder=3)
    ax.set_yticks([1, 0], labels)
    ax.tick_params(axis="both", length=0, pad=9)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlim(0, limit * 1.20)
    ax.set_xticks([0, limit / 2, limit])
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    for y, value in zip((1, 0), values, strict=True):
        label = f"{value:,}" if denominator is None else f"{value}/{denominator}"
        ax.text(
            value + limit * 0.025, y, label, va="center", fontsize=13, color=INK, fontweight="bold"
        )
    ax.set_xlabel(
        "Reported tokens" if token_axis else "Correct task outcomes", loc="left", labelpad=8
    )


def recovery_figure(metrics):
    fig = plt.figure(figsize=(12.8, 7.5))
    fig.text(0.055, 0.945, "Measured task recovery and token overhead", fontsize=23, weight="bold")
    fig.text(
        0.055,
        0.902,
        "Guarded workflow · Qwen3.5-4B · unchanged initial prompt and three-proposal budget",
        fontsize=11.5,
        color=MUTED,
    )
    for x, suite, title in (
        (0.12, "original", "Original regression suite"),
        (0.60, "challenge", "Authored challenge suite"),
    ):
        row = metrics["recovery"][suite]
        a, b = row["before"], row["after"]
        fig.text(x - 0.065, 0.826, title, fontsize=15, weight="bold")
        fig.text(
            x - 0.065,
            0.790,
            f"{a['distinct_cases']} cases × {row['repeats']} repeats · "
            f"{row['correct_delta']:+d} correct outcomes",
            color=MUTED,
            fontsize=11,
        )
        upper = fig.add_axes([x, 0.535, 0.31, 0.215])
        bar_pair(
            upper,
            [a["correct"], b["correct"]],
            ["v0.1", "v0.2"],
            [OLD, GUARDED],
            a["trials"],
            denominator=a["trials"],
        )
        upper.set_xlabel("")
        fig.text(x - 0.065, 0.753, "Correct task outcomes", color=MUTED, fontsize=10.5)
        lower = fig.add_axes([x, 0.215, 0.31, 0.215])
        token_limit = math.ceil(max(a["reported_tokens"], b["reported_tokens"]) / 10000) * 10000
        bar_pair(
            lower,
            [a["reported_tokens"], b["reported_tokens"]],
            ["v0.1", "v0.2"],
            [OLD, GUARDED],
            token_limit,
            token_axis=True,
        )
        fig.text(
            x - 0.065,
            0.452,
            f"{row['reported_token_delta']:+,} reported tokens "
            f"({row['reported_token_delta_percent']:+.1f}%)",
            fontsize=12,
            weight="bold",
        )
        fig.text(
            x - 0.065,
            0.127,
            "Defined effect checks: "
            f"{a['effect_invariants']}/{a['trials']} → {b['effect_invariants']}/{b['trials']}",
            color=MUTED,
            fontsize=10.5,
        )
    fig.text(
        0.055,
        0.065,
        "Repeated temperature-zero trials are correlated; these are authored development suites.",
        color=MUTED,
        fontsize=10,
    )
    fig.text(
        0.055,
        0.035,
        "Task success includes valid approval stops. No pooled score, causal isolation or universal safety claim.",
        color=MUTED,
        fontsize=10,
    )
    return fig


def separate_figure(metrics):
    fig = plt.figure(figsize=(13.2, 7.5))
    fig.text(
        0.045,
        0.945,
        "Independent verification and the rules-only control",
        fontsize=22,
        weight="bold",
    )
    fig.text(
        0.045,
        0.902,
        "Separate studies and denominators · recorded outcomes, not a combined accuracy score",
        color=MUTED,
        fontsize=11.5,
    )
    fig.add_artist(plt.Line2D([0.365, 0.365], [0.15, 0.84], transform=fig.transFigure, color=GRID))
    independent = metrics["independent"]
    baseline, guarded = independent["baseline"], independent["guarded"]
    fig.text(0.045, 0.825, "A  Independent verification", fontsize=14, weight="bold")
    fig.text(
        0.045,
        0.784,
        f"{guarded['distinct_cases']} cases × {independent['repeats']} repeats · v0.3",
        color=MUTED,
        fontsize=10.5,
    )
    ax = fig.add_axes([0.115, 0.49, 0.175, 0.245])
    bar_pair(
        ax,
        [baseline["correct"], guarded["correct"]],
        ["Baseline", "Guarded"],
        [OLD, GUARDED],
        guarded["trials"],
        denominator=guarded["trials"],
    )
    fig.text(0.045, 0.39, "Guarded resource use", fontsize=12, weight="bold")
    fig.text(0.045, 0.345, f"{guarded['model_calls']} model HTTP attempts", fontsize=11)
    fig.text(0.045, 0.302, f"{guarded['reported_tokens']:,} reported tokens", fontsize=11)
    fig.text(
        0.045,
        0.259,
        f"{guarded['effect_invariants']}/{guarded['trials']} defined effect checks passed",
        fontsize=11,
    )
    fig.text(
        0.045,
        0.190,
        "Small synthetic verification set;\nnot a broad generalization claim.",
        color=MUTED,
        fontsize=10,
        linespacing=1.5,
    )
    fig.text(0.405, 0.825, "B  Rules-only control · applicable subsets", fontsize=14, weight="bold")
    fig.text(
        0.405,
        0.784,
        "Correct outcomes · guarded runtime · same structured inputs",
        color=MUTED,
        fontsize=10.5,
    )
    for y, suite, title in ((0.55, "original", "Original"), (0.255, "challenge", "Challenge")):
        row = metrics["rules"][suite]
        model, rules = row["live_guarded"], row["rules_guarded"]
        fig.text(
            0.405,
            y + 0.174,
            f"{title}: {rules['distinct_cases']} of {row['suite_cases']} cases "
            f"× {row['repeats']} repeats",
            fontsize=11.5,
            weight="bold",
        )
        ax = fig.add_axes([0.495, y, 0.35, 0.15])
        bar_pair(
            ax,
            [model["correct"], rules["correct"]],
            ["LLM v0.2", "Rules"],
            [GUARDED, RULES],
            rules["trials"],
            denominator=rules["trials"],
        )
        ax.set_xlabel("")
        fig.text(
            0.405,
            y - 0.050,
            "Reported tokens: "
            f"LLM {model['reported_tokens']:,} · rules {rules['reported_tokens']:,}",
            fontsize=10.5,
        )
        fig.text(
            0.405,
            y - 0.084,
            f"Model HTTP attempts: LLM {model['model_calls']} · rules {rules['model_calls']}",
            fontsize=10.5,
            color=MUTED,
        )
    fig.text(
        0.045,
        0.09,
        "Control excludes only injected malformed/model-outage cases. Rules ignore untrusted prose; no model inference.",
        color=MUTED,
        fontsize=10,
    )
    fig.text(
        0.045,
        0.053,
        "Different recorded runs/builds; no latency ratio or causal claim. Repeated cases are correlated and counts are not pooled.",
        color=MUTED,
        fontsize=10,
    )
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    documents = read_inputs()
    metrics = derive(documents)
    directory = ROOT / args.output_dir
    directory.mkdir(parents=True, exist_ok=True)
    style()
    outputs = {}
    for name, figure in (
        ("guarded-recovery", recovery_figure(metrics)),
        ("separate-verification-and-rules", separate_figure(metrics)),
    ):
        for extension in ("svg", "png"):
            path = directory / f"{name}.{extension}"
            metadata = (
                {"Date": None, "Creator": "AgentProof evidence figures"}
                if extension == "svg"
                else {
                    "Software": "AgentProof evidence figures / matplotlib "
                    + matplotlib.__version__,
                }
            )
            figure.savefig(path, dpi=180, metadata=metadata)
            if extension == "svg":
                # Preserve SVG semantics while removing Matplotlib path-line spaces.
                path.write_text(
                    "\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n"
                )
            outputs[path.name] = digest(path)
        plt.close(figure)
    manifest = {
        "format": "agentproof-evidence-figures-v1",
        "generator": {
            "script": "scripts/plot_evidence.py",
            "sha256": digest(Path(__file__)),
            "python": platform.python_version(),
            "matplotlib": matplotlib.__version__,
        },
        "input_sha256": INPUTS,
        "executed_backend_sha256": {
            name: doc["server_metadata"]["backend_source_sha256"]
            for name, doc in documents.items()
            if "server_metadata" in doc
        },
        "metrics": metrics,
        "output_sha256": outputs,
    }
    (directory / "evidence-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {"output_dir": str(directory), "metrics": metrics, "input_files_verified": len(INPUTS)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
