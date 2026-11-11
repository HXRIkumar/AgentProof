"""One scientific contrast: guarded proposal budgets one versus three.

Separate from the release gate: both arms keep all application safety controls.
Checkpoints preserve completed trials; interrupted trials are never resumed.
"""

import hashlib
import json
import math
import os
import platform
import random
import subprocess
import tempfile
import time
import uuid
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

from .engine import Engine, EngineOptions, now
from .grading import grade
from .models import Scenario
from .providers import PROMPT_HASH, provider_for
from .scenarios import SCENARIOS, SUITE_VERSION
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
CHALLENGE_SHA256 = "77bfa60553343acdff60c1320b5a27650234799152a7d18561a6d88b9d707475"
ARMS = {"A1": {"max_proposals": 1}, "A3": {"max_proposals": 3}}
FORMAT = "agentproof-budget-ablation-v1"
REPEATS = 2


class AblationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_fingerprint():
    h = hashlib.sha256()
    paths = sorted(Path(__file__).parent.glob("*.py")) + [ROOT / "scripts" / "ablate.py"]
    for path in paths:
        h.update(path.name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def load_suites():
    raw = (ROOT / "examples" / "challenge-suite-v1.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CHALLENGE_SHA256:
        raise AblationError("The frozen challenge file changed; start a separately versioned study")
    challenge = [Scenario.model_validate(s) for s in json.loads(raw)]
    suites = []
    for name, suite_version, cases in (
        ("original", SUITE_VERSION, SCENARIOS),
        ("challenge", "challenge-suite-v1", challenge),
    ):
        scenarios = [case.model_dump() for case in cases]
        suites.append(
            {
                "id": name,
                "version": suite_version,
                "scenarios": scenarios,
                "sha256": digest(scenarios),
                "file_sha256": CHALLENGE_SHA256 if name == "challenge" else None,
            }
        )
    return suites


def make_schedule(suites, seed):
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise AblationError("seed must be a nonnegative 32-bit integer")
    rng = random.Random(seed)
    cases = [(suite["id"], case["id"]) for suite in suites for case in suite["scenarios"]]
    first_arm = {case: rng.randrange(2) for case in cases}
    schedule = []
    for repeat in range(REPEATS):
        ordered = cases.copy()
        rng.shuffle(ordered)
        for suite_id, scenario_id in ordered:
            arms = (
                ("A1", "A3")
                if (first_arm[(suite_id, scenario_id)] + repeat) % 2 == 0
                else ("A3", "A1")
            )
            for arm in arms:
                schedule.append(
                    {
                        "index": len(schedule),
                        "suite_id": suite_id,
                        "scenario_id": scenario_id,
                        "repeat": repeat + 1,
                        "arm": arm,
                    }
                )
    return schedule


def provider_configuration(adapter, provider):
    return {
        "provider": provider,
        "model": adapter.model,
        "model_revision": os.getenv("AGENTPROOF_MODEL_REVISION", "unrecorded")
        if provider == "openai"
        else "scripted-fixture-v1",
        "temperature": 0,
        "timeout_seconds": getattr(adapter, "timeout", None),
        "max_tokens": getattr(adapter, "max_tokens", None),
        "disable_thinking": getattr(adapter, "disable_thinking", False),
        "base_url_sha256": hashlib.sha256(getattr(adapter, "base_url", "").encode()).hexdigest(),
    }


def atomic_json(path: Path, document):
    """Replace a complete JSON file atomically; never expose a half-written checkpoint."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_ablation(output_dir, *, provider="scripted", seed=20261112, provider_factory=None):
    """Execute a new study. This never consumes or resumes an existing checkpoint."""
    if provider not in ("scripted", "openai"):
        raise AblationError("Unknown provider")
    factory = provider_factory or provider_for
    adapter = factory(provider)
    configuration = provider_configuration(adapter, provider)
    if provider == "openai":
        if not getattr(adapter, "is_loopback", False):
            raise AblationError("This study supports only free local inference endpoints")
        if configuration["model_revision"] in ("", "unrecorded"):
            raise AblationError("Record AGENTPROOF_MODEL_REVISION before live inference")
    suites = load_suites()
    schedule = make_schedule(suites, seed)
    source_hash = source_fingerprint()
    config_hash = digest(configuration)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    store = Store(directory / "ledger.sqlite3")
    try:
        revision = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    except subprocess.CalledProcessError:
        revision, dirty = "unrecorded", True
    document = {
        "format": FORMAT,
        "id": uuid.uuid4().hex,
        "created_at": now(),
        "status": "running",
        "kind": "live local-model budget ablation"
        if provider == "openai"
        else "scripted budget fixture; not model accuracy",
        "configuration": configuration,
        "configuration_sha256": config_hash,
        "source_sha256": source_hash,
        "prompt_hash": PROMPT_HASH,
        "source_revision": revision,
        "working_tree_dirty": dirty,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "packages": {name: version(name) for name in ("langgraph", "httpx", "pydantic")},
            "inference_note": os.getenv("AGENTPROOF_INFERENCE_NOTE", "unrecorded"),
        },
        "arms": json.loads(json.dumps(ARMS)),
        "seed": seed,
        "repeats": REPEATS,
        "suites": suites,
        "schedule": schedule,
        "schedule_sha256": digest(schedule),
        "planned_trials": len(schedule),
        "records": [],
        "active_trial": None,
        "warmup": {"status": "not_started" if provider == "openai" else "not_applicable"},
        "ledger_file": "ledger.sqlite3",
    }
    checkpoint = directory / "raw.json"
    atomic_json(checkpoint, document)
    cases = {(s["id"], c["id"]): Scenario.model_validate(c) for s in suites for c in s["scenarios"]}
    engines = {
        arm: Engine(store, lambda _: adapter, options=EngineOptions(**options))
        for arm, options in ARMS.items()
    }
    started = time.monotonic()
    try:
        if provider == "openai":
            document["warmup"] = {"status": "running", "excluded_from_trial_metrics": True}
            atomic_json(checkpoint, document)
            warmup_start = time.monotonic()
            try:
                _, tokens = adapter.propose(
                    {
                        "order": SCENARIOS[0].order.model_dump(),
                        "authenticated_customer": SCENARIOS[0].authenticated_customer,
                        "requested_cents": SCENARIOS[0].requested_cents,
                        "policy_version": SCENARIOS[0].observed_policy,
                        "retrieved_note": "",
                    }
                )
            except BaseException as exc:
                document["warmup"] = {
                    "status": "interrupted"
                    if isinstance(exc, (KeyboardInterrupt, SystemExit))
                    else "failed",
                    "excluded_from_trial_metrics": True,
                    "model_calls": 1,
                    "reported_tokens": None,
                    "latency_ms": round((time.monotonic() - warmup_start) * 1000, 3),
                }
                raise
            document["warmup"] = {
                "status": "completed",
                "excluded_from_trial_metrics": True,
                "model_calls": 1,
                "reported_tokens": tokens,
                "latency_ms": round((time.monotonic() - warmup_start) * 1000, 3),
            }
            atomic_json(checkpoint, document)
        for item in schedule:
            if source_fingerprint() != source_hash or PROMPT_HASH != document["prompt_hash"]:
                raise AblationError("Source or prompt changed during the study")
            if provider_configuration(factory(provider), provider) != configuration:
                raise AblationError("Provider configuration changed during the study")
            document["active_trial"] = item
            atomic_json(checkpoint, document)
            run = engines[item["arm"]].run(
                cases[(item["suite_id"], item["scenario_id"])], "guarded", provider
            )
            document["records"].append(
                {
                    **item,
                    "run": run,
                    "configuration_sha256": config_hash,
                    "source_sha256": source_hash,
                }
            )
            document["active_trial"] = None
            atomic_json(checkpoint, document)
        # Detect changes during the final trial as well as between earlier trials.
        if (
            source_fingerprint() != source_hash
            or provider_configuration(factory(provider), provider) != configuration
        ):
            raise AblationError("Configuration changed before study completion")
        document["status"] = "completed"
    except (KeyboardInterrupt, SystemExit):
        document["status"] = "interrupted"
        document["error"] = {
            "type": "InterruptedExecution",
            "message": "Partial evidence retained; start a new output directory. Interrupted trials are never resumed.",
        }
    except Exception as exc:  # noqa: BLE001 - keep failed studies inspectable without secret strings
        document["status"] = "failed"
        document["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)
            if isinstance(exc, AblationError)
            else "Study stopped. Preserve this partial evidence and start a new study after fixing the cause.",
        }
    finally:
        document["finished_at"] = now()
        document["duration_seconds"] = round(time.monotonic() - started, 3)
        atomic_json(checkpoint, document)
    return document


def _percentile(values, quantile):
    return sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)] if values else None


def _model_attempt_events(run, scenario):
    """Exclude the known non-network injections, not failed actual HTTP attempts."""
    if run["provider"] != "openai" or scenario.fault == "model_outage":
        return []
    return [
        event
        for event in run["events"]
        if event["name"] == "propose_action"
        and not (scenario.fault == "malformed" and event["detail"]["attempt"] == 1)
    ]


def _usage_gap(event):
    """A known usage field counts only if the provider returned its token tuple."""
    detail = event["detail"]
    diagnostic = detail.get("response_diagnostics")
    if not isinstance(diagnostic, dict):
        return "missing_response_diagnostics"
    if (
        detail.get("error") == "ProviderFailure"
        or diagnostic.get("parse_category") == "not_attempted"
    ):
        return "rejected_response_wrapper"
    if (
        type(diagnostic.get("http_status")) is not int
        or not 200 <= diagnostic["http_status"] < 300
        or diagnostic.get("parse_category")
        not in ("valid", "empty", "invalid_json", "schema_validation")
    ):
        return "unavailable_response_accounting"
    if (
        diagnostic.get("usage_present") is not True
        or diagnostic.get("usage_known") is not True
        or diagnostic.get("usage_status") != "reported"
    ):
        return "unknown_reported_usage"
    return None


def _metrics(runs, scenarios, *, metadata_aware=False):
    gaps = defaultdict(int)
    incomplete_trials = 0
    uncertain_trials = 0
    for run in runs:
        run_gaps = [
            gap
            for event in _model_attempt_events(run, scenarios[run["scenario_id"]])
            if metadata_aware and (gap := _usage_gap(event)) is not None
        ]
        for gap in run_gaps:
            gaps[gap] += 1
        incomplete_trials += bool(run_gaps)
        uncertain_trials += bool(
            run_gaps or (run["model_calls"] > 0 and run["token_usage"] == 0)
        )
    model_calls = sum(r["model_calls"] for r in runs)
    return {
        "trials": len(runs),
        "correct": sum(r["passed"] for r in runs),
        "safe": sum(r["safe"] for r in runs),
        "approval_stops": sum(r["passed"] and r["status"] == "awaiting_approval" for r in runs),
        "completed_refunds": sum(r["passed"] and r["outcome"] == "refunded" for r in runs),
        "eligible_refusals": sum(
            scenarios[r["scenario_id"]].expected_outcome in ("refunded", "approval_required")
            and r["outcome"] in ("rejected", "escalated")
            for r in runs
        ),
        "model_calls": model_calls,
        "proposal_attempts": sum(r["proposal_calls"] for r in runs),
        "reported_tokens": sum(r["token_usage"] for r in runs),
        "model_trials_with_zero_reported_tokens": sum(
            r["model_calls"] > 0 and r["token_usage"] == 0 for r in runs
        ),
        "model_trials_with_uncertain_usage": uncertain_trials,
        "token_usage_coverage": {
            "policy": "not_applicable_no_model_calls"
            if not model_calls
            else "per_response_diagnostics"
            if metadata_aware
            else "legacy_aggregate_only",
            "actual_model_attempts": model_calls,
            "accounted_attempts": model_calls - sum(gaps.values()) if metadata_aware else None,
            "incomplete_attempts": sum(gaps.values()) if metadata_aware else None,
            "trials_with_incomplete_accounting": incomplete_trials if metadata_aware else None,
            "gap_reasons": dict(gaps),
        },
        "retries": sum(r["retries"] for r in runs),
        "p50_ms": _percentile([r["latency_ms"] for r in runs], 0.5),
        "p95_ms": _percentile([r["latency_ms"] for r in runs], 0.95),
    }


def _validate_attempt_accounting(run, case, budget):
    """Counts must agree with recorded attempts, including non-network fault injections."""
    events = run["events"]
    if not isinstance(events, list) or [event["index"] for event in events] != list(
        range(len(events))
    ):
        raise AblationError("Trace events are not a contiguous ordered sequence")
    proposals = [event for event in events if event["name"] == "propose_action"]
    lookups = [event for event in events if event["name"] == "lookup_order"]
    injected = [event for event in events if event["name"] == "inject_provider_fault"]
    corrections = [
        event for event in events if event["name"] == "policy_gate" and event["status"] == "retry"
    ]
    commit_timeouts = [
        event
        for event in events
        if event["name"] == "refund"
        and event["status"] == "error"
        and event["detail"].get("error") == "injected_response_timeout_after_commit"
    ]
    if run["proposal_calls"] != len(proposals) or [
        event["detail"]["attempt"] for event in proposals
    ] != list(range(1, len(proposals) + 1)):
        raise AblationError("Proposal count differs from the recorded attempt trace")
    expected_lookups = 2 if case.fault in ("read_timeout", "read_outage") else 1
    if len(lookups) != expected_lookups or [
        event["detail"]["attempt"] for event in lookups
    ] != list(range(1, expected_lookups + 1)):
        raise AblationError("Lookup attempt trace differs from the fixed guarded recovery policy")
    expected_injections = (
        len(proposals)
        if case.fault == "model_outage"
        else int(case.fault == "malformed" and bool(proposals))
    )
    if len(injected) != expected_injections or any(
        event["detail"].get("network_request") is not False
        or event["detail"].get("fault") != case.fault
        for event in injected
    ):
        raise AblationError("Injected provider-fault accounting is inconsistent")
    expected_model_calls = len(proposals) - len(injected) if run["provider"] == "openai" else 0
    if run["model_calls"] != expected_model_calls:
        raise AblationError("Model-call count differs from actual versus injected attempt events")
    if run["provider"] == "scripted" and run["token_usage"] != 0:
        raise AblationError("Scripted fixtures cannot report inference tokens")
    if run["model_calls"] == 0 and run["token_usage"] != 0:
        raise AblationError("Reported tokens require an actual model request")
    if len(corrections) != max(0, len(proposals) - 1) or len(commit_timeouts) > int(
        case.fault == "commit_timeout"
    ):
        raise AblationError("Retry events differ from the bounded correction policy")
    expected_retries = len(lookups) - 1 + len(corrections) + len(commit_timeouts)
    if run["retries"] != expected_retries or run["retries"] > budget + 1:
        raise AblationError("Retry count differs from the recorded read/proposal/commit attempts")
    for event in events:
        if (
            event["name"] == "policy_gate"
            and "proposal_budget" in event["detail"]
            and (
                type(event["detail"]["proposal_budget"]) is not int
                or event["detail"]["proposal_budget"] != budget
            )
        ):
            raise AblationError("Trace proposal budget differs from the declared arm")


def analyse_ablation(document):
    """Validate the declared contrast and regrade evidence; partial data never supports adoption."""
    try:
        if (
            document["format"] != FORMAT
            or digest(document["arms"]) != digest(ARMS)
            or type(document["repeats"]) is not int
            or document["repeats"] != REPEATS
        ):
            raise AblationError("This analyser supports only the declared A1/A3 two-repeat study")
        suites = document["suites"]
        if suites != load_suites():
            raise AblationError("Suite content differs from the frozen original/challenge sets")
        schedule = make_schedule(suites, document["seed"])
        if digest(document["schedule"]) != digest(schedule) or document[
            "schedule_sha256"
        ] != digest(schedule):
            raise AblationError("Saved schedule is not the balanced declared schedule")
        if document["planned_trials"] != len(schedule):
            raise AblationError("Incorrect planned coverage")
        config = document["configuration"]
        required = {
            "provider",
            "model",
            "model_revision",
            "temperature",
            "timeout_seconds",
            "max_tokens",
            "disable_thinking",
            "base_url_sha256",
        }
        if set(config) != required or document["configuration_sha256"] != digest(config):
            raise AblationError("Invalid shared model configuration")
        if (
            config["provider"] not in ("scripted", "openai")
            or type(config["temperature"]) is not int
            or config["temperature"] != 0
        ):
            raise AblationError("Unsupported provider or generation setting")
        if (
            not isinstance(config["model"], str)
            or not config["model"].strip()
            or type(config["disable_thinking"]) is not bool
        ):
            raise AblationError("Invalid model identity or thinking configuration")
        for fingerprint in (
            document["source_sha256"],
            document["prompt_hash"],
            config["base_url_sha256"],
        ):
            if (
                not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in fingerprint)
            ):
                raise AblationError("Missing or malformed source/prompt/endpoint fingerprint")
        if config["provider"] == "openai":
            if not isinstance(config["model_revision"], str) or config["model_revision"] in (
                "",
                "unrecorded",
            ):
                raise AblationError("Live evidence needs a recorded model revision")
            if (
                type(config["timeout_seconds"]) not in (int, float)
                or not 1 <= config["timeout_seconds"] <= 120
                or type(config["max_tokens"]) is not int
                or not 128 <= config["max_tokens"] <= 2048
            ):
                raise AblationError("Live generation limits are invalid")
            if document["status"] == "completed" and document["warmup"]["status"] != "completed":
                raise AblationError("Completed live study needs its recorded common warm-up")
            warmup = document["warmup"]
            if warmup["status"] in ("completed", "failed", "interrupted"):
                if (
                    type(warmup["model_calls"]) is not int
                    or warmup["model_calls"] != 1
                    or warmup["excluded_from_trial_metrics"] is not True
                ):
                    raise AblationError(
                        "Terminal warm-up needs one recorded excluded request attempt"
                    )
                if (
                    type(warmup["latency_ms"]) not in (int, float)
                    or not math.isfinite(warmup["latency_ms"])
                    or warmup["latency_ms"] < 0
                ):
                    raise AblationError("Warm-up latency is invalid")
                tokens = warmup["reported_tokens"]
                if warmup["status"] == "completed" and (type(tokens) is not int or tokens < 0):
                    raise AblationError(
                        "Completed warm-up needs a nonnegative reported token count"
                    )
                if warmup["status"] != "completed" and tokens is not None:
                    raise AblationError("Failed warm-up token usage must remain unknown")
        cases = {
            (s["id"], c["id"]): Scenario.model_validate(c) for s in suites for c in s["scenarios"]
        }
        groups = defaultdict(list)
        ids = set()
        records = document["records"]
        if len(records) > len(schedule):
            raise AblationError("Too many trials")
        for index, record in enumerate(records):
            item = schedule[index]
            if {key: record[key] for key in item} != item:
                raise AblationError(
                    "Trial records must form an unchanged prefix of the saved schedule"
                )
            if (
                record["configuration_sha256"] != document["configuration_sha256"]
                or record["source_sha256"] != document["source_sha256"]
            ):
                raise AblationError("Mixed configuration or source evidence")
            run, case = record["run"], cases[(item["suite_id"], item["scenario_id"])]
            if run["id"] in ids:
                raise AblationError("Repeated run IDs cannot replace independent executions")
            ids.add(run["id"])
            if (
                run["variant"] != "guarded"
                or run["scenario_id"] != case.id
                or run.get("parent_run_id") is not None
            ):
                raise AblationError("Only planned guarded executions belong in this study")
            if run["engine_options"] != ARMS[item["arm"]]:
                raise AblationError(
                    "Run used the wrong proposal budget or undeclared engine options"
                )
            EngineOptions(**run["engine_options"])
            if (
                run["provider"] != config["provider"]
                or run["model"] != config["model"]
                or run["prompt_hash"] != document["prompt_hash"]
            ):
                raise AblationError("Run provider/model/prompt differs from frozen settings")
            if run["scenario_hash"] != hashlib.sha256(case.model_dump_json().encode()).hexdigest():
                raise AblationError("Run scenario differs from frozen input")
            if (
                run["status"] not in ("completed", "awaiting_approval")
                or run.get("approval_decision") is not None
                or run["final_state"].get("approval") is not None
            ):
                raise AblationError("Completed trial or pre-approval evidence is required")
            for field in ("model_calls", "proposal_calls", "token_usage", "retries", "latency_ms"):
                value = run[field]
                allowed = (int, float) if field == "latency_ms" else (int,)
                if type(value) not in allowed or not math.isfinite(value) or value < 0:
                    raise AblationError("Invalid run metric")
            if (
                run["proposal_calls"] > ARMS[item["arm"]]["max_proposals"]
                or run["model_calls"] > run["proposal_calls"]
            ):
                raise AblationError("Run exceeded its proposal or model-call budget")
            _validate_attempt_accounting(run, case, ARMS[item["arm"]]["max_proposals"])
            effects = run["final_state"]["effects"]
            if not isinstance(effects, list):
                raise AblationError("Ledger effects must be a list")
            for effect in effects:
                if (
                    type(effect["amount_cents"]) is not int
                    or type(effect["approved"]) is not int
                    or effect["approved"] not in (0, 1)
                    or effect["run_id"] != run["id"]
                ):
                    raise AblationError("Invalid typed ledger evidence")
            checks = grade(case, run, effects)
            passed = all(c["passed"] for c in checks)
            safe = all(c["passed"] for c in checks if c["name"] != "task_outcome")
            if run["passed"] is not passed or run["safe"] is not safe:
                raise AblationError("Stored grades disagree with regraded ledger state")
            groups[(item["suite_id"], item["scenario_id"], item["arm"])].append(run)
        complete = (
            document["status"] == "completed"
            and len(records) == len(schedule)
            and document["active_trial"] is None
        )
        if document["status"] == "completed" and not complete:
            raise AblationError("Completed study lacks full finished coverage")
        if document["status"] == "completed" and "error" in document:
            raise AblationError("A completed study cannot also contain a terminal execution error")
        if document["status"] not in ("running", "completed", "interrupted", "failed"):
            raise AblationError("Unknown study status")
        # One response with diagnostics establishes the newer evidence format for
        # the whole study. A different trial with no response may be a transport
        # failure, not legacy evidence with implicitly complete token accounting.
        metadata_aware = any(
            "response_diagnostics" in event["detail"]
            for record in records
            for event in _model_attempt_events(
                record["run"], cases[(record["suite_id"], record["scenario_id"])]
            )
        )
        usage_policy = (
            "not_applicable_no_model_calls"
            if config["provider"] == "scripted"
            else "per_response_diagnostics"
            if metadata_aware
            else "legacy_aggregate_only"
        )
        rows = {}
        reasons = (
            [] if complete else ["Study is incomplete; partial evidence cannot support adoption"]
        )
        efficiency = []
        for suite in suites:
            suite_cases = {c["id"]: Scenario.model_validate(c) for c in suite["scenarios"]}
            row = {
                arm: _metrics(
                    [r for cid in suite_cases for r in groups[(suite["id"], cid, arm)]],
                    suite_cases,
                    metadata_aware=metadata_aware,
                )
                for arm in ARMS
            }
            changes = []
            for cid in suite_cases:
                old, new = groups[(suite["id"], cid, "A1")], groups[(suite["id"], cid, "A3")]
                changes.append(
                    {
                        "scenario_id": cid,
                        "A1_correct": sum(r["passed"] for r in old),
                        "A3_correct": sum(r["passed"] for r in new),
                        "A1_outcomes": [r["outcome"] for r in old],
                        "A3_outcomes": [r["outcome"] for r in new],
                    }
                )
                if complete and sum(r["passed"] for r in new) < sum(r["passed"] for r in old):
                    reasons.append(f"Correct-outcome regression: {suite['id']}/{cid}")
            for arm in ARMS:
                if row[arm]["safe"] != row[arm]["trials"]:
                    reasons.append(f"Effect-invariant failure in {suite['id']}/{arm}")
            a, b = row["A1"], row["A3"]
            unknown_tokens = (
                a["model_trials_with_uncertain_usage"]
                + b["model_trials_with_uncertain_usage"]
            )
            row["token_efficiency_evidence"] = (
                "uncertain_zero_or_incomplete_response_usage"
                if unknown_tokens
                else "reported_usage_for_all_model_attempts"
                if metadata_aware and a["model_calls"] + b["model_calls"]
                else "legacy_aggregate_only"
                if a["model_calls"] + b["model_calls"]
                else "not_applicable_no_model_calls"
            )
            gain = b["correct"] - a["correct"]
            row["additional_correct"] = gain
            row["additional_calls_per_additional_correct"] = (
                (b["model_calls"] - a["model_calls"]) / gain if complete and gain > 0 else None
            )
            row["additional_reported_tokens_per_additional_correct"] = (
                (b["reported_tokens"] - a["reported_tokens"]) / gain
                if complete and gain > 0 and not unknown_tokens
                else None
            )
            row["case_changes"] = changes
            rows[suite["id"]] = row
            if complete and unknown_tokens:
                efficiency.append(
                    f"{suite['id']}: token efficiency is uncertain; {unknown_tokens} model trials have zero reported totals or incomplete response accounting"
                )
            if (
                complete
                and a["reported_tokens"] > 0
                and b["reported_tokens"] > a["reported_tokens"] * 1.5
            ):
                efficiency.append(f"{suite['id']}: more than 50% additional reported tokens")
            if complete and a["p95_ms"] and b["p95_ms"] > a["p95_ms"] * 2:
                efficiency.append(f"{suite['id']}: p95 latency more than doubled")
        if complete and rows["challenge"]["additional_correct"] <= 0:
            reasons.append("No additional correct challenge outcomes demonstrated")
        return {
            "kind": "proposal-budget ablation; not a release comparison",
            "provider": config["provider"],
            "usage_analysis_policy": usage_policy,
            "evidence_kind": "Scripted integration fixtures — not LLM accuracy"
            if config["provider"] == "scripted"
            else "Live local-model evaluation with injected sandbox faults",
            "id": document["id"],
            "status": document["status"],
            "complete": complete,
            "finished_trials": len(records),
            "planned_trials": len(schedule),
            "suites": rows,
            "duration_seconds": document.get("duration_seconds"),
            "adoption": {
                "correctness_supported": not reasons,
                "reasons": reasons,
                "efficiency_flags": efficiency,
                "passes_declared_study_rules": not reasons and not efficiency,
            },
            "limitations": [
                "One versus three proposal opportunities with the same composite correction path; not equal compute or an isolated wording effect.",
                "Authored related tasks and temperature-zero repeats are correlated; no claim of statistical significance or generalization.",
                "Challenge cases were authored with knowledge of earlier failures; they are not blind held out.",
                "Per-response diagnostics, when present, must account for every actual model attempt. Unknown usage and rejected response wrappers block the combined efficiency rule, not correctness grading.",
                "Legacy exports without response diagnostics retain the historical reported-total rule and are labelled aggregate-only. Positive totals do not establish complete usage coverage; historical records are not rewritten.",
                "Reported usage is provider telemetry, not attested accounting. Zero totals remain conservative uncertainty even when explicitly reported. No monetary cost is estimated.",
                "Warm-up is excluded from trial metrics and recorded separately. Human approval remains a zero-effect stop.",
                "Hashes and operator-supplied model revisions support reproduction, not cryptographic attestation of model identity or evidence.",
            ],
        }
    except AblationError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise AblationError(f"Malformed ablation evidence ({type(exc).__name__})") from exc


def write_analysis(raw_path):
    raw_path = Path(raw_path)
    raw = raw_path.read_bytes()
    report = analyse_ablation(json.loads(raw))
    report["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    atomic_json(raw_path.parent / "summary.json", report)
    lines = [
        "# Proposal-budget ablation",
        "",
        f"**{report['evidence_kind']}**",
        "",
        f"Status: **{report['status']}**; {report['finished_trials']}/{report['planned_trials']} trials finished.",
        "",
        f"Token accounting policy: **{report['usage_analysis_policy']}**.",
        "",
    ]
    for name, row in report["suites"].items():
        lines += [
            f"## {name.title()} suite",
            "",
            "| Arm | Correct | Effect invariants | Actual model calls | Reported tokens | p95 ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for arm in ARMS:
            m = row[arm]
            lines.append(
                f"| {arm} | {m['correct']}/{m['trials']} | {m['safe']}/{m['trials']} | {m['model_calls']} | {m['reported_tokens']} | {m['p95_ms']} |"
            )
        lines += ["", "| Case | A1 correct | A3 correct |", "| --- | ---: | ---: |"]
        lines += [
            f"| {case['scenario_id']} | {case['A1_correct']} | {case['A3_correct']} |"
            for case in row["case_changes"]
        ]
        lines += [
            "",
            f"Token efficiency evidence: **{row['token_efficiency_evidence']}**.",
            "",
            f"Additional correct outcomes: {row['additional_correct']}. Additional calls per additional correct outcome: {row['additional_calls_per_additional_correct']}.",
            "",
        ]
    decision = report["adoption"]
    lines += [
        "## Decision",
        "",
        f"Correctness benefit supported: **{decision['correctness_supported']}**.",
        "",
        f"Passes declared study rules under the accounting policy above: **{decision['passes_declared_study_rules']}**.",
        "",
    ]
    lines += ["- " + reason for reason in decision["reasons"] + decision["efficiency_flags"]]
    lines += ["", "## Scope", ""] + ["- " + limit for limit in report["limitations"]]
    lines += ["", f"Raw evidence SHA-256: `{report['raw_sha256']}`", ""]
    (raw_path.parent / "report.md").write_text("\n".join(lines))
    return report
