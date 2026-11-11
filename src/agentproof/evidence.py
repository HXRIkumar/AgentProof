"""Curated, hash-pinned historical evidence. No database or model access."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .comparison import ComparisonError, validate_experiment_export
from .grading import grade
from .models import Scenario

MAX_ARCHIVE_BYTES = 2_097_152
REPORT_ROOT = Path(__file__).resolve().parents[2] / "reports"


@dataclass(frozen=True)
class ArchiveEntry:
    id: str
    title: str
    filename: str
    sha256: str
    source_version: str
    suite_provenance: str


CATALOG = (
    ArchiveEntry(
        "challenge-v02",
        "Challenge suite · v0.2",
        "challenge-v1-after.json",
        "df2f8062a6202444bbfbea908bbaff7a7bf6d5c04e892d6507e5e4610771223f",
        "v0.2",
        "30 authored development cases, frozen before recovery changes; not a blind benchmark.",
    ),
    ArchiveEntry(
        "challenge-v01",
        "Challenge suite · v0.1",
        "challenge-v1-before.json",
        "4350df2a927427b391c077722705107d5680cd1f4997092439363fd5a7e09ea8",
        "v0.1",
        "The same 30 authored challenge cases, evaluated on the earlier workflow.",
    ),
    ArchiveEntry(
        "original-v02",
        "Original suite · v0.2",
        "qwen35-4b-live-v02.json",
        "2bc665369b0e943663485a3255cb4ddd5c503ff3997b77559c64d0604a985bad",
        "v0.2",
        "24 authored regression cases; repeated temperature-zero trials are correlated.",
    ),
    ArchiveEntry(
        "original-v01",
        "Original suite · v0.1",
        "qwen35-4b-live-v1.json",
        "3e8fb9dc2889b13de703a8c4b0c9979f59a982db86bb49e10df754d2edc218e7",
        "v0.1",
        "The initial 24-case development evaluation, including all observed failures.",
    ),
    ArchiveEntry(
        "independent-v03",
        "Independent verification · v0.3",
        "independent-verification-v1.json",
        "6ce7c8c54e49279fdc1cd6c9cff003a54955282323e85208d96c4ab7f093e797",
        "v0.3",
        "24 independently authored cases evaluated after the implementation was frozen; "
        "not a public benchmark or a broad generalization claim.",
    ),
)


class EvidenceError(ValueError):
    pass


class DisplayModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", allow_inf_nan=False)


class RecordedEvent(DisplayModel):
    index: int = Field(ge=0, le=10000)
    kind: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=128)
    duration_ms: float = Field(ge=0, le=86_400_000)
    detail: dict[str, Any]


class RecordedCheck(DisplayModel):
    name: str = Field(min_length=1, max_length=128)
    passed: bool
    detail: str = Field(max_length=4096)


class RecordedRun(DisplayModel):
    id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_name: str = Field(min_length=1, max_length=1000)
    category: str = Field(min_length=1, max_length=128)
    variant: Literal["baseline", "guarded"]
    provider: Literal["scripted", "openai"]
    model: str = Field(min_length=1, max_length=256)
    status: Literal["completed", "awaiting_approval"]
    passed: bool
    safe: bool
    outcome: Literal["refunded", "rejected", "escalated", "approval_required"]
    expected_outcome: Literal["refunded", "rejected", "escalated", "approval_required"]
    latency_ms: float = Field(ge=0, le=86_400_000)
    model_calls: int = Field(ge=0, le=10000)
    retries: int = Field(ge=0, le=10000)
    token_usage: int = Field(ge=0, le=1_000_000_000)
    events: list[RecordedEvent] = Field(max_length=1000)
    checks: list[RecordedCheck] = Field(min_length=1, max_length=100)
    final_state: dict[str, Any]
    parent_run_id: str | None = None


class RecordedConfiguration(DisplayModel):
    provider: Literal["scripted", "openai"]
    model: str = Field(min_length=1, max_length=256)
    model_revision: str = Field(min_length=1, max_length=256)
    temperature: float = Field(ge=0, le=2)
    timeout_seconds: float | None = Field(gt=0, le=3600)
    max_tokens: int | None = Field(gt=0, le=1_000_000)
    disable_thinking: bool
    repeats: int = Field(ge=1, le=5)
    max_proposals: int = Field(ge=1, le=3)
    variant_order: Literal["alternating_by_scenario_and_repeat"]
    scenario_ids: list[str] = Field(min_length=1, max_length=100)


class RecordedExperiment(DisplayModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=1000)
    created_at: str = Field(min_length=1, max_length=64)
    provider: Literal["scripted", "openai"]
    status: Literal["completed"]
    configuration: RecordedConfiguration
    server_metadata: dict[str, Any]
    suite_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenarios: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    runs: list[RecordedRun] = Field(min_length=1, max_length=1000)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Recorded evidence contains duplicate JSON keys")
        result[key] = value
    return result


def _invalid_constant(value):
    raise EvidenceError("Recorded evidence contains a non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise EvidenceError("Recorded evidence contains a non-finite JSON number")
    return number


class EvidenceLibrary:
    def __init__(self, root: Path | None = None, entries=None):
        self.root = Path(root) if root is not None else REPORT_ROOT
        self.entries = {entry.id: entry for entry in (CATALOG if entries is None else entries)}

    def load(self, archive_id: str):
        """Return verified bytes and a detached display copy; never rewrite raw evidence."""
        if archive_id not in self.entries:
            raise KeyError(archive_id)
        entry = self.entries[archive_id]
        try:
            path = self.root / entry.filename
            with path.open("rb") as stream:
                raw = stream.read(MAX_ARCHIVE_BYTES + 1)
        except OSError:
            raise EvidenceError("Recorded evidence is not included in this installation") from None
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise EvidenceError("Recorded evidence exceeds the supported file size")
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise EvidenceError("Recorded evidence failed its SHA-256 integrity check")
        try:
            document = json.loads(
                raw,
                object_pairs_hook=_object,
                parse_constant=_invalid_constant,
                parse_float=_finite_float,
            )
            RecordedExperiment.model_validate(document)
            recorded_at = datetime.fromisoformat(document["created_at"])
            if recorded_at.tzinfo is None:
                raise ValueError("Timestamp must have an offset")
            config_hash = hashlib.sha256(
                json.dumps(document["configuration"], sort_keys=True).encode()
            ).hexdigest()
            if config_hash != document["config_hash"]:
                raise EvidenceError("Recorded configuration does not match its hash")
            source_hash = document["server_metadata"]["backend_source_sha256"]
            if not isinstance(source_hash, str) or len(source_hash) != 64:
                raise ValueError("Missing executed-source fingerprint")
            int(source_hash, 16)
            validated = validate_experiment_export(document)
            scenarios = {s["id"]: Scenario.model_validate(s) for s in validated["suite"]}
            for run in document["runs"]:
                scenario = scenarios[run["scenario_id"]]
                if (
                    run["scenario_name"] != scenario.name
                    or run["category"] != scenario.category
                    or run["expected_outcome"] != scenario.expected_outcome
                ):
                    raise EvidenceError("Recorded trial labels differ from the embedded case")
                final = run["final_state"]
                if (
                    type(final["total_refunded_cents"]) is not int
                    or final["total_refunded_cents"]
                    != sum(e["amount_cents"] for e in final["effects"])
                    or final["policy_version"] != scenario.current_policy
                ):
                    raise EvidenceError("Recorded final state contradicts its ledger effects")
                checks = grade(scenario, run, final["effects"])
                if [(c["name"], c["passed"]) for c in run["checks"]] != [
                    (c["name"], c["passed"]) for c in checks
                ]:
                    raise EvidenceError("Recorded checks disagree with the supported grader")
                run["checks"] = checks
        except EvidenceError:
            raise
        except (ValidationError, ComparisonError, ValueError, TypeError, KeyError, RecursionError):
            raise EvidenceError(
                "Recorded evidence is incompatible with the supported export schema"
            ) from None
        configuration = document["configuration"]
        archive = {
            "id": entry.id,
            "title": entry.title,
            "read_only": True,
            "sha256": entry.sha256,
            "source_version": entry.source_version,
            "recorded_at": document["created_at"],
            "provider": document["provider"],
            "model": configuration["model"],
            "model_revision": configuration["model_revision"],
            "backend_source_sha256": source_hash,
            "suite_hash": document["suite_hash"],
            "suite_provenance": entry.suite_provenance,
            "trial_count": len(document["runs"]),
            "distinct_cases": len(document["scenarios"]),
            "integrity_note": "Hash-checked against the repository catalog; not a signed attestation.",
            "validation": "Supported export schema, complete coverage and ledger regrading passed.",
            "download_url": f"/api/evidence/{entry.id}/download",
        }
        return raw, {"archive": archive, "experiment": document}

    def catalog(self):
        entries = []
        for entry in self.entries.values():
            try:
                _, envelope = self.load(entry.id)
                entries.append({**envelope["archive"], "available": True})
            except EvidenceError as exc:
                entries.append(
                    {
                        "id": entry.id,
                        "title": entry.title,
                        "available": False,
                        "read_only": True,
                        "error": str(exc),
                    }
                )
        return entries
