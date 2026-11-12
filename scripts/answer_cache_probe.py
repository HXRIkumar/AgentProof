"""Measure and independently regrade exact replay and semantic near misses.

This is a separate synthetic cache study, not part of answer-quality evaluation.
Every cold, warm, miss and rejection is retained. No invented latency constants.
"""

import argparse
import hashlib
import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from agentproof.answer_cache_eval import cache_case, expected_request, summarize_cache
from agentproof.answer_eval import grade_result
from agentproof.answers import AnswerRequest, AnswerService
from agentproof.answers.models import parse_json

ROOT = Path(__file__).resolve().parents[1]


def atomic_save(path, data):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        stream.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def source_manifest():
    paths = sorted((ROOT / "src/agentproof/answers").glob("*.py")) + [
        ROOT / "src/agentproof/answer_eval.py", ROOT / "src/agentproof/answer_cache_eval.py",
        Path(__file__).resolve(),
    ]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def execute(service, request, references):
    start = time.perf_counter()
    result = service.run(request)
    wall_ms = (time.perf_counter() - start) * 1000
    grade = grade_result(cache_case(references), result)
    return {
        "request": request.model_dump(by_alias=True), "references": references,
        "result": result, "end_to_end_ms": wall_ms,
        "exact_match": grade["exact_match"], "token_f1": grade["token_f1"],
        "correct": grade["correct"],
    }


def run_probe(suite_path, output_dir, *, replays=5):
    if not 1 <= replays <= 20:
        raise ValueError("Replay count must be between 1 and 20")
    if output_dir.exists():
        raise FileExistsError("Output directory exists; use a new path to preserve prior evidence")
    suite_bytes = suite_path.read_bytes()
    suite = parse_json(suite_bytes.decode())
    output_dir.mkdir(parents=True)
    db = output_dir / "cache.sqlite3"
    service = AnswerService(db)
    if not service.public_config()["configured"]:
        raise ValueError("Set the ANSWER_LAB local inference configuration first")
    warmup_start = time.perf_counter()
    service.embedder.encode(["warmup"])
    report = {
        "format": "answer-cache-probe-v1", "id": output_dir.name,
        "title": "Selective cache: exact replay and semantic near misses",
        "model": service.adapter.model, "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "suite_source_text": suite_bytes.decode(), "suite_snapshot": suite,
        "plan": {"replays_per_group": replays, "max_attempts": 3},
        "configuration": service.configuration(), "source_files": source_manifest(),
        "groups": [],
        "embedding_warmup": {"latency_ms": (time.perf_counter() - warmup_start) * 1000,
                             "model_calls": 0, "included_in_trial_latency": False},
        "scope": "Synthetic cache stress cases; exact replay latency is not new-query speed. A new SQLite DB is used; the service is reconstructed before exact replays. Model server prewarming is operator-controlled.",
    }
    output = output_dir / "raw.json"
    atomic_save(output, report)
    try:
        for group in suite["groups"]:
            seed = AnswerRequest(**expected_request(group, group["seed"]["question"]))
            cold = execute(service, seed, group["seed"]["answers"])
            record = {"id": group["id"], "cold": cold, "replays": [], "queries": []}
            report["groups"].append(record)
            atomic_save(output, report)
            # Preserve only the immutable embedding model, never an in-memory answer cache.
            service = AnswerService(db, adapter=service.adapter, embedder=service.embedder)
            for _ in range(replays):
                record["replays"].append(execute(service, seed, group["seed"]["answers"]))
                atomic_save(output, report)
            for query in group["queries"]:
                request = AnswerRequest(**expected_request(group, query["question"]))
                record["queries"].append({
                    "kind": query["kind"], "reuse_expected": query["reuse_expected"],
                    **execute(service, request, query["answers"]),
                })
                atomic_save(output, report)
            print(f"Finished {group['id']}", flush=True)
        report["status"] = "completed"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    except BaseException:
        report["status"] = "error"
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["source_files_after"] = source_manifest()
        report["source_unchanged"] = report["source_files_after"] == report["source_files"]
        # Save actual observations before grading, so an audit failure preserves its cause.
        atomic_save(output, report)
        report["summary"] = summarize_cache(report)
        atomic_save(output, report)
        atomic_save(output_dir / "summary.json", report["summary"])
    return report


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=Path("examples/cache-probe-v1.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replays", type=int, default=5)
    args = parser.parse_args()
    if urlsplit(os.getenv("ANSWER_LAB_BASE_URL", "")).hostname not in {
        "127.0.0.1", "localhost", "::1",
    }:
        parser.error("This study is restricted to a free local inference endpoint")
    signal.signal(signal.SIGTERM, interrupt)
    report = run_probe(args.suite, args.output_dir, replays=args.replays)
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
