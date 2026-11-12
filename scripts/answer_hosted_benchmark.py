#!/usr/bin/env python3
"""Explicitly opt in to a budgeted efficient-model study; never used by local tests."""

from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path
from urllib.parse import urlsplit

from answer_benchmark import interrupt, run_benchmark, save_json

from agentproof.answers import AnswerService

MODEL = "gpt-5.4-mini-2026-03-17"
ENDPOINT = "https://api.openai.com/v1"


def route_environment(mode: str, environment: dict) -> dict:
    """No credential values enter the route configuration or report."""
    if mode not in {"hybrid", "hosted"}:
        raise ValueError("Choose hybrid or hosted mode")
    selected = {
        "ANSWER_LAB_ENABLE_PAID": "1",
        "ANSWER_LAB_OPENAI_REASONING_EFFORT": "low",
        "ANSWER_LAB_CRITIC_BASE_URL": ENDPOINT,
        "ANSWER_LAB_CRITIC_MODEL": MODEL,
        "ANSWER_LAB_CRITIC_MODEL_REVISION": MODEL,
        "ANSWER_LAB_CRITIC_MAX_TOKENS": "1536",
    }
    if mode == "hosted":
        selected.update({
            "ANSWER_LAB_BASE_URL": ENDPOINT,
            "ANSWER_LAB_MODEL": MODEL,
            "ANSWER_LAB_MODEL_REVISION": MODEL,
            "ANSWER_LAB_MAX_TOKENS": "1536",
        })
    else:
        endpoint = urlsplit(environment.get("ANSWER_LAB_BASE_URL", ""))
        if (endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
                or endpoint.scheme not in {"http", "https"}
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or not environment.get("ANSWER_LAB_MODEL")):
            raise ValueError("Hybrid mode requires a configured local generator")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true",
                        help="Explicitly authorize this run under the existing total budget")
    parser.add_argument("--mode", choices=("hybrid", "hosted"), required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("No API calls: --allow-paid is required for a hosted experiment")
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error("Output directory already exists; retained evidence will not be overwritten")
    runtime_db = args.output_dir.with_name(args.output_dir.name + ".sqlite3")
    if runtime_db.exists() or runtime_db.is_symlink():
        parser.error("Study database already exists; choose a new output directory")
    audit_path = args.output_dir.with_name(args.output_dir.name + ".budget.json")
    if audit_path.exists() or audit_path.is_symlink():
        parser.error("Budget audit already exists; choose a new output directory")
    try:
        selected = route_environment(args.mode, dict(os.environ))
    except ValueError as exc:
        parser.error(str(exc))
    os.environ.update(selected)
    # The provider owns private key loading and durable reservations. No credential is
    # placed in arguments, report metadata, or any printed exception.
    service = AnswerService(runtime_db)
    budget_before = service.adapter.budget_status()
    signal.signal(signal.SIGTERM, interrupt)
    # The database is a sibling so the runner can exclusively create its report directory.
    report = run_study(args, service, budget_before)
    print(f"Study {report['status']}. Evidence saved to {args.output_dir.resolve()}.")
    return 0 if report["status"] == "completed" else 2


def run_study(args, service, budget_before):
    billing = {
        "mode": args.mode, "model": MODEL,
        "budget_before": budget_before,
        "cost_note": "Conservative client-side cost estimates at pinned standard prices; not an invoice. Unknown usage retains its full reservation. No automatic retries.",
    }
    audit_path = args.output_dir.with_name(args.output_dir.name + ".budget.json")
    save_json(audit_path, billing)
    try:
        report = run_benchmark(
            args.suite, args.output_dir, service=service, limit=args.limit,
            max_attempts=args.max_attempts, extra_source_files=(Path(__file__).resolve(),),
        )
    finally:
        billing["budget_after"] = service.adapter.budget_status()
        save_json(audit_path, billing)
    report["hosted_experiment"] = billing
    save_json(args.output_dir / "raw.json", report)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
