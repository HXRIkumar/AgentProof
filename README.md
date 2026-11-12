# AgentProof

[![Engineering checks](https://github.com/HXRIkumar/AgentProof/actions/workflows/ci.yml/badge.svg)](https://github.com/HXRIkumar/AgentProof/actions/workflows/ci.yml)

**A release-testing workbench for policy-gated AI agent workflows.**

An agent can produce a convincing answer and still take the wrong action.
AgentProof compares a baseline and a guarded refund workflow against the actual
transaction ledger, then shows exactly where each run failed or recovered.

The flagship test: a refund commits, but its acknowledgement times out. A naive
retry creates a second effect. The guarded workflow reuses a stable idempotency
key, returns the original result and records one refund.

![Inspecting a recovered transaction after a lost acknowledgement](docs/screenshots/trace.png)

This is a working local engineering lab. Orders, customers and refund effects
are synthetic. It has both a deterministic fault provider and a configurable
real-model adapter; the interface and reports distinguish the two.

## Run it

Prerequisites: macOS or Linux, Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), Node 22+.
Windows users can use the Linux Docker container or WSL; the local worker uses POSIX file locks.

```sh
uv sync --frozen
cd web
npm ci
npm run build
cd ..
.venv/bin/uvicorn agentproof.api:app --host 127.0.0.1 --port 8010
```

Open **http://127.0.0.1:8010**. Run the scripted suite, select a result, and
inspect its checks, event trace and final ledger. No API key is required.
To inspect the measured local-model results immediately, choose **Recorded
evidence** in the sidebar. The five bundled reports retain their original
failures, pending approvals, model revisions and source hashes. This view is
read-only and makes no model calls; it does not import anything into your local
experiment history. [Archive provenance and scope](docs/EVIDENCE_ARCHIVE.md).
For frontend development, `cd web && npm run dev` starts Vite with an API proxy.
On macOS, `scripts/open-mac.command` starts the application and opens the browser;
keep its Terminal window open while using a server started by the launcher.

Alternatively:

```sh
docker compose up --build -d
```

The service binds only to localhost. A named volume persists experiment evidence.
The local application does not implement user authentication; do not expose its
approval or experiment API publicly.

## What you can inspect

- Paired baseline and guarded outcomes across an authored regression suite.
- Transient read failures, permanent outages, malformed proposals, stale policy,
  prompt injection, incorrect identifiers, excessive amounts and duplicate delivery.
- Bounded proposal correction and read retries, with visible budgets and traces.
- Transactional effect deduplication and human approval for high-value requests.
- Persisted runs, fresh-sandbox replay, JSON export and a machine-readable CI gate.
- Background experiments with live progress, bounded queues and cancellation after the current trial.
- Browser import of custom JSON suites, including clear schema errors and a downloadable example.
- Release-to-release comparisons that reject incomplete evidence and reveal per-case regressions.
- Side-by-side traces, checks and ledger snapshots for both versions of a changed case.
- Actual model requests and token counts when a live provider is configured.
- Bounded response diagnostics: termination reason, usage availability, output
  fingerprint and parse category, without retaining raw completions.
- A separately implemented rules-only control that tests whether inference is needed.
- A real localhost HTTP service lab for lost acknowledgements and persisted idempotency.

The guarded agent does not become a better model. Its execution environment
enforces explicit business constraints. That distinction is central to this project.

![Inspect completed trials while a background experiment continues](docs/screenshots/background-progress.png)

Queued jobs survive a server restart. A trial interrupted by a crash is marked
failed, never silently rerun. Cancelled experiments retain completed evidence and
cannot pass the gate. Both synchronous clients and the web console share one
serialized worker per database; run one API process per database.

## Live inference

An OpenAI-compatible chat-completions endpoint can be local or hosted. Credentials
are server-side environment variables. Hosted providers may charge for requests.

```sh
export AGENTPROOF_BASE_URL=http://127.0.0.1:8089/v1
export AGENTPROOF_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
export AGENTPROOF_DISABLE_THINKING=true
export AGENTPROOF_TIMEOUT_SECONDS=120
export AGENTPROOF_MODEL_REVISION=32f3e8ecf65426fc3306969496342d504bfa13f3
.venv/bin/uvicorn agentproof.api:app --host 127.0.0.1 --port 8010
```

On Apple Silicon, a separate free local server can be launched with:

```sh
uv tool run --python 3.12 --from mlx-lm mlx_lm.server \
  --model mlx-community/Qwen3.5-4B-MLX-4bit \
  --host 127.0.0.1 --port 8089 \
  --chat-template-args '{"enable_thinking":false}' \
  --prompt-cache-size 0
```

This downloads model weights and consumes local memory. The MLX server is a
development server, not a hardened deployment. Other compatible endpoints can be
used; set `AGENTPROOF_API_KEY` for hosted providers. The adapter uses bounded
timeouts, strict proposal validation and a fixed proposal-attempt limit.
The revision above identifies the tested weights; set the revision to the
weights you actually load. It is recorded metadata, not a command that pins the
inference server's download. The HTTP I/O cancellation deadline spans connection,
headers and body; DNS cleanup can extend elapsed time. Responses are capped at
1 MiB and must use identity encoding. See [operational limits](docs/HARDENING_NOTES.md)
for the tested boundaries and the explicit DNS limitation.

## Evaluate and export evidence

With the API running:

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/benchmark.py --output reports/my-fixture --require-gate
uv run python scripts/benchmark.py --provider openai --repeats 3 --output reports/my-live
uv run python scripts/benchmark.py --suite examples/custom-suite.json --output reports/custom
uv run python scripts/benchmark.py --background --suite examples/challenge-suite-v1.json --output reports/challenge
uv run python scripts/benchmark.py --experiment-id SAVED_ID --output reports/reconnected
uv run python scripts/compare.py reports/reference.json reports/candidate.json --output reports/comparison
```

Each benchmark saves raw JSON, an analysis JSON and a readable Markdown report.
Raw evidence includes per-run traces and checks. Reports retain denominators,
source revision, hashes, measured latency and limitations. A failed gate exits
nonzero when `--require-gate` is supplied. CI runs only scripted tests, never paid
model calls. See [evaluation protocol](docs/EVALUATION_PROTOCOL.md).

`--background` prints the persisted experiment ID and polls progress. If the
client disconnects, reconnect with `--experiment-id`; the server owns the job.
Existing output files are protected unless `--overwrite` is explicit.
The comparison command also protects existing derived reports and refuses to
overwrite either raw input, even when `--overwrite` is supplied.
The comparison command checks compatible inputs and model settings, regrades
exported ledger effects, and fails on any guarded case regression even if the
aggregate improves. Its per-case gate is stricter than the single-experiment UI
gate. Cost and latency changes are reported, not automatically certified acceptable.

In the console, open **Release comparison**, select a completed reference and
compare it with the current candidate. Filter regressions or improvements, then
inspect both versions' traces and ledger snapshots. Repeat selectors are
independent: trial ordering does not establish matched independent samples.
The inspector uses the exact snapshots graded by that comparison, with a capture
timestamp. Comparison makes no new model calls and does not alter either run.

![An aggregate improvement that correctly fails because one case regressed](docs/screenshots/release-comparison.png)

Custom suites use the typed scenario schema exposed in `/api/docs`. Expected
outcomes are evaluator labels and are never included in model observations.
Suite authors control those labels; review them before interpreting a pass rate.
The [30-case challenge suite](docs/CHALLENGE_SUITE.md) was frozen before recovery
changes; its provenance is documented. It is an authored development set, not a
blind held-out benchmark. Requested amounts support up to 1,000,000 cents;
negative requests are allowed as deliberate rejection tests.

The local API accepts only loopback Host names and limits request bodies to
1 MiB. `/api/health` reports liveness; `/api/ready` additionally checks the worker
and database. These controls do not provide user authentication or tenant isolation.

## Measured live results

A local Qwen3.5-4B run completed **144 trials**: 24 authored scenarios, three
repetitions and two strategies. Correct outcomes were **45/72 baseline versus
66/72 guarded**; guarded runs passed all defined effect-invariant checks. Six
valid requests were still incorrectly refused. The runtime used more tokens and
had higher tail latency. This is a measured development-suite result with injected
faults, not a general LLM accuracy claim. [Full results and raw evidence](reports/LIVE_FINDINGS.md).

A later frozen 30-case challenge exposed substantially more over-refusal. Bounded
factual correction and policy refresh improved guarded outcomes from **32/60 to
54/60**, with no per-case regressions and all defined effect checks passing.
Reported tokens increased **29.8%**; six trials still failed. These are authored
development cases, and host activity limits latency comparisons.
[Challenge results, failures and exact source fingerprints](reports/CHALLENGE_FINDINGS.md).

The original-suite regression subsequently improved from **66/72 to 72/72**
guarded correct outcomes, using six additional HTTP attempts and 10.3% more
reported tokens. The unchanged baseline remained 45/72 correct.
[Original regression evidence](reports/ORIGINAL_REGRESSION_FINDINGS.md).

A separate author then created 24 verification cases from only the policy and
schema, without seeing the implementation, prompts or existing results. Against
the already frozen implementation, guarded outcomes were **48/48 correct**
versus **20/48 baseline**, with all defined guarded effect checks passing.
This is small synthetic verification, not a public benchmark or broad reliability
guarantee. [Independent provenance and results](reports/INDEPENDENT_VERIFICATION_FINDINGS.md).

![Actual saved live evidence compared in the console](docs/screenshots/live-release-comparison.png)

## Test the simpler alternative

For this fully structured refund policy, a model is unnecessary. A rules-only
control matched the model on **66/66 applicable original trials** and completed
**56/56 challenge trials versus 50/56 for the guarded model**, with zero inference
requests. Two deliberately injected model-provider faults per suite are excluded
and individually disclosed; ordinary live grounding and adversarial-note cases
remain included. [Rules control and interpretation](reports/RULES_REFERENCE_FINDINGS.md).

This is an evaluation workbench for inspecting model workflows, not a claim that
all business rules should use an LLM. Choosing ordinary code when it is sufficient
is one of the project's findings.

## Measure what extra recovery costs

A frozen, balanced **216-trial A1/A3 study** held the guarded workflow constant
and varied only its proposal budget. Original-suite correctness rose **40/48 to
48/48**; challenge correctness rose **30/60 to 54/60**, with no per-case losses
and all defined effect checks passing. Challenge reported tokens rose **100.2%**,
so the result **fails the predeclared token-efficiency threshold** despite its
correctness gain. The two suites remain separate; repeats are correlated.
[Protocol, complete results and original evidence](reports/ABLATION_FINDINGS.md).

```sh
uv run python scripts/ablate.py run --provider openai --output-dir artifacts/my-ablation
```

This experiment accepts only a local inference endpoint. It is not a release
comparison or an equal-compute test. Existing reports retain aggregate-only usage
limitations; newer diagnostics make unknown per-response accounting explicit.

A separate 16-trial diagnostic probe examined three known failures and one
successful control. It distinguished incomplete JSON at the output limit from
normally terminated, valid proposals with incorrect amounts. More output tokens
alone would not explain all failures. This was selected post-hoc diagnosis,
not an accuracy benchmark. [Response-level findings](reports/DIAGNOSTIC_FINDINGS.md).

[Reproducible evidence figures](docs/EVIDENCE_FIGURES.md) keep development,
independent verification and rules-only controls visually separate.

## Cross a real service boundary

```sh
uv run python scripts/remote_lab.py --output-dir artifacts/my-remote-lab
```

A separate localhost process owns its own SQLite ledger. The lab commits a
synthetic refund, closes the response socket, then reconciles or retries with the
same operation key. It tests process restart, concurrent requests, conflicting
arguments and unresolved ambiguity. An intentionally unsafe new-key retry creates
two effects; the same-key path retains one. Independent database inspection
checks each result. [Protocol](docs/REMOTE_TOOL_LAB.md) ·
[Saved six-scenario evidence](reports/remote-tool-lab-v1/report.md).

This lab makes no model calls and uses no payment provider. Its results are
separate from the model studies, and its synthetic customer identity is not
production authentication.

## Architecture

```mermaid
flowchart LR
    UI[React evaluation console] --> API[FastAPI experiment API]
    API --> QUEUE[Durable SQLite queue]
    QUEUE --> WORKER[One worker with exclusive lease]
    WORKER --> GRAPH[LangGraph workflow]
    GRAPH --> OBS[Observe order and policy]
    OBS --> MODEL[Scripted or live proposal]
    MODEL --> GATE[Typed validation and policy gate]
    GATE -->|bounded feedback| MODEL
    GATE --> APPROVAL[Human approval when required]
    GATE --> LEDGER[Transactional simulated refund ledger]
    APPROVAL --> LEDGER
    LEDGER --> GRADE[Independent final-state checks]
    GRAPH --> TRACE[Run span with child stage spans]
    GRADE --> DB[(SQLite run journal)]
    DB --> UI
```

Python/FastAPI/Pydantic handle typed boundaries; LangGraph makes the workflow
explicit; SQLite owns transaction identity and evidence; React/TypeScript makes
the comparison inspectable. Optional OTLP export is configured using
`OTEL_EXPORTER_OTLP_ENDPOINT`. No prompt bodies or credentials are span attributes.
Persisted run IDs correlate with actual OTLP trace/span IDs when tracing is
configured; disabled mode records no borrowed IDs. [Tracing behavior and tested
boundaries](docs/TRACE_CONTEXT.md).

## Scope and honest limits

- The authored suite is a development regression suite, not a held-out public benchmark.
- Scripted results test infrastructure, not LLM accuracy. Live runs also contain
  explicitly injected tool/provider faults; inspect their traces.
- Approval is an in-app operator action in a local sandbox, not authenticated
  enterprise approval provenance.
- Stage snapshots support inspection and persisted pending approvals. Interrupted
  in-flight computation is not automatically resumed; replay starts a fresh sandbox.
- Idempotency is proven within the SQLite ledger boundary. Remote payments require
  the payment system's own deduplication and reconciliation protocol.
- No multi-tenant deployment, distributed workers, production load testing or
  customer adoption is claimed.

## Start here for interviews

[Two-minute walkthrough of actual saved evidence](docs/DEMO.md) ·
[Five-minute demonstration and architecture questions](docs/INTERVIEW_GUIDE.md) ·
[Research and technology decisions](docs/RESEARCH.md) ·
[Evaluation methodology](docs/EVALUATION_PROTOCOL.md) ·
[Engineering tradeoffs](docs/ENGINEERING_NOTES.md) ·
[Verification record](docs/VERIFICATION.md)

Inspired by outcome-oriented agent evaluation work, including
[Anthropic's evaluation guide](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)
and [Sierra's tau2-bench](https://github.com/sierra-research/tau2-bench).
AgentProof is an independent, smaller project, not an implementation of their benchmark.
