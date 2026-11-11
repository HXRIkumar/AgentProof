# Verification record

Checked on 12 November 2026, Apple M4, 24 GB unified memory, macOS 26.5.1.

## Version 0.2 candidate

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

Live before/after evaluation remains in progress at this checkpoint. Its final
results will be recorded after completion; none is inferred from unit tests.

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
