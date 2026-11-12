#!/usr/bin/env python3
"""Freeze expanded retrieval corpora, then compare production retrieval without LLM calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from agentproof.answers.models import AnswerRequest, Source
from agentproof.answers.retrieval import SentenceEmbedder, chunks, retrieve

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261112
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SCOPE = (
    "Expanded retrieval stress test reusing already-observed answerable QA questions; "
    "not unseen generalization or an official SQuAD evaluation. Only the original "
    "gold source is annotated relevant. Other sources are unjudged distractors, not "
    "independently verified negatives. No answer generation or critique is evaluated."
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(value):
    return sha(encoded(value))


def normalized(text):
    return " ".join(text.casefold().split())


def stamp():
    return datetime.now(UTC).isoformat()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_parent(path):
    raw = path.read_bytes()
    manifest = json.loads((path.parent / "manifest.json").read_text())
    if manifest.get("files", {}).get(path.name) != sha(raw):
        raise ValueError("Parent suite does not match its frozen manifest")
    suite = json.loads(raw)
    if suite.get("split") != "evaluation" or suite.get("version") != "answer-suite-v1":
        raise ValueError("Expected the frozen answer-suite-v1 evaluation split")
    return suite, sha(raw)


def freeze_suite(parent_path, output, *, seed=SEED, source_count=20, expected_cases=24):
    """Select corpora without calling retrieve(), scoring passages, or loading embeddings."""
    if output.exists():
        raise FileExistsError("Refusing to overwrite a frozen retrieval suite directory")
    if not 5 <= source_count <= 20:
        raise ValueError("Retrieval stress requires 5–20 sources, exceeding operational k=4")
    parent, parent_hash = read_parent(parent_path)
    qa = [case for case in parent["cases"] if case["task"] == "qa"]
    selected_cases = [case for case in qa if case["gold"].get("answerable") is True]
    if (
        len(selected_cases) != expected_cases
        or len({x["id"] for x in selected_cases}) != expected_cases
    ):
        raise ValueError("Unexpected number of distinct answerable parent questions")
    # Whitespace/case-normalized duplicate text is one candidate, independent of reused IDs.
    pool = {}
    for case in sorted(qa, key=lambda item: item["id"]):
        for source in sorted(case["request"]["sources"], key=lambda item: item["id"]):
            Source.model_validate(source)
            pool.setdefault(normalized(source["text"]), dict(source))
    pool = sorted(pool.values(), key=lambda item: sha(item["text"].encode()))
    pool_hash = digest([{key: item[key] for key in ("title", "text")} for item in pool])
    cases = []
    for case in sorted(selected_cases, key=lambda item: item["id"]):
        ids = case["gold"].get("relevant_source_ids", [])
        originals = [item for item in case["request"]["sources"] if item["id"] in ids]
        answers = [normalized(answer) for answer in case["gold"].get("answers", [])]
        if len(ids) != 1 or len(originals) != 1 or not answers or any(not a for a in answers):
            raise ValueError(
                "Every stress question needs one annotated source and nonempty answers"
            )
        original = originals[0]
        candidates = [
            item
            for item in pool
            if normalized(item["text"]) != normalized(original["text"])
            and not any(answer in normalized(item["text"]) for answer in answers)
        ]
        candidates.sort(
            key=lambda item: sha(
                f"{seed}:select:{case['id']}:{sha(item['text'].encode())}".encode()
            )
        )
        if len(candidates) < source_count - 1:
            raise ValueError("Insufficient distinct eligible distractors; no relaxed exclusions")
        sources = [dict(original), *[dict(item) for item in candidates[: source_count - 1]]]
        for source in sources:
            source["id"] = "passage-" + sha(source["text"].encode())[:20]
        relevant_id = sources[0]["id"]
        sources.sort(key=lambda item: sha(f"{seed}:order:{case['id']}:{item['id']}".encode()))
        request = AnswerRequest(question=case["request"]["question"], sources=sources)
        source_hashes = {item.id: sha(item.text.encode()) for item in request.sources}
        cases.append(
            {
                "id": case["id"],
                "origin": case.get("origin", {}),
                "question": request.question,
                "sources": sources,
                "annotation": {
                    "relevant_source_id": relevant_id,
                    "parent_relevant_source_id": ids[0],
                    "excluded_answer_strings": case["gold"]["answers"],
                },
                "source_sha256": source_hashes,
                "corpus_sha256": digest(sources),
                "eligible_distractor_count": len(candidates),
            }
        )
    suite = {
        "version": "retrieval-suite-v1",
        "scope": SCOPE,
        "seed": seed,
        "parent": {
            "suite": parent_path.name,
            "version": parent["version"],
            "split": parent["split"],
            "sha256": parent_hash,
        },
        "selection": "Per-query SHA256 seeded distractor selection and independent source-order shuffle; no relevance scores used",
        "exclusion": "Casefolded whitespace-normalized substring matching against all known answers; exclude normalized duplicate text and the annotated source",
        "corpus_pool": {
            "source": "All QA sources in the frozen parent evaluation split",
            "distinct_texts": len(pool),
            "sha256": pool_hash,
        },
        "sources_per_case": source_count,
        "operational_k": 4,
        "embedding": {
            "model": MODEL,
            "revision": REVISION,
            "device": "cpu",
            "local_files_only": True,
        },
        "cases": cases,
    }
    source = Path(__file__).read_bytes()
    manifest = {
        "version": "retrieval-freeze-v1",
        "created_at": stamp(),
        "scope": SCOPE,
        "freeze_step_did_not_run_ranking": True,
        "case_count": len(cases),
        "sources_per_case": source_count,
        "files": {"suite.json": sha(encoded(suite)), "frozen-generator.py.txt": sha(source)},
        "parent_sha256": parent_hash,
        "case_sha256": {case["id"]: digest(case) for case in cases},
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "suite.json").write_bytes(encoded(suite))
    (output / "frozen-generator.py.txt").write_bytes(source)
    (output / "manifest.json").write_bytes(encoded(manifest))
    return manifest


def load_frozen(path):
    manifest = json.loads((path.parent / "manifest.json").read_text())
    for name in ("suite.json", "frozen-generator.py.txt"):
        if manifest.get("files", {}).get(name) != sha((path.parent / name).read_bytes()):
            raise ValueError("Frozen retrieval file does not match manifest")
    if path.name != "suite.json":
        raise ValueError("Expected the frozen suite.json")
    suite = json.loads(path.read_text())
    if suite.get("version") != "retrieval-suite-v1" or suite.get("operational_k") != 4:
        raise ValueError("Unsupported retrieval suite")
    if suite.get("embedding") != {
        "model": MODEL,
        "revision": REVISION,
        "device": "cpu",
        "local_files_only": True,
    }:
        raise ValueError("Unexpected embedding configuration")
    cases = suite["cases"]
    if len(cases) != manifest.get("case_count") or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Incomplete or duplicate frozen cases")
    for case in cases:
        if digest(case) != manifest["case_sha256"].get(case["id"]):
            raise ValueError("Case changed after freeze")
        req = AnswerRequest(question=case["question"], sources=case["sources"])
        relevant = case["annotation"]["relevant_source_id"]
        if relevant not in {source.id for source in req.sources}:
            raise ValueError("Annotated source missing")
        if len(req.sources) != suite["sources_per_case"] or not 5 <= len(req.sources) <= 20:
            raise ValueError("Wrong frozen corpus size")
        if len({normalized(s.text) for s in req.sources}) != len(req.sources):
            raise ValueError("Duplicate source text")
        if digest(case["sources"]) != case["corpus_sha256"]:
            raise ValueError("Corpus hash mismatch")
        if {s.id: sha(s.text.encode()) for s in req.sources} != case["source_sha256"]:
            raise ValueError("Source hash mismatch")
    return suite, sha(path.read_bytes()), sha((path.parent / "manifest.json").read_bytes())


def source_manifest():
    return {
        str(path.relative_to(ROOT)): sha(path.read_bytes())
        for path in [
            Path(__file__).resolve(),
            ROOT / "src/agentproof/answers/retrieval.py",
            ROOT / "src/agentproof/answers/models.py",
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        ]
    }


def rank_case(case, embedder=None):
    """The annotation is used only AFTER production retrieval returns its ranking."""
    sources = [Source.model_validate(item) for item in case["sources"]]
    count = len(chunks(sources))
    ranking = retrieve(case["question"], sources, embedder, limit=count)
    selected = retrieve(case["question"], sources, embedder, limit=4)
    identity = lambda item: (item["source_id"], item["start"], item["end"])
    if [identity(x) for x in ranking["selected"][:4]] != [
        identity(x) for x in selected["selected"]
    ]:
        raise ValueError("Full-ranking prefix differs from production k=4")
    if embedder is not None and (
        ranking["method"] != "hybrid_bm25_embeddings"
        or selected["method"] != "hybrid_bm25_embeddings"
        or getattr(embedder, "status", None) != "loaded"
    ):
        raise ValueError("Embedding arm fell back instead of producing hybrid retrieval")
    relevant = case["annotation"]["relevant_source_id"]
    ranks = [i for i, item in enumerate(ranking["selected"], 1) if item["source_id"] == relevant]
    first = min(ranks) if ranks else None
    return {
        "status": "ranked",
        "method": ranking["method"],
        "source_count": len(sources),
        "chunk_count": count,
        "selected_count": len(selected["selected"]),
        "relevant_source_id": relevant,
        "annotated_source_first_rank": first,
        "recall_at_1": int(first is not None and first <= 1),
        "recall_at_4": int(first is not None and first <= 4),
        "reciprocal_rank": 1 / first if first else 0.0,
        "top_4_source_ids": [x["source_id"] for x in selected["selected"]],
        "ranking": [
            {
                "rank": index,
                "source_id": item["source_id"],
                "start": item["start"],
                "end": item["end"],
                "text_sha256": sha(item["text"].encode()),
                "score": item["score"],
                "lexical_score": item["lexical_score"],
                "semantic_score": item["semantic_score"],
            }
            for index, item in enumerate(ranking["selected"], 1)
        ],
    }


def summarize(rows, case_count):
    summary = {}
    for arm in ("bm25", "hybrid"):
        trials = [row for row in rows if row["arm"] == arm]
        ranked = [row for row in trials if row["status"] == "ranked"]
        complete = len(ranked) == case_count
        summary[arm] = {
            "planned_queries": case_count,
            "recorded_queries": len(trials),
            "ranked_queries": len(ranked),
            "errors": len(trials) - len(ranked),
            "complete": complete,
            "recall_at_1": sum(x["recall_at_1"] for x in ranked) / case_count if complete else None,
            "recall_at_4": sum(x["recall_at_4"] for x in ranked) / case_count if complete else None,
            "mrr": sum(x["reciprocal_rank"] for x in ranked) / case_count if complete else None,
        }
    return summary


def evaluate(suite_path, output, *, embedder=None):
    suite, suite_hash, manifest_hash = load_frozen(suite_path)
    output.mkdir(parents=True, exist_ok=False)
    files = source_manifest()
    packages = {}
    for package in ("sentence-transformers", "torch", "huggingface-hub"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    configuration = {
        "operational_k": 4,
        "ranked_limit": "all production chunks; prefix checked against actual limit=4",
        "corpus_order": "identical frozen order for both arms",
        "embedding": suite["embedding"],
        "runtime_source_sha256": files,
        "python": platform.python_version(),
        "packages": packages,
        "platform": platform.system(),
        "machine": platform.machine(),
        "no_llm_calls": True,
        "no_network_downloads": True,
        "metric_unit": "rank of first chunk belonging to the single annotated relevant source",
    }
    report = {
        "format": "retrieval-study-v1",
        "created_at": stamp(),
        "status": "running",
        "scope": SCOPE,
        "suite_sha256": suite_hash,
        "manifest_sha256": manifest_hash,
        "suite": {
            "case_count": len(suite["cases"]),
            "parent": suite["parent"],
            "corpus_pool": suite["corpus_pool"],
        },
        "configuration": configuration,
        "configuration_sha256": digest(configuration),
        "llm_calls": 0,
        "trials": [],
        "summary": {},
    }
    path = output / "raw.json"
    save_json(path, report)
    if embedder is None:
        embedder = SentenceEmbedder(MODEL)
        embedder.revision = REVISION
    try:
        if (
            getattr(embedder, "name", None) != MODEL
            or getattr(embedder, "revision", None) != REVISION
        ):
            raise ValueError("Embedding identity does not match frozen configuration")
        warmup = embedder.encode(["retrieval stress warmup"])
        available = (
            getattr(embedder, "status", None) == "loaded"
            and bool(warmup)
            and len(warmup) == 1
            and bool(warmup[0])
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in warmup[0])
        )
        report["embedding_loaded"] = available
        for case in suite["cases"]:
            for arm in ("bm25", "hybrid"):
                row = {
                    "case_id": case["id"],
                    "arm": arm,
                    "question_sha256": sha(case["question"].encode()),
                    "corpus_sha256": case["corpus_sha256"],
                }
                try:
                    if arm == "hybrid" and not available:
                        raise ValueError("Pinned embeddings unavailable")
                    row.update(rank_case(case, embedder if arm == "hybrid" else None))
                except (
                    ValueError,
                    TypeError,
                    RuntimeError,
                    OSError,
                    KeyError,
                    IndexError,
                    ArithmeticError,
                ) as exc:
                    # Preserve error coverage without arbitrary exception text or local paths.
                    row.update(
                        status="error",
                        error_type=type(exc).__name__,
                        error="Retrieval failed or the required hybrid configuration was unavailable",
                    )
                report["trials"].append(row)
                report["summary"] = summarize(report["trials"], len(suite["cases"]))
                save_json(path, report)
        report["source_integrity"] = files == source_manifest()
        try:
            # Recheck every frozen input, including the archived generator. Merely
            # hashing the unchanged manifest would miss a modified listed file.
            _, final_suite_hash, final_manifest_hash = load_frozen(suite_path)
            report["suite_integrity"] = (
                suite_hash == final_suite_hash and manifest_hash == final_manifest_hash
            )
        except (ValueError, OSError, KeyError, TypeError):
            report["suite_integrity"] = False
        report["status"] = (
            "completed"
            if report["source_integrity"]
            and report["suite_integrity"]
            and all(value["complete"] for value in report["summary"].values())
            else "failed"
        )
    except (
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
        KeyError,
        IndexError,
        ArithmeticError,
        KeyboardInterrupt,
    ) as exc:
        report.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            error_type=type(exc).__name__,
        )
    finally:
        report["summary"] = summarize(report["trials"], len(suite["cases"]))
        report["finished_at"] = stamp()
        save_json(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="Freeze corpora without running retrieval")
    freeze.add_argument(
        "--parent-suite", type=Path, default=ROOT / "examples/answer-suite-v1/evaluation.json"
    )
    freeze.add_argument("--output-dir", type=Path, required=True)
    run = commands.add_parser("run", help="Use cached pinned CPU embeddings; no LLM calls")
    run.add_argument("--suite", type=Path, default=ROOT / "examples/retrieval-suite-v1/suite.json")
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_suite(args.parent_suite, args.output_dir)
        print(json.dumps({"frozen_cases": result["case_count"], "files": result["files"]}))
    else:
        result = evaluate(args.suite, args.output_dir)
        print(json.dumps({"status": result["status"], "summary": result["summary"]}))
        if result["status"] != "completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
