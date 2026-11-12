# Recorded-only static demonstration

The static build serves the same recorded-evidence inspector without a Python
server, database, inference endpoint or credentials. It is suitable for a
GitHub Pages project URL such as `/AgentProof/`. It does not run experiments.
The ordinary application build and API remain available for local execution.

Published viewer: **https://hxrikumar.github.io/AgentProof/**.
The initial deployment from `6455237` followed successful
[engineering CI](https://github.com/HXRIkumar/AgentProof/actions/runs/43155026104)
and [Pages validation/deployment](https://github.com/HXRIkumar/AgentProof/actions/runs/43155584726).
Its `build.json` identifies the exact deployed source and preceding CI run.
Future pushes publish only after successful push CI on the current branch tip;
the build has read-only repository/Pages access and the isolated deployment job
receives Pages write/OIDC permissions.

The [initial public-site verification](../reports/public-demo-verification-v04.json)
checked actual HTTPS responses, all five downloads directly and through Chrome,
the failed-case inspector, negative-finding links and desktop/mobile layouts.
It recorded no JavaScript errors, failed site responses, API calls or mutations.
This is a dated deployment check; `build.json` is the current source record.

## Build and inspect locally

From the repository root:

```sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build:recorded
uv run python scripts/build_static_evidence.py
uv run python scripts/build_answer_evidence.py
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

The default workspace is **Answer Lab**, with recorded model experiments, their
per-case comparisons, source citations, correction traces and cache measurements.
The source editor shows example inputs, but generating an answer requires the
local application. The public viewer sends no model requests. It does not invent
saved history or live connection status.

The answer catalog reads completed quality studies from `reports/answers/` and
cache studies from `reports/answers-cache/`. Development experiments stay separate
in `reports/answer-development/`; they are not presented as final evaluation.
Each raw report retains the exact model identities, source hashes and measurements.
The UI export preserves JSON content; the static raw report URL preserves original
file bytes and can be verified against the catalog SHA-256.

**Tool-action lab** opens the earlier recorded-evidence workspace at `/legacy`.
That workspace still contains all five historical reports, including challenge
failures and their ledger traces. Its synthetic order/refund results answer a
different question and are not pooled with answer-quality results.

Model labels describe the recorded provider, not inference running in the page.
The studies are small and do not establish general model accuracy or production
safety. The transport permits read-only evidence requests; mutations and workspace
API requests are rejected before fetch. There is no mock API server.

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

Answer studies use a separate builder which recomputes grades and summaries from
the recorded trials, rejects incomplete or mismatched evidence, and copies raw
bytes unchanged. Cache studies additionally regrade each cold request, replay and
changed query. The independent offline answer auditor provides a second grading
implementation. The release manifest pins the expected report IDs and hashes for
static and container checks. These checks establish artifact consistency, not
independent attestation of the hosted provider or the truth of every source.
