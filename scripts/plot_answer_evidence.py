#!/usr/bin/env python3
"""Render completed, matching answer studies without invoking any model.

Use a Python environment with matplotlib==3.10.8. Development inputs receive an
explicit development label. Output goes to a new directory; evidence stays unchanged.
"""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from agentproof.answer_eval import summarize_report

COLORS = {"baseline": "#aab7c7", "validated": "#5b7b9d", "adaptive": "#214fb4"}
LABELS = {"baseline": "Direct", "validated": "Validation + correction", "adaptive": "Critic + correction"}
INK = "#1b2939"


def load_reports(arguments):
    records = []
    identity = None
    for argument in arguments:
        label, separator, value = argument.partition("=")
        if not separator or not label.strip():
            raise ValueError("Use --report 'Label=/path/to/raw.json'")
        path = Path(value)
        raw = path.read_bytes()
        report = json.loads(raw)
        summary = summarize_report(report)
        if not summary["complete"] or report.get("source_unchanged") is not True:
            raise ValueError("Only complete studies with unchanged source may be plotted")
        current = (report["suite"]["sha256"], tuple(sorted(report["suite"]["case_ids"])))
        if identity is not None and current != identity:
            raise ValueError("Figures require identical frozen suites and case coverage")
        identity = current
        records.append({"label": label, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                        "summary": summary, "split": report["suite"]["split"],
                        "cases": report["suite"]["case_count"]})
    return records


def style(axis):
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#ccd5df")
    axis.tick_params(colors=INK, length=0, pad=8)
    axis.grid(axis="y", color="#e8edf2", linewidth=0.7)
    axis.set_axisbelow(True)


def save(figure, directory, name):
    figure.savefig(directory / (name + ".png"), dpi=180, facecolor="white")
    figure.savefig(directory / (name + ".svg"), facecolor="white", metadata={"Date": None})
    plt.close(figure)


def plot(records, directory):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "text.color": INK, "axes.labelcolor": INK, "svg.hashsalt": "agentproof-answer-v05"})
    split = records[0]["split"]
    count = records[0]["cases"]
    scope = (f"Development split · {count} cases · not held-out evidence" if split == "development"
             else f"Frozen evaluation split · {count} unique cases · shared first response within each policy comparison")
    figure, axis = plt.subplots(figsize=(11.5, 6.5))
    figure.subplots_adjust(left=.08, right=.98, top=.78, bottom=.22)
    figure.text(.08, .94, "Answer quality, measured against references", fontsize=19, weight="bold")
    figure.text(.08, .89, scope, color="#586b80", fontsize=10)
    positions = list(range(len(records)))
    for index, strategy in enumerate(("baseline", "validated", "adaptive")):
        offsets = [position + (index - 1) * .24 for position in positions]
        metrics = [item["summary"]["strategies"][strategy] for item in records]
        values = [item["success_rate"] * 100 for item in metrics]
        bars = axis.bar(offsets, values, .21, color=COLORS[strategy], label=LABELS[strategy])
        for bar, metric in zip(bars, metrics, strict=True):
            axis.text(bar.get_x() + bar.get_width()/2, bar.get_height()+1.3,
                      f"{metric['correct']}/{metric['trials']}", ha="center", va="bottom", fontsize=9)
    axis.set_xticks(positions, [item["label"] for item in records])
    axis.set_ylabel("Reference-correct and delivered (%)")
    axis.set_ylim(0, 110)
    axis.set_yticks([0, 25, 50, 75, 100])
    axis.legend(loc="upper left", bbox_to_anchor=(0, 1.19), ncol=3, frameon=False)
    style(axis)
    figure.text(.08, .10, "Strict QA exact match or typed extraction match; all failures retained. Each label shows its numerator and denominator.", fontsize=9, color="#586b80")
    figure.text(.08, .065, "These configurations measure a deployment tradeoff; results do not establish general model accuracy.", fontsize=9, color="#586b80")
    save(figure, directory, "answer-quality")

    figure, axes = plt.subplots(1, 2, figsize=(11.5, 5.7))
    figure.subplots_adjust(left=.20, right=.97, top=.75, bottom=.21, wspace=.60)
    figure.text(.08, .94, "Correction gains and their time cost", fontsize=19, weight="bold")
    figure.text(.08, .89, scope, color="#586b80", fontsize=10)
    comparisons = [next(x for x in item["summary"]["comparisons"] if x["candidate"] == "adaptive") for item in records]
    for index, comparison in enumerate(comparisons):
        delta = comparison["success_delta"] * 100
        low, high = [x * 100 for x in comparison["success_delta_ci95"]]
        axes[0].errorbar(delta, index, xerr=[[max(0, delta-low)], [max(0, high-delta)]],
                         fmt="o", color=COLORS["adaptive"], ecolor="#7794bf", capsize=5, markersize=7)
    axes[0].axvline(0, color="#8393a5", linewidth=1, linestyle="--")
    axes[0].set_yticks(positions, [item["label"] for item in records])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Adaptive − direct success (percentage points)")
    axes[0].set_title("Paired 95% bootstrap intervals", loc="left", fontsize=11, pad=15)
    style(axes[0])
    for strategy, marker in (("baseline", "o"), ("adaptive", "s")):
        values = [item["summary"]["strategies"][strategy]["latency_p50_ms"]/1000 for item in records]
        axes[1].scatter(values, positions, color=COLORS[strategy], marker=marker, s=45, label=LABELS[strategy])
    axes[1].set_yticks(positions, ["" for _ in records])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Median end-to-end seconds")
    axes[1].set_xlim(left=0)
    axes[1].legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, fontsize=9)
    style(axes[1])
    figure.text(.08, .09, "Intervals resample paired cases (2,000 draws). Latency reflects this Mac and network; it is not a hardware-isolated ranking.", fontsize=9, color="#586b80")
    save(figure, directory, "answer-tradeoffs")

    paid = [(item["label"].replace("\n", " "), strategy, metrics)
            for item in records for strategy, metrics in item["summary"]["strategies"].items()
            if metrics.get("cost_known") is True and metrics.get("cost_per_correct_usd") is not None
            and metrics.get("paid_calls", 0) > 0]
    if paid:
        figure, axis = plt.subplots(figsize=(11.5, max(5.7, 2.7 + len(paid) * .52)))
        figure.subplots_adjust(left=.35, right=.86, top=.75, bottom=.23)
        figure.text(.08, .94, "API spend per successful task", fontsize=19, weight="bold")
        figure.text(.08, .89, scope, color="#586b80", fontsize=10)
        positions = list(range(len(paid)))
        values = [metrics["cost_per_correct_usd"] for _, _, metrics in paid]
        axis.barh(positions, values, height=.5, color=[COLORS[strategy] for _, strategy, _ in paid])
        axis.set_yticks(positions, [f"{label}\n{LABELS[strategy]}" for label, strategy, _ in paid])
        axis.invert_yaxis()
        axis.set_xlabel("Estimated policy API dollars / reference-correct delivered task")
        axis.set_xlim(0, max(values) * 1.18 if max(values) else .001)
        axis.xaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value:.3f}"))
        for position, (_, _, metrics) in enumerate(paid):
            axis.text(metrics["cost_per_correct_usd"] + max(values) * .02, position,
                      f"${metrics['cost_per_correct_usd']:.4f}", va="center", fontsize=9)
            axis.text(1.09, position, f"{metrics['correct']}/{metrics['trials']}",
                      transform=axis.get_yaxis_transform(), va="center", ha="center", fontsize=9)
        axis.text(1.09, 1.04, "Tasks\nsucceeded", transform=axis.transAxes, ha="center", fontsize=9)
        style(axis)
        axis.grid(axis="y", visible=False)
        axis.grid(axis="x", color="#e8edf2", linewidth=.7)
        figure.text(.08, .11, "Paid policies only. Local computation, electricity and hardware are excluded; these are token-price estimates, not invoices.", fontsize=9, color="#586b80")
        figure.text(.08, .065, "Each policy includes its initial call. Actual study spending counts shared initial calls once and is recorded separately.", fontsize=9, color="#586b80")
        save(figure, directory, "answer-api-cost")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.report) <= 6:
        parser.error("Provide 1–6 completed matching studies")
    records = load_reports(args.report)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    plot(records, args.output_dir)
    (args.output_dir / "provenance.json").write_text(json.dumps({
        "matplotlib_version": matplotlib.__version__, "inputs": records,
        "model_calls": 0, "source_data_modified": False,
    }, indent=2) + "\n")
    print(f"Saved measured figures to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
