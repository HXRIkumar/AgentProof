#!/usr/bin/env python3
"""Run or inspect the guarded A1/A3 proposal-budget study; no paid endpoints."""

import argparse
import json
import signal
from pathlib import Path

from agentproof.ablation import AblationError, run_ablation, write_analysis


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Start a new study in a new output directory")
    run.add_argument("--provider", choices=("scripted", "openai"), default="scripted")
    run.add_argument("--seed", type=int, default=20261112)
    run.add_argument("--output-dir", type=Path, required=True)
    analyse = commands.add_parser("analyse", help="Validate and summarize a raw checkpoint")
    analyse.add_argument("raw", type=Path)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.command == "run":
            document = run_ablation(args.output_dir, provider=args.provider, seed=args.seed)
            raw = args.output_dir / "raw.json"
        else:
            raw = args.raw
            document = json.loads(raw.read_text())
        report = write_analysis(raw)
    except (OSError, ValueError, AblationError) as exc:
        parser.exit(2, f"Ablation refused: {exc}\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "finished_trials": report["finished_trials"],
                "planned_trials": report["planned_trials"],
                "adoption": report["adoption"],
                "raw": str(raw.resolve()),
            },
            indent=2,
        )
    )
    return 130 if document["status"] == "interrupted" else 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
