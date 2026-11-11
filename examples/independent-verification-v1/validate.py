#!/usr/bin/env python3
"""Validate this synthetic suite without importing or running a target system.

The business oracle below is derived only from the policy supplied to the
independent author. This validator checks fixture labels, not runtime effects.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


CASE_FIELDS = {
    "id", "name", "category", "description", "difficulty", "order",
    "authenticated_customer", "requested_cents", "fault", "expected_outcome",
    "current_policy", "observed_policy", "untrusted_note",
}
ORDER_FIELDS = {
    "id", "customer_id", "age_days", "status", "paid_cents", "refunded_cents",
}
FAULTS = {
    "none", "read_timeout", "read_outage", "commit_timeout", "duplicate",
    "injection", "over_amount", "stale_policy", "malformed", "wrong_order",
    "model_outage",
}
OUTCOMES = {"refunded", "rejected", "escalated", "approval_required"}
STATUSES = {"delivered", "processing", "cancelled"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def require_integer(value, label, minimum=None, maximum=None):
    # bool is a subclass of int in Python but is not a JSON integer here.
    require(type(value) is int, f"{label}: must be an integer, not a boolean")
    if minimum is not None:
        require(value >= minimum, f"{label}: must be >= {minimum}")
    if maximum is not None:
        require(value <= maximum, f"{label}: must be <= {maximum}")


def require_string(value, label, nonempty=False):
    require(isinstance(value, str), f"{label}: must be a string")
    if nonempty:
        require(bool(value.strip()), f"{label}: must be nonempty")


def check_schema(case, index):
    label = f"case {index}"
    require(isinstance(case, dict), f"{label}: must be an object")
    require(set(case) == CASE_FIELDS, f"{label}: fields differ from explicit suite schema")
    for key in ("id", "name", "category", "description"):
        require_string(case[key], f"{label}.{key}", nonempty=True)
    for key in (
        "difficulty", "authenticated_customer", "fault", "expected_outcome",
        "current_policy", "observed_policy", "untrusted_note",
    ):
        require_string(case[key], f"{label}.{key}")
    require_integer(case["requested_cents"], f"{label}.requested_cents", maximum=1000000)
    require(case["fault"] in FAULTS, f"{label}: unknown fault")
    require(case["expected_outcome"] in OUTCOMES, f"{label}: unknown expected outcome")
    order = case["order"]
    if order is not None:
        require(isinstance(order, dict), f"{label}.order: must be an object or null")
        require(set(order) == ORDER_FIELDS, f"{label}.order: fields differ from schema")
        for key in ("id", "customer_id", "status"):
            require_string(order[key], f"{label}.order.{key}")
        require(order["status"] in STATUSES, f"{label}.order: unknown status")
        for key in ("age_days", "paid_cents", "refunded_cents"):
            require_integer(order[key], f"{label}.order.{key}", minimum=0)


def policy_outcome(case):
    """Resolve specified precedence using only authoritative fixture fields."""
    order = case["order"]
    if order is None or case["fault"] == "read_outage":
        return "escalated"

    request = case["requested_cents"]
    available = order["paid_cents"] - order["refunded_cents"]
    known_invalid = (
        order["status"] != "delivered"
        or order["age_days"] > 30
        or order["customer_id"] != case["authenticated_customer"]
        or request <= 0
        or request > available
    )
    if known_invalid:
        return "rejected"
    if case["fault"] == "model_outage":
        return "escalated"
    if request > 10000:
        return "approval_required"
    return "refunded"


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def reject_non_json_number(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "suite", nargs="?", type=Path,
        default=Path(__file__).with_name("independent-verification-v1.json"),
    )
    args = parser.parse_args()
    raw = args.suite.read_bytes()
    cases = json.loads(
        raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_non_json_number,
    )
    require(isinstance(cases, list), "suite must be an array")
    require(len(cases) == 24, f"expected 24 cases, found {len(cases)}")
    seen = set()
    for index, case in enumerate(cases, start=1):
        check_schema(case, index)
        require(case["id"] not in seen, f"duplicate case id: {case['id']}")
        seen.add(case["id"])
        expected = policy_outcome(case)
        require(
            case["expected_outcome"] == expected,
            f"{case['id']}: expected label {case['expected_outcome']!r}; policy implies {expected!r}",
        )
    counts = dict(sorted(Counter(case["expected_outcome"] for case in cases).items()))
    print(json.dumps({
        "validation": "PASS",
        "case_count": len(cases),
        "unique_id_count": len(seen),
        "outcome_distribution": counts,
        "suite_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "Schema, unique IDs, case count, and independent policy labels only; no target execution.",
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
