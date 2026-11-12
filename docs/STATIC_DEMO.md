# Recorded-only static demonstration

The static build serves the same recorded-evidence inspector without a Python
server, database, inference endpoint or credentials. It is suitable for a
GitHub Pages project URL such as `/AgentProof/`. It does not run experiments.
The ordinary application build and API remain available for local execution.

## Build and inspect locally

From the repository root:

```sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build:recorded
uv run python scripts/build_static_evidence.py
uv run --with playwright==1.64.0 python web/qa/static_smoke.py
uv run --with playwright==1.64.0 python web/qa/static_review.py
```

The first browser check serves the actual `web/dist` directory under `/AgentProof/`
using a temporary static HTTP server. It checks all five reports and download
hashes, a failed task, historical pending approval, mobile layout and the absence
of API or mutation requests. Chrome is used locally; set
`PLAYWRIGHT_CHANNEL=chromium` after installing Playwright Chromium if preferred.
Screenshots and machine-readable checks are saved under `artifacts/browser-static`.
The independent review check builds a separate temporary distribution beneath
`/review/AgentProof_v2/`, verifies the selected-report reload after a failed request,
and checks all downloads. It does not change `web/dist`.

Publish **only `web/dist/`**. Generated files are ignored by Git. No source
checkout, `.env`, SQLite database or private run journal belongs in a Pages
artifact. Building these files does not publish them or configure Pages.
`npm run build:recorded` sets recorded-only mode and the `/AgentProof/` Vite base.
For a different project path, pass `--base /YourProject/` to the Vite command;
the client uses that build's `BASE_URL` for assets, report reads and downloads.

## What a visitor sees

The initial selection is **Independent verification · v0.3**. A persistent
notice says this is a recorded demonstration with no backend or model running.
**Inspect recorded challenge failures** opens the challenge v0.2 report with
its failure filter selected. The visitor can inspect traces, checks and final
ledgers, switch among all five reports and download the original JSON.

Model badges describe the historical decision provider. They do not claim
inference is running in the page. Limitations remain visible: the orders and
refund effects are synthetic; the studies are small and are not general model
benchmarks or production safety certifications. The page links to instructions
for running the full local application.

Workspace history, experiment setup, replay, approvals, cancellation, release
comparison and API connection claims are absent. The transport allows only
curated evidence GET requests; mutation payloads and workspace paths are rejected
before fetch. There is no mock API server and no invented config/history result.

## Evidence integrity and boundaries

The builder loads every original report through `EvidenceLibrary`, including
its pinned SHA-256, bounded strict JSON/schema validation, complete-coverage
checks and ledger regrading. It fails before creating output if any report is
missing or invalid. It recomputes display summaries using the same pure function
as the API. The original raw report bytes are copied unchanged to
`evidence/raw/<sha256>.json`; `evidence/manifest.json` lists their hashes.

Validation happens **at build time against the repository catalog**, not through
an independent signature or external attestation. The static client reads the
built envelopes; it does not rerun Python validation in the browser. HTTPS and
the hosting account's integrity remain part of the distribution boundary.
Downloaded bytes can be checked against their displayed SHA-256.

A fresh-process test denies network sockets, confirms the builder never imports
the API, Store, worker or provider modules, and checks that it creates no database.
Only the curated catalog is packaged; arbitrary local experiment records are
not scanned, uploaded or imported.
