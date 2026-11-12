# Verification record

Checked on 12 November 2026, Apple M4, 24 GB unified memory, macOS 26.5.1.

## Final version 0.4 engineering checkpoint

Commit `6455237` passed **597 Python tests**, Ruff, **eight web tests**, the
production build, four application browser workflows, two static browser checks,
fixture/release gates and the Linux production-container job in
[Actions run 43155026104](https://github.com/HXRIkumar/AgentProof/actions/runs/43155026104).
The container was built and exercised, including persistence across restart.

On the Mac, the same integrated source passed all 597 tests, the eight web tests
and production build. Fresh-database archive QA verified actual scripted actions,
historical isolation, selection races, exact downloads and mobile layout. A
separate static build passed the nested-path/reload/download check. The local
editable package needed reinstalling before test collection; reinstalling with
`uv sync --frozen --reinstall-package agentproof` restored imports without a
source change. The local application was then restarted and `/api/ready` returned
200 with both database and worker available.

Both free local-model families completed their studies. The later Phi study
contains 96 original and 120 challenge trials, with 46/48 and 60/60 guarded
correct outcomes respectively. The original threshold failure occurs twice and
is retained. An independent standard-library audit reconciled all 216 trial
records, ledger grades, source hashes, 226 HTTP attempts and reported usage;
the separate warm-up is excluded. See [results and limits](../reports/MODEL_PORTABILITY_FINDINGS.md).
The inference server was stopped after completion to release memory.

The 216-trial proposal-budget study and 16-trial focused probe are also complete
and independently reconciled in [the evidence audit](EVIDENCE_AUDIT.md).
Extra retries fail the declared challenge token-efficiency rule. These are
separate experiments; test counts and correlated model trials are not combined
into an accuracy claim. Original v0.1 raw evidence remains byte-identical to
the published v0.1 tag.

## Earlier version 0.4 integration checkpoint

[GitHub Actions run 43122576001](https://github.com/HXRIkumar/AgentProof/actions/runs/43122576001)
passed for `60ff899`: **494 Python tests**, Ruff, four web test groups and production
build, four real browser workflows, fixture comparison, and production-container
checks. This is a source-specific verification record, not a claim about later
changes or a hosted production deployment.

The Linux container checks inspected all five historical model reports before
running any experiments, verified each exact download hash, and independently
queried SQLite to confirm that archive browsing left both the experiment and run
tables empty. No live provider was configured. The same job then executed 48
original and 60 challenge fixture trials and verified persisted evidence after a
container restart.

The four browser workflows cover classic experiment/replay/approval/export;
background progress, reload and cancellation; exact-snapshot release comparison;
and read-only archive inspection. Archive QA also creates a deliberate local ID
collision and confirms that approving the local run cannot change the historical
record. Desktop and mobile checks reported no JavaScript errors or horizontal
overflow.

The separate HTTP service lab completed six process-boundary tests, including a
committed effect followed by a lost acknowledgement, restart and reconciliation,
eight concurrent requests using one key, conflicting arguments, unresolved
lookup, and a new-key negative control. Its independently inspected ledger results
are in [the saved report](../reports/remote-tool-lab-v1/report.md). They are not
real payment transactions or model benchmarks.

At this checkpoint, `npm audit` reported zero known vulnerabilities. `pip-audit`
also reported none in the Python environment it inspected; the editable project
itself was excluded, and the temporary audit tool's dependencies were included.
These are point-in-time advisory checks, not a source-code security assessment.

Completed real-model findings are recorded separately:
[original v0.1](../reports/LIVE_FINDINGS.md),
[challenge comparison](../reports/CHALLENGE_FINDINGS.md),
[original regression](../reports/ORIGINAL_REGRESSION_FINDINGS.md), and
[independent verification](../reports/INDEPENDENT_VERIFICATION_FINDINGS.md).
The [rules-only control](../reports/RULES_REFERENCE_FINDINGS.md) answers whether
inference is necessary for the structured policy; its trials are not pooled with
the model studies.

## Historical version 0.2 checkpoint

- Python: **228 tests passed**, Ruff clean. Includes independent evidence-integrity
  checks, queue races and restart recovery, provider usage validation, actionable
  approval grading, strict integer inputs and bounded refusal correction.
- Web: **4 import-test groups passed**; TypeScript/Vite production build passed.
- Real browser: background 202 submission, progress, reload recovery, selection
  preservation, custom import, invalid-file retention, running cancellation and
  queued cancellation passed. A cancelled run retained 18/240 completed trials;
  a queued cancellation executed zero. Both correctly failed the gate. These are
  scripted QA scenarios with a 120 ms delay to make cancellation observable.
- Classic browser workflow still passed: 48 trials, filters, replay, approval,
  export, no JavaScript errors and no mobile overflow.
- CLI: reconnecting exported identical bytes; output overwrite protection rejected
  a command before it submitted a new experiment.
- Fixture comparison against v0.1 passed with no per-case regression. Fixture
  counts remain 15/24 baseline and 24/24 guarded; this is not model accuracy.

- GitHub Actions run `43110489027` passed on commit `00931a8`: Python, web build,
  classic and asynchronous browser workflows, fixture/challenge/comparison gates,
  and a separate production-container job.
- The Linux CI container built from the repository Dockerfile, passed 48 original
  fixture trials and 60 challenge trials, then retained the exact 60 challenge
  records across a container restart. Evidence is attached to that Actions run.
- A local Docker Desktop build hit a BuildKit connection error while resolving
  base images. A cached container could reach the network; local image-build
  verification was not substituted for the successful Linux CI build. Existing
  unrelated containers were preserved.

Live before/after evaluation was still in progress at this historical checkpoint.
The completed reports are linked above; their results were not inferred from tests.

## Published version 0.1 checks

| Check | Result |
|---|---|
| `uv run pytest -q` | 76 passed |
| `uv run ruff check src tests scripts` | Passed |
| `npm run build` in `web/` | TypeScript and production Vite build passed |
| `npm audit` in `web/` | Zero reported vulnerabilities at check time |
| Real browser workflow | Chrome headless, desktop 1440x900 and mobile 390x844 |
| Docker | Image built and full 48-trial fixture experiment passed its gate inside container |
| OTLP | Real HTTP exporter received and decoded by a local protobuf collector test |
| Custom suite | JSON import exercised; invalid labels and selections rejected |
| GitHub Actions | Python tests, build, fixture gate and Chromium browser regression passed |

The browser workflow exercises experiment creation, failure/recovery filters,
search, trace/check/final-state views, replay, approval, JSON export, empty
selection and mobile overflow. It reported no JavaScript errors.

The independent tests include concurrent effect delivery, approval races,
idempotency argument conflicts, strict monetary types, orphan effects, malicious
model proposals, restart persistence, bounded failures, incomplete experiments and
grader-oracle independence. The OTLP test uses a real exporter, not a mocked
function call.

## Reproduce

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check src tests scripts
cd web && npm ci && npm run build && cd ..
.venv/bin/uvicorn agentproof.api:app --host 127.0.0.1 --port 8010
```

In another terminal:

```sh
uv run python scripts/benchmark.py --output artifacts/check --require-gate
uv run --with playwright==1.64.0 python web/qa/browser_smoke.py
```

The browser script uses installed Chrome by default. CI installs Playwright
Chromium and sets `PLAYWRIGHT_CHANNEL=chromium`. It saves screenshots under
`SCREENSHOT_DIR` when supplied.

## Evidence boundaries

The verified Docker and native runs had identical backend source fingerprints.
The application binds locally and contains no real payment integration. These
checks do not establish production throughput, security certification, remote
deployment, payment-service exactly-once execution, or unseen-task generalization.

`reports/fixture-v1.*` contains the scripted report. Its 15/24 baseline versus
24/24 guarded outcomes measure intentionally injected fixture failures; they are
not an LLM accuracy claim. Read the live report separately when evaluating the
configured model.
