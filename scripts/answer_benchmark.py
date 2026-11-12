#!/usr/bin/env python3
"""Run frozen, paired Answer Lab studies on a local model, or regrade saved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import signal
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from agentproof.answer_eval import (
    STRATEGIES,
    evidence_digest,
    grade_result,
    load_suite,
    percentile,
    summarize_report,
)
from agentproof.answers import AnswerRequest, AnswerService

ROOT = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(UTC).isoformat()


def source_manifest(extra_files=()):
    paths = sorted((ROOT / "src/agentproof/answers").glob("*.py")) + [
        ROOT / "src/agentproof/answer_eval.py", Path(__file__).resolve(),
    ]
    paths += [Path(path).resolve() for path in extra_files]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def save_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def request_for(case, *, strategy, max_attempts=3, namespace="benchmark", use_cache=False):
    # Explicit allowlist is the boundary between reference data and model input.
    allowed = {k: case["request"][k] for k in ("question", "sources", "task", "schema")
               if k in case["request"]}
    return AnswerRequest(**allowed, strategy=strategy, max_attempts=max_attempts,
                         namespace=namespace, use_cache=use_cache)


def actual_usage(report):
    initial = [item["response"] for item in report["initial_generations"]]
    trial_usage = [trial["result"]["usage"] for trial in report["trials"]]
    known = (all(item["usage_known"] for item in initial)
             and all(item["known"] for item in trial_usage))
    tokens = sum((item.get("prompt_tokens") or 0) + (item.get("completion_tokens") or 0)
                 for item in initial)
    tokens += sum(item.get("actual_total_tokens") or 0 for item in trial_usage)
    return {"calls": len(initial) + sum(item.get("actual_calls", 0) for item in trial_usage),
            "observed_tokens": tokens, "total_tokens": tokens if known else None,
            "usage_known": known,
            "shared_initial_generations": len(initial),
            "logical_policy_tokens_are_not_actual_study_tokens": True}


def run_benchmark(suite_path: Path, output: Path, *, service=None, strategies=STRATEGIES,
                  seed=20261112, max_attempts=3, limit=None, extra_source_files=()):
    suite, suite_hash = load_suite(suite_path)
    if "baseline" not in strategies or len(set(strategies)) != len(strategies):
        raise ValueError("Unique strategies including baseline are required")
    if set(strategies) - set(STRATEGIES):
        raise ValueError("Unsupported strategy")
    cases = list(suite["cases"])
    random.Random(seed).shuffle(cases)
    if limit is not None:
        if limit < 1:
            raise ValueError("Limit must be positive")
        cases = cases[:limit]
    output.mkdir(parents=True, exist_ok=False)
    service = service or AnswerService(output / "runtime.sqlite3")
    embedding_started = time.perf_counter()
    embedding_available = None
    if hasattr(service, "embedder"):
        embedding_available = service.embedder.encode(["warmup"]) is not None
    embedding_warmup = {"latency_ms": (time.perf_counter() - embedding_started) * 1000,
                        "available": embedding_available, "model_calls": 0,
                        "included_in_trial_latency": False}
    report = {
        "format_version": "answer-lab-study-v1", "id": output.name,
        "title": "Source-grounded answer reliability — paired policy comparison",
        "created_at": utc_now(), "model": service.adapter.model, "status": "running",
        "suite": {"sha256": suite_hash, "version": suite["version"], "split": suite["split"],
                  "case_count": len(cases), "case_ids": [case["id"] for case in cases],
                  "case_manifest_sha256": {case["id"]: evidence_digest(case) for case in cases},
                  "limited": limit is not None, "provenance": suite.get("provenance", {})},
        "configuration": {"strategies": list(strategies), "max_attempts": max_attempts,
                          "seed": seed, "cache_enabled": False,
                          "runtime": service.configuration(), "source_files": source_manifest(extra_source_files),
                          "python": platform.python_version(), "machine": platform.machine(),
                          "system": platform.system(),
                          "initial_generation": "One shared first response; each policy logically pays its full initial cost, actual study usage counts it once."},
        "initial_generations": [], "trials": [], "summary": {},
        "embedding_warmup": embedding_warmup,
    }
    try:
        report["configuration"]["git_revision"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        report["configuration"]["git_revision"] = "unrecorded"
    started = time.perf_counter()
    save_json(output / "raw.json", report)
    try:
        for case in cases:
            req = request_for(case, strategy="baseline", max_attempts=max_attempts)
            initial_start = time.perf_counter()
            initial = service.generate_initial(req)
            report["initial_generations"].append({"case_id": case["id"], "response": asdict(initial),
                                                   "wall_latency_ms": (time.perf_counter()-initial_start)*1000})
            # Persist the actual response before subsequent work; interruption never erases it.
            save_json(output / "raw.json", report)
            baseline = service.run(req, initial_response=initial, persist=False)
            initial_grade = grade_result(case, baseline)
            arms = [s for s in strategies if s != "baseline"]
            random.Random(f"{seed}:{case['id']}").shuffle(arms)
            for strategy in ["baseline", *arms]:
                result = baseline if strategy == "baseline" else service.run(
                    request_for(case, strategy=strategy, max_attempts=max_attempts),
                    initial_response=initial, persist=False,
                )
                report["trials"].append({
                    "case_id": case["id"], "task": case["task"], "category": case["category"],
                    "question": case["request"]["question"], "strategy": strategy,
                    "case": case, "result": result, "initial_result": baseline,
                    "grade": grade_result(case, result), "initial_grade": initial_grade,
                })
                report["actual_usage"] = actual_usage(report)
                report["elapsed_seconds"] = time.perf_counter() - started
                save_json(output / "raw.json", report)
                print(json.dumps({"completed": len(report["trials"]),
                                  "planned": len(cases)*len(strategies), "case": case["id"],
                                  "strategy": strategy, "correct": report["trials"][-1]["grade"]["correct"]}), flush=True)
            report["summary"] = summarize_report(report)
            save_json(output / "raw.json", report)
        report["status"] = "completed"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    except Exception as exc:
        report["status"] = "error"
        # Avoid transport exception bodies, prompts or keys in user-facing log paths.
        report["failure"] = {"type": type(exc).__name__, "message": "Study interrupted by an execution error; inspect retained trials."}
        raise
    finally:
        report["finished_at"] = utc_now()
        report["elapsed_seconds"] = time.perf_counter() - started
        report["source_unchanged"] = source_manifest(extra_source_files) == report["configuration"]["source_files"]
        report["actual_usage"] = actual_usage(report)
        report["summary"] = summarize_report(report)
        if not report["source_unchanged"]:
            report["summary"]["complete"] = False
            report["source_warning"] = "Source files changed while the study was running. This is not frozen-runtime evidence."
        save_json(output / "raw.json", report)
        save_json(output / "summary.json", report["summary"])
    return report


def run_cache_study(suite_path, output, *, service=None, limit=6, repeats=5):
    suite, suite_hash = load_suite(suite_path)
    if limit < 1 or repeats < 1:
        raise ValueError("Cache limit and repeats must be positive")
    output.mkdir(parents=True, exist_ok=False)
    service = service or AnswerService(output / "runtime.sqlite3")
    if hasattr(service, "embedder"):
        service.embedder.encode(["warmup"])
    namespace = "cache-study-" + uuid.uuid4().hex
    report = {"format_version": "answer-lab-cache-v1", "id": output.name,
              "created_at": utc_now(), "status": "running", "model": service.adapter.model,
              "suite_sha256": suite_hash, "selection": "First N frozen cases, no selection by result",
              "configuration": service.configuration(), "source_files": source_manifest(),
              "repeats": repeats, "trials": []}
    try:
        for case in suite["cases"][:limit]:
            req = request_for(case, strategy="adaptive", namespace=namespace, use_cache=True)
            cold = service.run(req, persist=False)
            row = {"case_id": case["id"], "case": case, "cold": cold,
                   "cold_grade": grade_result(case, cold), "warm": []}
            report["trials"].append(row)
            save_json(output / "raw.json", report)
            for _ in range(repeats):
                warm = service.run(req, persist=False)
                row["warm"].append({"result": warm, "grade": grade_result(case, warm)})
                save_json(output / "raw.json", report)
        report["status"] = "completed"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    finally:
        warm = [item for row in report["trials"] for item in row["warm"]]
        exact = [item for item in warm if item["result"].get("cache", {}).get("status") == "exact_hit"]
        semantic = [item for item in warm if item["result"].get("cache", {}).get("status") == "semantic_hit"]
        paired_speedups = []
        for row in report["trials"]:
            latencies = [item["result"]["latency_ms"] for item in row["warm"]
                         if item["result"].get("cache", {}).get("status") == "exact_hit"]
            if latencies and percentile(latencies, .5) > 0:
                paired_speedups.append(row["cold"]["latency_ms"] / percentile(latencies, .5))
        report["summary"] = {
            "cases": len(report["trials"]), "warm_queries": len(warm), "exact_hits": len(exact),
            "semantic_hits": len(semantic), "hit_rate": len(exact+semantic)/len(warm) if warm else None,
            "incorrect_exact_hits": sum(not item["grade"]["correct"] for item in exact),
            "incorrect_semantic_hits": sum(not item["grade"]["correct"] for item in semantic),
            "exact_hit_precision": sum(item["grade"]["correct"] for item in exact)/len(exact) if exact else None,
            "paired_exact_speedup_p50": percentile(paired_speedups, .5),
            "speedup_paired_cases": len(paired_speedups),
            "exact_hit_latency_p50_ms": percentile([x["result"]["latency_ms"] for x in exact], .5),
            "exact_hit_latency_p95_ms": percentile([x["result"]["latency_ms"] for x in exact], .95),
            "scope": "Exact identical-question replay only. Embeddings prewarmed; inference server startup is operator-controlled. No paraphrase accuracy or general throughput claim.",
        }
        report["source_unchanged"] = source_manifest() == report["source_files"]
        save_json(output / "raw.json", report)
    return report


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "cache"):
        command = commands.add_parser(name)
        command.add_argument("--suite", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--limit", type=int, default=6 if name == "cache" else None)
        if name == "run":
            command.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
            command.add_argument("--seed", type=int, default=20261112)
            command.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
        else:
            command.add_argument("--repeats", type=int, default=5)
    analyse = commands.add_parser("analyse")
    analyse.add_argument("raw", type=Path)
    analyse.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    if args.command == "analyse":
        if args.output.exists():
            parser.error("Analysis output already exists; choose a new file to preserve evidence")
        report = json.loads(args.raw.read_text())
        summary = summarize_report(report)
        save_json(args.output, summary)
        print(json.dumps(summary, indent=2))
        return 0
    endpoints = [os.getenv("ANSWER_LAB_BASE_URL", "")]
    if os.getenv("ANSWER_LAB_CRITIC_BASE_URL"):
        endpoints.append(os.environ["ANSWER_LAB_CRITIC_BASE_URL"])
    if any(urlsplit(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
           for endpoint in endpoints):
        parser.error("This runner permits only local inference endpoints; no paid API calls")
    if args.command == "run":
        report = run_benchmark(args.suite, args.output_dir, strategies=args.strategies,
                               seed=args.seed, max_attempts=args.max_attempts, limit=args.limit)
    else:
        report = run_cache_study(args.suite, args.output_dir, limit=args.limit, repeats=args.repeats)
    print(json.dumps({"status": report["status"], "output": str(args.output_dir.resolve()),
                      "summary": report["summary"]}, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
