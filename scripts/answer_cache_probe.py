"""Measure exact replay and semantic near misses using the real answer runtime.

This is a separate synthetic cache study, not part of answer-quality evaluation.
Every cold, warm, miss and rejection is retained. No invented latency constants.
"""

import argparse
import hashlib
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from agentproof.answer_eval import grade_result
from agentproof.answers import AnswerRequest, AnswerService


def atomic_save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def execute(service, request, references):
    start = time.perf_counter()
    result = service.run(request)
    wall_ms = (time.perf_counter() - start) * 1000
    grade = grade_result({"task": "qa", "gold": {"answers": references}}, result)
    return {
        "result": result,
        "end_to_end_ms": wall_ms,
        "exact_match": grade["exact_match"],
        "token_f1": grade["token_f1"],
        "correct": grade["correct"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=Path("examples/cache-probe-v1.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replays", type=int, default=5)
    args = parser.parse_args()
    if urlsplit(os.getenv("ANSWER_LAB_BASE_URL", "")).hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        parser.error("This study is restricted to a free local inference endpoint")
    if not 1 <= args.replays <= 20:
        parser.error("Replay count must be between 1 and 20")
    if args.output_dir.exists():
        parser.error("Output directory exists; use a new path to preserve prior evidence")
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    args.output_dir.mkdir(parents=True)
    db = args.output_dir / "cache.sqlite3"
    service = AnswerService(db)
    if not service.public_config()["configured"]:
        parser.error("Set the ANSWER_LAB local inference configuration first")
    report = {
        "format": "answer-cache-probe-v1",
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "configuration": service.configuration(),
        "groups": [],
        "scope": "Synthetic cache stress cases; exact replay latency is not new-query speed",
    }
    output = args.output_dir / "raw.json"
    atomic_save(output, report)
    try:
        for group in suite["groups"]:
            seed = AnswerRequest(
                question=group["seed"]["question"],
                sources=[group["source"]],
                namespace=group["id"],
                strategy="adaptive",
                use_cache=True,
            )
            cold = execute(service, seed, group["seed"]["answers"])
            record = {"id": group["id"], "cold": cold, "replays": [], "queries": []}
            report["groups"].append(record)
            atomic_save(output, report)
            # Reconstruct the service to demonstrate persistent SQLite lookup. Retain
            # the already-loaded immutable embedding model; no in-memory answer cache.
            service = AnswerService(db, adapter=service.adapter, embedder=service.embedder)
            for _ in range(args.replays):
                record["replays"].append(execute(service, seed, group["seed"]["answers"]))
                atomic_save(output, report)
            for query in group["queries"]:
                request = seed.model_copy(update={"question": query["question"]})
                record["queries"].append(
                    {
                        "kind": query["kind"],
                        "reuse_expected": query["reuse_expected"],
                        "references": query["answers"],
                        **execute(service, request, query["answers"]),
                    }
                )
                atomic_save(output, report)
            print(f"Finished {group['id']}", flush=True)
        report["status"] = "completed"
    except BaseException:
        report["status"] = "interrupted"
        atomic_save(output, report)
        raise
    replays = [row for group in report["groups"] for row in group["replays"]]
    queries = [row for group in report["groups"] for row in group["queries"]]
    exact_hits = [row for row in replays if row["result"]["cache"]["status"] == "exact_hit"]
    semantic = [row for row in queries if row["result"]["cache"]["status"] == "semantic_hit"]
    eligible_groups = [
        group
        for group in report["groups"]
        if group["replays"]
        and all(r["result"]["cache"]["status"] == "exact_hit" for r in group["replays"])
    ]
    cold_times = [g["cold"]["end_to_end_ms"] for g in eligible_groups]
    warm_times = [r["end_to_end_ms"] for g in eligible_groups for r in g["replays"]]
    all_rows = [g["cold"] for g in report["groups"]] + replays + queries
    report["summary"] = {
        "cold_requests": len(report["groups"]),
        "exact_replay_requests": len(replays),
        "exact_hits": len(exact_hits),
        "exact_answer_matches": sum(r["exact_match"] for r in exact_hits),
        "exact_hit_rate": len(exact_hits) / len(replays) if replays else None,
        "paired_cold_requests": len(cold_times),
        "cold_p50_ms": statistics.median(cold_times) if cold_times else None,
        "warm_p50_ms": statistics.median(warm_times) if warm_times else None,
        "p50_exact_replay_speedup": statistics.median(cold_times) / statistics.median(warm_times)
        if cold_times and warm_times
        else None,
        "semantic_queries": len(queries),
        "semantic_hits": len(semantic),
        "semantic_false_hits": sum(not r["exact_match"] for r in semantic),
        "semantic_false_hit_rate": sum(not r["exact_match"] for r in semantic) / len(semantic)
        if semantic
        else None,
        "semantic_total_correct": sum(r["correct"] for r in queries),
        "rejected_candidates": sum(r["result"]["cache"]["rejected_candidates"] for r in queries),
        "actual_calls": sum(r["result"]["usage"]["actual_calls"] for r in all_rows),
        "tokens": sum(r["result"]["usage"]["total_tokens"] for r in all_rows),
        "usage_known": all(r["result"]["usage"]["known"] for r in all_rows),
    }
    atomic_save(output, report)
    atomic_save(args.output_dir / "summary.json", report["summary"])
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
