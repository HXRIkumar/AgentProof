"""Independent grading and coverage/accounting checks for recorded cache probes.

No inference is performed. This is a separate synthetic cache workload, not an
estimate of novel-query answer quality or general application throughput.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from typing import Any

from .answer_eval import cost_summary, evidence_digest, grade_result, normalize_answer


class CacheEvidenceError(ValueError):
    """The record cannot support the claimed cache-study measurement."""


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise CacheEvidenceError(f"{label} must be numeric")
    if not math.isfinite(value) or value < 0:
        raise CacheEvidenceError(f"{label} must be finite and nonnegative")
    return value


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise CacheEvidenceError(f"{label} must be a nonnegative integer")
    return value


def _mean_ratio(a, b):
    return a / b if b else None


def _median(values):
    return statistics.median(values) if values else None


def cache_case(references):
    return {"task": "qa", "gold": {"answers": references,
            "answerable": any(normalize_answer(answer) for answer in references)}}


def expected_request(group, question, max_attempts=3):
    return {"question": question, "sources": [group["source"]], "task": "qa", "schema": None,
            "strategy": "adaptive", "max_attempts": max_attempts, "use_cache": True,
            "namespace": group["id"]}


def _decode_strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CacheEvidenceError("Duplicate JSON key in suite snapshot")
            result[key] = value
        return result

    def nonfinite(_value):
        raise CacheEvidenceError("Nonfinite JSON in suite snapshot")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def _response_usage(result):
    """Reconstruct attempted model calls from saved generation and critic responses."""
    responses = []
    for attempt in result.get("attempts", []):
        if not isinstance(attempt.get("generation"), dict):
            raise CacheEvidenceError("A generation response is missing")
        responses.append(attempt["generation"])
        if attempt.get("critic_response") is not None:
            responses.append(attempt["critic_response"])
    verification = result.get("cache", {}).get("verification")
    if verification is not None:
        if not isinstance(verification.get("response"), dict):
            raise CacheEvidenceError("Cache verification response is missing")
        responses.append(verification["response"])
    recorded = responses
    responses = []
    blocked = 0
    for response in recorded:
        sent = response.get("request_sent", True)
        if type(sent) is not bool:
            raise CacheEvidenceError("Response request-sent flag must be boolean")
        if sent:
            responses.append(response)
        else:
            blocked += 1
            if any(response.get(name) not in (None, 0) for name in ("prompt_tokens", "completion_tokens")):
                raise CacheEvidenceError("A blocked request cannot report consumed tokens")
            if response.get("billing") is not None:
                raise CacheEvidenceError("A blocked request cannot report a billed reservation")
    prompt_tokens = completion_tokens = 0
    known = True
    for response in responses:
        if type(response.get("usage_known")) is not bool:
            raise CacheEvidenceError("Response usage-known flag is missing")
        for name in ("prompt_tokens", "completion_tokens"):
            value = response.get(name)
            if value is not None:
                _integer(value, name)
            elif response["usage_known"]:
                raise CacheEvidenceError("Known response usage has missing tokens")
        prompt_tokens += response.get("prompt_tokens") or 0
        completion_tokens += response.get("completion_tokens") or 0
        known = known and response["usage_known"]
    expected = {
        "calls": len(responses), "actual_calls": len(responses), "reused_calls": 0,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "actual_total_tokens": prompt_tokens + completion_tokens,
        "known": known,
        "unknown_calls": sum(not response["usage_known"] for response in responses),
    }
    usage = result.get("usage", {})
    if blocked or "blocked_calls" in usage:
        expected["blocked_calls"] = blocked
    for key, value in expected.items():
        if type(usage.get(key)) is not type(value) or usage.get(key) != value:
            raise CacheEvidenceError(f"Recorded model accounting disagrees for {key}")
    if result.get("cache", {}).get("status") in {"exact_hit", "semantic_hit"} and blocked:
        raise CacheEvidenceError("Blocked verification cannot produce a cache hit")
    if result.get("cache", {}).get("status") == "exact_hit" and responses:
        raise CacheEvidenceError("Exact cache hits must not make inference calls")
    if result.get("cache", {}).get("status") == "semantic_hit" and verification is None:
        raise CacheEvidenceError("Semantic cache hits require a recorded fresh critique")
    cost_records = []
    for response in responses:
        billing = response.get("billing")
        if billing is not None:
            cost_records.append({"paid_calls": 1, "actual_paid_calls": 1,
                                 "cost_known": billing.get("state") == "settled",
                                 "estimated_cost_usd": billing.get("estimated_cost_usd"),
                                 "accounted_cost_usd": billing.get("accounted_usd")})
    if blocked:
        cost_records.append({"blocked_calls": blocked})
    costs = cost_summary(cost_records)
    if costs:
        costs.update({"actual_cost_known": costs["cost_known"],
                      "actual_estimated_cost_usd": costs["estimated_cost_usd"],
                      "actual_accounted_cost_usd": costs["accounted_cost_usd"]})
    for key in ("paid_calls", "actual_paid_calls", "cost_known", "estimated_cost_usd", "accounted_cost_usd",
                "actual_cost_known", "actual_estimated_cost_usd", "actual_accounted_cost_usd"):
        if key in costs and usage.get(key) != costs[key]:
            raise CacheEvidenceError(f"Recorded model accounting disagrees for {key}")
    expected.update(costs)
    return expected


def _grade_row(row, group, question, references, report):
    expected = expected_request(group, question, report["plan"]["max_attempts"])
    if row.get("request") != expected:
        raise CacheEvidenceError("Recorded request differs from frozen cache plan")
    if row.get("references") != references:
        raise CacheEvidenceError("Recorded references differ from frozen cache plan")
    result = row["result"]
    for key in ("question", "sources", "task", "schema", "strategy", "namespace"):
        if result.get(key) != expected[key]:
            raise CacheEvidenceError(f"Runtime result {key} differs from its request")
    if result.get("model") != report["model"]:
        raise CacheEvidenceError("Result model differs from study model")
    if result.get("config_hash") != evidence_digest(report["configuration"]):
        raise CacheEvidenceError("Effective model/configuration changed during cache study")
    if result.get("source_hash") != evidence_digest(expected["sources"]):
        raise CacheEvidenceError("Result source fingerprint differs from frozen source")
    wall = _number(result.get("wall_latency_ms"), "Runtime wall latency")
    logical = _number(result.get("latency_ms"), "Runtime latency")
    elapsed = _number(row.get("end_to_end_ms"), "End-to-end latency")
    if abs(wall - logical) > 1e-6:
        raise CacheEvidenceError("Cache probes cannot reuse unmeasured initial generations")
    if elapsed + 1e-6 < wall:
        raise CacheEvidenceError("End-to-end latency cannot be shorter than runtime wall latency")
    usage = _response_usage(result)
    grade = grade_result(cache_case(references), result)
    # Return derived grades; raw saved grades are not trusted and need not be rewritten.
    return {**row, "exact_match": grade["exact_match"], "token_f1": grade["token_f1"],
            "correct": grade["correct"], "grade": grade, "audited_usage": usage}


def _source_integrity(report):
    initial = report.get("source_files", {})
    final = report.get("source_files_after", {})
    if not initial or not isinstance(initial, dict) or not isinstance(final, dict):
        raise CacheEvidenceError("Runtime source snapshots are missing")
    for name, digest in initial.items():
        if name.startswith("/") or ".." in name.split("/"):
            raise CacheEvidenceError("Source manifest paths must be relative")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CacheEvidenceError("Source manifest contains an invalid digest")
    unchanged = initial == final
    if report.get("source_unchanged") is not unchanged:
        raise CacheEvidenceError("Source integrity flag disagrees with snapshots")
    return unchanged


def summarize_cache(report: dict[str, Any]) -> dict:
    """Regrade the entire raw cache artifact and return stable frontend summary keys."""
    if report.get("format") != "answer-cache-probe-v1":
        raise CacheEvidenceError("Unsupported cache report format")
    raw_suite = report.get("suite_source_text")
    if not isinstance(raw_suite, str):
        raise CacheEvidenceError("Frozen source suite text is required")
    if hashlib.sha256(raw_suite.encode()).hexdigest() != report.get("suite_sha256"):
        raise CacheEvidenceError("Frozen suite bytes do not match their fingerprint")
    suite = _decode_strict(raw_suite)
    if suite != report.get("suite_snapshot"):
        raise CacheEvidenceError("Frozen suite snapshot differs from source bytes")
    planned = suite["groups"]
    if len({group["id"] for group in planned}) != len(planned):
        raise CacheEvidenceError("Frozen group IDs must be unique")
    replay_count = _integer(report["plan"]["replays_per_group"], "Replay count")
    if not 1 <= replay_count <= 20 or report["plan"]["max_attempts"] not in {1, 2, 3}:
        raise CacheEvidenceError("Invalid bounded cache experiment plan")
    observed = report["groups"]
    if len(observed) > len(planned):
        raise CacheEvidenceError("Unexpected cache groups")
    groups = []
    seen_results = set()
    previous_results = {}
    complete_coverage = len(observed) == len(planned)
    for index, record in enumerate(observed):
        group = planned[index]
        if record["id"] != group["id"]:
            raise CacheEvidenceError("Group order differs from frozen plan")
        if len(record["replays"]) > replay_count or len(record["queries"]) > len(group["queries"]):
            raise CacheEvidenceError("Unexpected replay or semantic query")
        complete_coverage &= len(record["replays"]) == replay_count
        complete_coverage &= len(record["queries"]) == len(group["queries"])
        cold = _grade_row(record["cold"], group, group["seed"]["question"],
                          group["seed"]["answers"], report)
        replays = [_grade_row(row, group, group["seed"]["question"], group["seed"]["answers"], report)
                   for row in record["replays"]]
        queries = []
        for query_index, row in enumerate(record["queries"]):
            plan = group["queries"][query_index]
            if row.get("kind") != plan["kind"] or row.get("reuse_expected") is not plan["reuse_expected"]:
                raise CacheEvidenceError("Query category differs from the frozen plan")
            queries.append(_grade_row(row, group, plan["question"], plan["answers"], report))
        for row in [cold, *replays, *queries]:
            result = row["result"]
            run_id = result.get("id")
            if not isinstance(run_id, str) or not run_id or run_id in seen_results:
                raise CacheEvidenceError("Run IDs must be unique and nonempty")
            seen_results.add(run_id)
            cache_status = result.get("cache", {}).get("status")
            if cache_status not in {"miss", "exact_hit", "semantic_hit"}:
                raise CacheEvidenceError("Cache probe must have caching enabled")
            if cache_status in {"exact_hit", "semantic_hit"}:
                if result.get("status") != "accepted":
                    raise CacheEvidenceError("A served cache hit must be an accepted output")
                source_id = result["cache"].get("source_run_id")
                source = previous_results.get(source_id)
                if source is None or source.get("status") != "accepted":
                    raise CacheEvidenceError("Cache hit refers to no earlier accepted run")
                for key in ("namespace", "source_hash", "config_hash", "answer", "data", "abstained", "citations"):
                    if result.get(key) != source.get(key):
                        raise CacheEvidenceError("Cached response differs from its recorded origin")
                if cache_status == "exact_hit" and row["request"]["question"] != source["question"]:
                    raise CacheEvidenceError("Exact hit changed its question")
            previous_results[run_id] = result
        groups.append({"id": record["id"], "cold": cold, "replays": replays, "queries": queries})
    source_unchanged = _source_integrity(report)
    replays = [row for group in groups for row in group["replays"]]
    queries = [row for group in groups for row in group["queries"]]
    exact_hits = [row for row in replays if row["result"]["cache"]["status"] == "exact_hit"]
    semantic = [row for row in queries if row["result"]["cache"]["status"] == "semantic_hit"]
    eligible_groups = [group for group in groups if len(group["replays"]) == replay_count
                       and all(row["result"]["cache"]["status"] == "exact_hit" for row in group["replays"])]
    correct_groups = [group for group in eligible_groups if group["cold"]["correct"]
                      and all(row["correct"] for row in group["replays"])]
    cold_times = [group["cold"]["end_to_end_ms"] for group in eligible_groups]
    warm_times = [row["end_to_end_ms"] for group in eligible_groups for row in group["replays"]]
    all_rows = [group["cold"] for group in groups] + replays + queries
    observed_tokens = sum(row["audited_usage"]["total_tokens"] for row in all_rows)
    known = all(row["audited_usage"]["known"] for row in all_rows)
    blocked = sum(row["audited_usage"].get("blocked_calls", 0) for row in all_rows)
    by_kind = defaultdict(list)
    for row in queries:
        by_kind[row["kind"]].append(row)
    kind_summary = {}
    for kind, rows in sorted(by_kind.items()):
        hits = [row for row in rows if row["result"]["cache"]["status"] == "semantic_hit"]
        kind_summary[kind] = {"requests": len(rows), "correct": sum(row["correct"] for row in rows),
                              "hits": len(hits), "false_hits": sum(not row["exact_match"] for row in hits),
                              "rejected_candidates": sum(row["result"]["cache"]["rejected_candidates"] for row in rows)}
    correct_speedups = [group["cold"]["end_to_end_ms"] / _median(
        [row["end_to_end_ms"] for row in group["replays"]]) for group in correct_groups
        if _median([row["end_to_end_ms"] for row in group["replays"]]) > 0]
    return {
        "complete": report["status"] == "completed" and complete_coverage and source_unchanged and not blocked,
        "planned_groups": len(planned), "planned_exact_replays": len(planned) * replay_count,
        "planned_semantic_queries": sum(len(group["queries"]) for group in planned),
        "cold_requests": len(groups), "cold_correct": sum(group["cold"]["correct"] for group in groups),
        "cold_incorrect": sum(not group["cold"]["correct"] for group in groups),
        "exact_replay_requests": len(replays), "exact_hits": len(exact_hits),
        "exact_answer_matches": sum(row["exact_match"] for row in exact_hits),
        "exact_hit_rate": _mean_ratio(len(exact_hits), len(replays)),
        "exact_false_hits": sum(not row["exact_match"] for row in exact_hits),
        "exact_false_hit_rate": _mean_ratio(sum(not row["exact_match"] for row in exact_hits), len(exact_hits)),
        "paired_cold_requests": len(cold_times), "cold_p50_ms": _median(cold_times),
        "warm_p50_ms": _median(warm_times),
        "p50_exact_replay_speedup": _mean_ratio(_median(cold_times), _median(warm_times))
        if cold_times and warm_times else None,
        "correct_paired_groups": len(correct_groups),
        "correct_pair_speedup_p50": _median(correct_speedups),
        "semantic_queries": len(queries), "semantic_hits": len(semantic),
        "semantic_false_hits": sum(not row["exact_match"] for row in semantic),
        "semantic_false_hit_rate": _mean_ratio(sum(not row["exact_match"] for row in semantic), len(semantic)),
        "semantic_total_correct": sum(row["correct"] for row in queries),
        "negative_query_hits": sum(not row["reuse_expected"] for row in semantic),
        "rejected_candidates": sum(row["result"]["cache"]["rejected_candidates"] for row in queries),
        "actual_calls": sum(row["audited_usage"]["actual_calls"] for row in all_rows),
        "tokens": observed_tokens if known else None, "observed_tokens": observed_tokens,
        "usage_known": known, "source_unchanged": source_unchanged,
        "by_kind": kind_summary,
        "failed_outputs": sum(row["result"].get("status") in {"failed", "error"} for row in all_rows),
        "latency_scope": "End-to-end service.run including persistence. Ratio of median cold requests to median replays for groups where every planned replay hit; excludes non-hit groups, retains incorrect hits. Not new-query speed or throughput.",
        "correct_pair_scope": "Median per-group cold/warm-median ratio restricted to reference-correct cold and warm outputs; conditional subset with explicit denominator.",
        "negative_scope": "Negative labels mean reuse of the seed answer is not expected; a later cache entry may correctly answer them. False-hit rate uses reference grading, not the label alone.",
        "calls_scope": "Actual adapter inference attempts reconstructed from saved generation/critic responses, including failed calls; no external billing attestation.",
        **cost_summary([row["audited_usage"] for row in all_rows]),
    }
