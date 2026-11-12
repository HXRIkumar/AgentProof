"""Offline reference grading for Answer Lab. Gold labels never reach the runtime.

QA normalization follows the published SQuAD v2 definition. Runtime validation
scores and reference correctness are deliberately different measurements.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
import string
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import jsonschema

STRATEGIES = ("baseline", "validated", "adaptive")


def evidence_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_answer(text: str) -> str:
    lowered = text.lower()
    no_punctuation = "".join(c for c in lowered if c not in string.punctuation)
    no_articles = re.sub(r"\b(a|an|the)\b", " ", no_punctuation)
    return " ".join(no_articles.split())


def qa_scores(prediction: str, references: list[str]) -> tuple[float, float]:
    references = [answer for answer in references if normalize_answer(answer)] or [""]
    prediction_tokens = normalize_answer(prediction).split()
    exact, f1 = 0.0, 0.0
    for answer in references:
        target_tokens = normalize_answer(answer).split()
        exact = max(exact, float(normalize_answer(prediction) == normalize_answer(answer)))
        if not target_tokens or not prediction_tokens:
            candidate_f1 = float(target_tokens == prediction_tokens)
        else:
            overlap = sum((Counter(target_tokens) & Counter(prediction_tokens)).values())
            candidate_f1 = 2 * overlap / (len(target_tokens) + len(prediction_tokens))
        f1 = max(f1, candidate_f1)
    return exact, f1


def typed_equal(left: Any, right: Any) -> bool:
    """JSON booleans are not numbers; integral float and int compare as JSON numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(typed_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def flatten_fields(value: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf paths preserve array order; empty containers count as actual fields."""
    fields: dict[str, Any] = {}
    if isinstance(value, dict) and value:
        for key, child in value.items():
            fields.update(flatten_fields(child, f"{prefix}/{key}"))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            fields.update(flatten_fields(child, f"{prefix}/{index}"))
    else:
        fields[prefix or "/"] = value
    return fields


def grade_result(case: dict, result: dict) -> dict:
    """Grade answer content and successful delivery separately; no implicit abstentions."""
    task = case["task"]
    delivered = result.get("status") in {"accepted", "abstained"}
    error = result.get("status") == "error"
    schema_valid = None
    field_accuracy = field_precision = field_recall = field_f1 = None
    exact_match = token_f1 = None
    relevant_ids = set(case["gold"].get("relevant_source_ids", []))
    selected_ids = {
        item.get("source_id") for item in result.get("retrieval", {}).get("selected", [])
    }
    retrieval_recall = len(relevant_ids & selected_ids) / len(relevant_ids) if relevant_ids else None
    if task == "qa":
        abstained = result.get("abstained") is True
        text = result.get("answer")
        explicit_output = abstained or (isinstance(text, str) and bool(text.strip()))
        if error or not explicit_output or (not case["gold"]["answerable"] and not abstained):
            exact_match, token_f1 = 0.0, 0.0
        else:
            prediction = "" if abstained else text
            exact_match, token_f1 = qa_scores(prediction, case["gold"]["answers"])
        answer_correct = exact_match == 1.0
    elif task == "extraction":
        prediction = result.get("data")
        expected = case["gold"]["data"]
        schema_valid = False
        if not error and not result.get("abstained"):
            try:
                jsonschema.Draft202012Validator(case["request"]["schema"]).validate(prediction)
                schema_valid = True
            except jsonschema.ValidationError:
                pass
        gold_fields = flatten_fields(expected)
        pred_fields = flatten_fields(prediction) if isinstance(prediction, dict) else {}
        correct_fields = sum(
            key in pred_fields and typed_equal(value, pred_fields[key])
            for key, value in gold_fields.items()
        )
        field_recall = correct_fields / len(gold_fields) if gold_fields else 0.0
        field_precision = correct_fields / len(pred_fields) if pred_fields else 0.0
        field_accuracy = correct_fields / len(set(gold_fields) | set(pred_fields))
        field_f1 = (
            2 * field_precision * field_recall / (field_precision + field_recall)
            if field_precision + field_recall else 0.0
        )
        answer_correct = bool(schema_valid and typed_equal(prediction, expected))
    else:
        raise ValueError(f"Unsupported task: {task}")
    return {
        "correct": bool(answer_correct and delivered), "answer_correct": bool(answer_correct),
        "delivered": delivered, "exact_match": exact_match, "token_f1": token_f1,
        "schema_valid": schema_valid, "field_accuracy": field_accuracy,
        "field_precision": field_precision, "field_recall": field_recall, "field_f1": field_f1,
        "retrieval_recall": retrieval_recall,
    }


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def mean(values) -> float | None:
    numbers = [value for value in values if value is not None]
    return statistics.fmean(numbers) if numbers else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def paired_interval(deltas: list[float], seed: int = 20261112, draws: int = 2000):
    """Percentile bootstrap over paired cases, not individual repeat observations."""
    if not deltas:
        return None
    rng = random.Random(seed)
    estimates = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas))) for _ in range(draws))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def strategy_summary(trials: list[dict]) -> dict:
    count = len(trials)
    correct = sum(t["grade"]["correct"] for t in trials)
    answer_correct = sum(t["grade"]["answer_correct"] for t in trials)
    initial_failures = sum(not t["initial_grade"]["answer_correct"] for t in trials)
    initial_successes = sum(t["initial_grade"]["correct"] for t in trials)
    initial_answer_successes = sum(t["initial_grade"]["answer_correct"] for t in trials)
    recovered = sum(
        not t["initial_grade"]["answer_correct"] and t["grade"]["correct"] for t in trials
    )
    regressed = sum(
        t["initial_grade"]["correct"] and not t["grade"]["correct"] for t in trials
    )
    answer_regressed = sum(
        t["initial_grade"]["answer_correct"] and not t["grade"]["answer_correct"] for t in trials
    )
    task_recovered = sum(
        not t["initial_grade"]["correct"] and t["grade"]["correct"] for t in trials
    )
    accepted = sum(t["result"].get("status") in {"accepted", "abstained"} for t in trials)
    accepted_incorrect = sum(
        t["result"].get("status") in {"accepted", "abstained"}
        and not t["grade"]["answer_correct"] for t in trials
    )
    usage_known = all(t["result"].get("usage", {}).get("known") is True for t in trials)
    observed_tokens = sum(t["result"].get("usage", {}).get("total_tokens") or 0 for t in trials)
    calls = sum(t["result"].get("usage", {}).get("calls") or 0 for t in trials)
    retries = sum(max(0, len(t["result"].get("attempts", [])) - 1) for t in trials)
    latencies = [t["result"].get("latency_ms", 0.0) for t in trials]
    cache_statuses = Counter(t["result"].get("cache", {}).get("status", "unknown") for t in trials)
    return {
        "trials": count, "correct": correct, "success_rate": ratio(correct, count),
        "answer_correct": answer_correct, "answer_accuracy": ratio(answer_correct, count),
        "exact_match": mean(t["grade"]["exact_match"] for t in trials),
        "token_f1": mean(t["grade"]["token_f1"] for t in trials),
        "field_accuracy": mean(t["grade"]["field_accuracy"] for t in trials),
        "field_f1": mean(t["grade"]["field_f1"] for t in trials),
        "schema_valid_rate": mean(t["grade"]["schema_valid"] for t in trials),
        "retrieval_recall": mean(t["grade"].get("retrieval_recall") for t in trials),
        "recovered": recovered, "initial_failures": initial_failures,
        "recovery_rate": ratio(recovered, initial_failures),
        "regressed": regressed, "initial_successes": initial_successes,
        "regression_rate": ratio(regressed, initial_successes),
        "answer_regressed": answer_regressed, "initial_answer_successes": initial_answer_successes,
        "answer_regression_rate": ratio(answer_regressed, initial_answer_successes),
        "task_recovered": task_recovered, "initial_task_failures": count - initial_successes,
        "task_recovery_rate": ratio(task_recovered, count - initial_successes),
        "accepted": accepted, "accepted_incorrect": accepted_incorrect,
        "false_accept_rate": ratio(accepted_incorrect, accepted),
        "retries": retries, "retries_per_query": ratio(retries, count),
        "calls": calls, "calls_per_query": ratio(calls, count),
        "usage_known": usage_known, "observed_tokens": observed_tokens,
        "total_tokens": observed_tokens if usage_known else None,
        "tokens_per_correct": ratio(observed_tokens, correct) if usage_known else None,
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "cache_statuses": dict(cache_statuses),
        "error_count": sum(t["result"].get("status") == "error" for t in trials),
    }


def comparison_summary(trials: list[dict], reference: str, candidate: str) -> dict:
    grouped = defaultdict(dict)
    for trial in trials:
        if trial["strategy"] in {reference, candidate}:
            grouped[trial["case_id"]][trial["strategy"]] = trial
    paired = [rows for rows in grouped.values() if len(rows) == 2]
    success_deltas = [
        float(rows[candidate]["grade"]["correct"]) - float(rows[reference]["grade"]["correct"])
        for rows in paired
    ]
    f1_deltas = [
        rows[candidate]["grade"]["token_f1"] - rows[reference]["grade"]["token_f1"]
        for rows in paired if rows[reference]["task"] == "qa"
    ]
    return {
        "reference": reference, "candidate": candidate, "paired_cases": len(paired),
        "success_delta": mean(success_deltas), "success_delta_ci95": paired_interval(success_deltas),
        "token_f1_delta": mean(f1_deltas), "token_f1_delta_ci95": paired_interval(f1_deltas),
        "improved_cases": sum(delta > 0 for delta in success_deltas),
        "regressed_cases": sum(delta < 0 for delta in success_deltas),
        "bootstrap_unit": "case", "bootstrap_draws": 2000, "bootstrap_seed": 20261112,
    }


def summarize_report(report: dict, *, recompute: bool = True) -> dict:
    trials = report["trials"]
    planned = report["suite"]["case_count"] * len(report["configuration"]["strategies"])
    seen = set()
    expected_ids = report["suite"].get("case_ids", [])
    if (len(expected_ids) != report["suite"]["case_count"]
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError("Suite case IDs must match declared coverage")
    strategies = report["configuration"]["strategies"]
    if (not strategies or "baseline" not in strategies
            or len(set(strategies)) != len(strategies) or set(strategies) - set(STRATEGIES)):
        raise ValueError("Unique supported strategies including baseline are required")
    frozen_case_hashes = report["suite"].get("case_manifest_sha256", {})
    if set(frozen_case_hashes) != set(expected_ids):
        raise ValueError("Frozen case manifest does not match declared coverage")
    initial_generations = {}
    for initial in report.get("initial_generations", []):
        if initial["case_id"] in initial_generations or initial["case_id"] not in expected_ids:
            raise ValueError("Initial generations must be unique and belong to the suite")
        initial_generations[initial["case_id"]] = initial["response"]
    initial_snapshots = {}
    for trial in trials:
        key = trial["case_id"], trial["strategy"]
        if key in seen:
            raise ValueError("Duplicate case/strategy evidence")
        seen.add(key)
        if trial["strategy"] not in report["configuration"]["strategies"]:
            raise ValueError("Unexpected strategy in report")
        if trial["case_id"] not in expected_ids or trial["case"]["id"] != trial["case_id"]:
            raise ValueError("Unexpected case in report")
        if trial["task"] != trial["case"]["task"]:
            raise ValueError("Trial task does not match its reference case")
        latency = trial["result"].get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            raise TypeError("Trial latency must be a finite nonnegative number")
        if not math.isfinite(latency) or latency < 0:
            raise ValueError("Trial latency must be a finite nonnegative number")
        if evidence_digest(trial["case"]) != frozen_case_hashes[trial["case_id"]]:
            raise ValueError("Trial reference case differs from the frozen case manifest")
        initial_result = trial["initial_result"]
        initial_hash = evidence_digest(initial_result)
        if initial_snapshots.setdefault(trial["case_id"], initial_hash) != initial_hash:
            raise ValueError("Policies do not share an identical initial result")
        attempts = initial_result.get("attempts", [])
        if (not attempts or trial["case_id"] not in initial_generations
                or attempts[0].get("generation") != initial_generations[trial["case_id"]]):
            raise ValueError("Initial result is not bound to its recorded model generation")
        if trial["strategy"] == "baseline" and evidence_digest(trial["result"]) != initial_hash:
            raise ValueError("Baseline result differs from the shared initial result")
        if recompute:
            trial["grade"] = grade_result(trial["case"], trial["result"])
            trial["initial_grade"] = grade_result(trial["case"], trial["initial_result"])
    complete = (report["status"] == "completed" and len(trials) == planned
                and report.get("source_unchanged", True))
    by_strategy = {
        strategy: strategy_summary([t for t in trials if t["strategy"] == strategy])
        for strategy in report["configuration"]["strategies"]
    }
    by_task = {
        task: {
            strategy: strategy_summary(
                [t for t in trials if t["task"] == task and t["strategy"] == strategy]
            ) for strategy in report["configuration"]["strategies"]
        } for task in sorted({t["task"] for t in trials})
    }
    qa_by_answerability = {
        category: {
            strategy: strategy_summary(
                [t for t in trials if t["task"] == "qa" and t["category"] == category
                 and t["strategy"] == strategy]
            ) for strategy in report["configuration"]["strategies"]
        } for category in ("answerable", "unanswerable")
    }
    comparisons = [comparison_summary(trials, "baseline", candidate)
                   for candidate in report["configuration"]["strategies"] if candidate != "baseline"]
    return {
        "complete": complete, "planned_trials": planned, "finished_trials": len(trials),
        "strategies": by_strategy, "by_task": by_task, "qa_by_answerability": qa_by_answerability,
        "comparisons": comparisons,
        "definitions": {
            "success_rate": "Exact QA reference match or exact schema-valid extraction AND delivered status accepted/abstained.",
            "answer_accuracy": "Reference answer correctness, independent of whether runtime accepted it.",
            "exact_match": "SQuAD normalized exact match; QA only. Malformed empty outputs are not abstentions.",
            "token_f1": "Maximum token F1 over reference spans; QA only; not embedding similarity.",
            "field_accuracy": "Correct typed leaf fields / union of predicted and expected field paths, preserving array order.",
            "recovery_rate": "Initially reference-incorrect answers corrected and delivered / initially incorrect answers.",
            "regression_rate": "Initially correctly delivered tasks not correctly delivered at end / initially correctly delivered tasks.",
            "answer_regression_rate": "Initially reference-correct answers becoming reference-incorrect / initially reference-correct answers, independent of delivery.",
            "false_accept_rate": "Reference-incorrect accepted outputs / all accepted outputs, including explicit abstentions.",
            "cost": "Logical standalone cost per policy includes shared initial generation. Actual study calls are tracked separately. Unknown usage blocks token-efficiency claims.",
            "latency": "Logical cold end-to-end latency including shared initial generation. Hardware development activity may overlap.",
            "intervals": "Paired percentile case bootstrap, 2000 draws. Small public-derived subset, not general accuracy or unseen training data.",
        },
    }


def load_suite(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    suite = json.loads(raw)
    ids = [case["id"] for case in suite["cases"]]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("Suite must contain unique non-empty cases")
    for case in suite["cases"]:
        if "gold" in case["request"]:
            raise ValueError("Gold labels must not be present in runtime request")
        if case["task"] == "extraction":
            jsonschema.Draft202012Validator.check_schema(case["request"]["schema"])
            jsonschema.validate(case["gold"]["data"], case["request"]["schema"])
    return suite, hashlib.sha256(raw).hexdigest()
