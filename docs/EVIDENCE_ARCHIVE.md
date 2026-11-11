# Inspect recorded model evidence without running a model

The console includes a separate **Recorded evidence** list. It works on a fresh
source checkout or Docker installation with an empty experiment database and no
model configuration. Select a report, inspect baseline/guarded trials, and open
the checks, trace or final ledger. Browsing makes no inference calls.

These are the original saved local-model experiments, not replayed or fabricated
UI data. They deliberately retain failed trials and historically pending
approvals. The scripted demo remains available as a separate workspace action.

![Recorded local-model evidence in the console](screenshots/recorded-evidence.png)

| Recorded report | Cases | Trials | Executed workflow |
|---|---:|---:|---|
| Original suite | 24 | 144 | v0.1 |
| Original suite | 24 | 144 | v0.2 |
| Challenge suite | 30 | 120 | v0.1 |
| Challenge suite | 30 | 120 | v0.2 |
| Independent verification | 24 | 96 | v0.3 |

Repeated trials and overlapping suites must not be added together and presented
as independent benchmark tasks. The authored development suites are not blind
benchmarks. Independent verification used separately authored cases after the
implementation was frozen, but it is still a small synthetic study.

## What remains read-only

An archive selection is distinct from a workspace selection, even when both
contain exactly the same experiment and run IDs. The archive is loaded from a
fixed repository file, never from the mutable run database. Its inspector has
no replay, approval, rejection or cancellation controls. The corresponding UI
handlers also require a workspace selection.

A pending approval means the experiment stopped at that point. It does not
represent a current task for the person browsing the archive. Later local
approvals cannot change this historical snapshot. Release-to-release comparison
currently uses workspace experiments; the archive still provides each report’s
baseline-versus-guarded view.

## Provenance and validation

`src/agentproof/evidence.py` defines five catalog entries with fixed filenames,
SHA-256 hashes, executed workflow versions and suite provenance. No user-supplied
path, URL or arbitrary uploaded JSON is accepted. Each read is bounded to 2 MiB
and checked against the catalog hash before parsing.

The reader validates the display schema, finite numbers, configuration hash,
suite/scenario hashes, complete trial coverage, provider/model consistency and
ledger grading. Duplicate JSON keys, malformed traces, contradictory grades or
unsupported export shapes are rejected. Missing/tampered records are marked
unavailable; ordinary workspace experiments remain usable.

The display summary and check descriptions are derived from the validated
snapshot using the supported grader. **Download recorded JSON** returns the
exact original verified bytes, including the original stored summary. Hashes
and metadata are exposed in **Recorded provenance**. They establish consistency
with the repository catalog, not a signed attestation of who produced the data.

The executed backend fingerprint identifies the source snapshot behind the
trial, rather than the version of the application currently displaying it. The
recorded model revision describes the tested weights; it does not pin a newly
started inference server. Latency and token results retain the limitations
documented alongside the original studies.

![Inspecting a recorded failure without rerunning the model](screenshots/recorded-failure.png)

## API and packaging

- `GET /api/evidence`: catalog with explicit availability.
- `GET /api/evidence/{archive_id}`: provenance and a detached display snapshot.
- `GET /api/evidence/{archive_id}/download`: original verified JSON bytes.

These routes do not construct a model provider or read/write the workspace
experiment store. There are no archive mutation endpoints. Downloads are served
from the bytes already validated in that request, avoiding a second file read
between verification and delivery.

Source checkouts read the existing `reports` directory. The Dockerfile explicitly
copies the five catalog reports into the image. A standalone Python wheel is
not advertised as an archive distribution; an installation without the files
shows their unavailability rather than inventing replacement results.

## Verification

Backend tests cover real catalog reports, exact download hashes, failed
integrity/schema checks, model-free browsing, empty-store preservation, ID
collisions and malformed nested numbers. Browser QA starts a disposable API
without a live provider and checks failed trials, historical approval, exact
downloads, source-selection races and responsive layout.

The browser collision test first executes a scripted experiment, constructs a
QA-only local ID collision from that executed state and approves it locally.
The same archived run remains pending with zero effects, while the local run has
one effect. This fixture setup exists only in the test server.

```sh
uv run pytest -q tests/test_evidence_archive.py tests/test_evidence_review.py
cd web && npm ci && npm run build && cd ..
uv run --with playwright==1.64.0 python web/qa/archive_smoke.py
```

The archive does not display the separate ablation, rules-reference or remote
tool-lab report formats; their original reports remain in the repository.
