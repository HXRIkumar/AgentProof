#!/usr/bin/env python3
"""Independent, offline audit of frozen Answer Lab evidence (no runtime imports).

Recomputes reference correctness, physical/logical usage and standard-price costs.
It does not establish model training independence, semantic critic accuracy, or
provider invoice charges. No model, network, credential or database access occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import string
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
FROZEN = {
    "evaluation": (64, "4b2d1c8a6b801175a313bd09bb3e4f2525d5428c68e2aa14beb2262707fdcd99"),
    "development": (18, "93e1310cd634918b76eb86ca648847afe0defc8737b2e196dc5313bf84d14dcf"),
}


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def same(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def check_fields(recorded, computed, label):
    for key, value in computed.items():
        got = recorded.get(key)
        equal = same(got, value)
        if type(got) in (int, float) and type(value) in (int, float):
            equal = math.isclose(got, value, rel_tol=1e-10, abs_tol=1e-10)
        require(key in recorded and equal, f"{label}: mismatch in {key}")


def normalized(text):
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(re.sub(r"\b(?:a|an|the)\b", " ", text).split())


def leaves(value):
    pending, output = [((), value)], {}
    while pending:
        path, item = pending.pop()
        children = item.items() if isinstance(item, dict) else enumerate(item) if isinstance(item, list) else []
        children = list(children)
        if children:
            pending.extend(((*path, key), child) for key, child in children)
        else:
            output[path] = item
    return output


def grade(case, result):
    delivered = result.get("status") in ("accepted", "abstained")
    error = result.get("status") == "error"
    em = f1 = schema = field_accuracy = field_f1 = None
    if case["task"] == "qa":
        text = result.get("answer")
        abstain = result.get("abstained") is True
        valid = abstain or isinstance(text, str) and bool(text.strip())
        em = f1 = 0.0
        if not error and valid and (case["gold"]["answerable"] or abstain):
            tokens = normalized("" if abstain else text).split()
            targets = [normalized(answer).split() for answer in case["gold"]["answers"] if normalized(answer)] or [[]]
            for target in targets:
                em = max(em, float(tokens == target))
                common = sum(min(tokens.count(word), target.count(word)) for word in set(tokens))
                score = 2 * common / (len(tokens) + len(target)) if tokens and target else float(tokens == target)
                f1 = max(f1, score)
        correct = em == 1
    else:
        require(case["task"] == "extraction", "Unsupported task")
        prediction, expected = result.get("data"), case["gold"]["data"]
        schema = not error and not result.get("abstained") and jsonschema.Draft202012Validator(
            case["request"]["schema"]).is_valid(prediction)
        wanted = leaves(expected)
        actual = leaves(prediction) if isinstance(prediction, dict) else {}
        matched = sum(path in actual and same(value, actual[path]) for path, value in wanted.items())
        field_accuracy = matched / len(wanted.keys() | actual.keys())
        field_f1 = 2 * matched / (len(wanted) + len(actual)) if wanted or actual else 0
        correct = bool(schema and same(prediction, expected))
    return {"correct": bool(correct and delivered), "answer_correct": bool(correct),
            "delivered": delivered, "exact_match": em, "token_f1": f1,
            "schema_valid": schema, "field_accuracy": field_accuracy, "field_f1": field_f1}


def usage(records):
    """records are (raw response, reused initial) tuples; no stored usage trusted."""
    sent = [(r, reuse) for r, reuse in records if r.get("request_sent", True)]
    blocked = len(records) - len(sent)
    for response, _ in records:
        require(type(response.get("request_sent", True)) is bool, "Invalid request-sent flag")
        for key in ("prompt_tokens", "completion_tokens"):
            value = response.get(key)
            require(value is None or type(value) is int and value >= 0, "Invalid token count")
            if response.get("request_sent", True) and response.get("usage_known"):
                require(value is not None, "Known response missing token usage")
        if not response.get("request_sent", True):
            require(not response.get("billing") and not response.get("prompt_tokens")
                    and not response.get("completion_tokens"), "Blocked response claims billed usage")
    physical = [(r, reuse) for r, reuse in sent if not reuse]
    tokens = lambda rows, key: sum(r.get(key) or 0 for r, _ in rows)
    total = lambda rows: tokens(rows, "prompt_tokens") + tokens(rows, "completion_tokens")
    out = {"calls": len(sent), "actual_calls": len(physical), "reused_calls": len(sent)-len(physical),
           "prompt_tokens": tokens(sent, "prompt_tokens"), "completion_tokens": tokens(sent, "completion_tokens"),
           "total_tokens": total(sent), "actual_total_tokens": total(physical),
           "known": all(r.get("usage_known") is True for r, _ in sent),
           "unknown_calls": sum(r.get("usage_known") is not True for r, _ in sent)}
    paid = [(r, reuse) for r, reuse in sent if r.get("billing") is not None]
    for response, _ in paid:
        bill = response["billing"]
        require(bill.get("provider") == "openai" and response.get("model") == "gpt-5.4-mini-2026-03-17",
                "Unrecognized priced provider/model")
        require(bill.get("pricing_version") == "openai-gpt-5.4-mini-standard-2026-11-12", "Unrecognized price version")
        for key in ("accounted_usd", "reserved_usd"):
            require(type(bill.get(key)) in (int, float) and math.isfinite(bill[key]) and bill[key] >= 0,
                    "Invalid reservation cost")
        if bill.get("state") == "settled":
            require(response.get("usage_known") is True, "Settled cost lacks observed usage")
            estimate = (response["prompt_tokens"] * 750 + response["completion_tokens"] * 4500) / 1e9
            check_fields(bill, {"estimated_cost_usd": estimate, "accounted_usd": estimate,
                               "reported_prompt_tokens": response["prompt_tokens"],
                               "reported_completion_tokens": response["completion_tokens"]}, "Billing")
            require(bill["accounted_usd"] <= bill["reserved_usd"] + 1e-10, "Settlement exceeds reservation")
    if paid or blocked:
        actual_paid = [(r, reuse) for r, reuse in paid if not reuse]
        for prefix, rows in (("", paid), ("actual_", actual_paid)):
            known = all(r["billing"].get("state") == "settled" for r, _ in rows)
            out[prefix + "paid_calls"] = len(rows)
            out[prefix + "cost_known"] = known
            out[prefix + "estimated_cost_usd"] = sum(r["billing"]["estimated_cost_usd"] for r, _ in rows) if known else None
            out[prefix + "accounted_cost_usd"] = sum(r["billing"]["accounted_usd"] for r, _ in rows)
        out["blocked_calls"] = blocked
    return out


def result_records(result):
    records = []
    for index, attempt in enumerate(result["attempts"]):
        require(isinstance(attempt.get("generation"), dict), "Missing raw generation")
        records.append((attempt["generation"], index == 0))
        if attempt.get("critic_response") is not None:
            records.append((attempt["critic_response"], False))
    require(not result.get("cache", {}).get("verification"), "Quality study contains cache verification")
    return records


def audit_report(report, suite_bytes, *, allow_development=False, source_root=None):
    suite = json.loads(suite_bytes)
    split = suite["split"]
    require(split == "evaluation" or allow_development and split == "development", "Development evidence is not final evaluation")
    count, frozen_hash = FROZEN[split]
    require(hashlib.sha256(suite_bytes).hexdigest() == frozen_hash, "Suite differs from frozen reference bytes")
    cases = {case["id"]: case for case in suite["cases"]}
    require(len(cases) == len(suite["cases"]) == count, "Frozen suite coverage mismatch")
    require(report["status"] == "completed" and report["summary"].get("complete") is True,
            "Only completed studies can pass this audit")
    require(report.get("source_unchanged") is True, "Runtime changed during study")
    require(report["suite"]["sha256"] == frozen_hash and report["suite"]["split"] == split,
            "Recorded suite identity mismatch")
    ids = report["suite"]["case_ids"]
    require(len(ids) == count and set(ids) == set(cases) and report["suite"]["case_count"] == count,
            "Recorded case coverage mismatch")
    require(report["suite"]["case_manifest_sha256"] == {key: digest(value) for key, value in cases.items()},
            "Case manifest differs from frozen suite")
    strategies = report["configuration"]["strategies"]
    require(set(strategies) == {"baseline", "validated", "adaptive"} and len(strategies) == 3,
            "Three paired policies required")
    require(report["configuration"]["cache_enabled"] is False, "Quality study must disable cache")
    initials = {row["case_id"]: row["response"] for row in report["initial_generations"]}
    require(len(initials) == len(report["initial_generations"]) == count and set(initials) == set(cases),
            "Shared initial coverage mismatch")
    physical = [(value, False) for value in initials.values()]
    grouped = {strategy: [] for strategy in strategies}
    seen, initial_snapshots = set(), {}
    for row in report["trials"]:
        key = row["case_id"], row["strategy"]
        require(key not in seen and key[0] in cases and key[1] in grouped, "Duplicate or unexpected trial")
        seen.add(key)
        case = cases[key[0]]
        require(row["case"] == case, "Trial snapshot differs from frozen case")
        initial, result = row["initial_result"], row["result"]
        require(initial_snapshots.setdefault(key[0], digest(initial)) == digest(initial), "Different initial results across arms")
        require(initial["attempts"][0]["generation"] == initials[key[0]], "Initial result binding mismatch")
        require(result["attempts"][0]["generation"] == initials[key[0]], "Policy first generation was not shared")
        if key[1] == "baseline":
            require(result == initial, "Baseline differs from initial result")
        final_grade, first_grade = grade(case, result), grade(case, initial)
        check_fields(row["grade"], final_grade, "Stored grade")
        check_fields(row["initial_grade"], first_grade, "Stored initial grade")
        records = result_records(result)
        measured = usage(records)
        require(not measured.get("blocked_calls"), "Completed study contains unsent requests")
        check_fields(result["usage"], measured, "Trial usage")
        physical.extend((response, False) for response, reused in records if not reused)
        grouped[key[1]].append((final_grade, first_grade, records))
    require(len(seen) == count * 3, "Incomplete policy coverage")
    reservation_ids = [r["billing"].get("reservation_id") for r, _ in physical if r.get("billing")]
    require(all(reservation_ids) and len(set(reservation_ids)) == len(reservation_ids) if reservation_ids else True,
            "Repeated physical paid reservation ID")
    actual = usage(physical)
    require(not actual.get("blocked_calls"), "Unsent initial requests cannot complete a study")
    actual_summary = {"calls": actual["calls"], "observed_tokens": actual["total_tokens"],
                      "total_tokens": actual["total_tokens"] if actual["known"] else None,
                      "usage_known": actual["known"], "shared_initial_generations": count}
    for key in ("paid_calls", "blocked_calls", "estimated_cost_usd", "accounted_cost_usd", "cost_known"):
        if key in actual:
            actual_summary[key] = actual[key]
    check_fields(report["actual_usage"], actual_summary, "Physical study usage")
    summaries = {}
    for strategy, rows in grouped.items():
        aggregate = usage([record for _, _, records in rows for record in records])
        correct = sum(final["correct"] for final, _, _ in rows)
        answers = sum(final["answer_correct"] for final, _, _ in rows)
        summary = {"trials": count, "correct": correct, "success_rate": correct / count,
                   "answer_correct": answers, "answer_accuracy": answers / count,
                   "calls": aggregate["calls"], "observed_tokens": aggregate["total_tokens"],
                   "total_tokens": aggregate["total_tokens"] if aggregate["known"] else None,
                   "usage_known": aggregate["known"],
                   "tokens_per_correct": aggregate["total_tokens"] / correct if correct and aggregate["known"] else None,
                   "recovered": sum(not first["answer_correct"] and final["correct"] for final, first, _ in rows),
                   "regressed": sum(first["correct"] and not final["correct"] for final, first, _ in rows)}
        for key in ("exact_match", "token_f1", "field_accuracy", "field_f1", "schema_valid"):
            values = [final[key] for final, _, _ in rows if final[key] is not None]
            summary["schema_valid_rate" if key == "schema_valid" else key] = sum(values)/len(values) if values else None
        for key in ("paid_calls", "actual_paid_calls", "blocked_calls", "estimated_cost_usd", "accounted_cost_usd", "cost_known"):
            if key in aggregate:
                summary[key] = aggregate[key]
        if "cost_known" in aggregate:
            summary["cost_per_correct_usd"] = aggregate["estimated_cost_usd"] / correct if correct and aggregate["cost_known"] else None
        check_fields(report["summary"]["strategies"][strategy], summary, "Strategy " + strategy)
        summaries[strategy] = summary
    sources = report["configuration"]["source_files"]
    require(bool(sources), "Missing source manifest")
    for name, sha in sources.items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and re.fullmatch(r"[0-9a-f]{64}", sha), "Invalid source manifest")
        if source_root:
            require(hashlib.sha256((Path(source_root) / name).read_bytes()).hexdigest() == sha,
                    "Frozen source mismatch: " + name)
    return {"passed": True, "study_complete": True, "split": split, "case_count": count,
            "suite_sha256": frozen_hash, "paired_trials": len(seen), "strategies": summaries,
            "actual_usage": actual_summary, "unique_paid_reservations": len(reservation_ids),
            "runtime_configuration": report["configuration"]["runtime"],
            "source_manifest_sha256": digest(sources), "source_files": sources,
            "source_files_checked_on_disk": source_root is not None,
            "scope": "Independent frozen-case grading and raw-response usage/cost audit; no inference or production grader imports. Standard-price estimates are not invoices. Does not validate bootstrap intervals or semantic critic labels."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", type=Path, default=ROOT / "examples/answer-suite-v1/evaluation.json")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--allow-development", action="store_true")
    args = parser.parse_args()
    require(not args.output.exists(), "Audit output already exists")
    raw = args.report.read_bytes()
    try:
        audited = audit_report(json.loads(raw), args.suite.read_bytes(),
                               allow_development=args.allow_development, source_root=args.source_root)
    except (AuditError, KeyError, TypeError, ValueError, OSError) as exc:
        audited = {"passed": False, "error_type": type(exc).__name__,
                   "error": str(exc) if isinstance(exc, AuditError) else "Evidence has invalid or missing fields"}
    audited.update(format="answer-evidence-audit-v1", report_sha256=hashlib.sha256(raw).hexdigest(),
                   audited_at=datetime.now(UTC).isoformat(), auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with args.output.open("x") as stream:
        json.dump(audited, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": audited["passed"], "output": str(args.output)}))
    return 0 if audited["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
