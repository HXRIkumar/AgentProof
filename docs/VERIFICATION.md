# Verification record

Checked on 12 November 2026, Apple M4, 24 GB unified memory, macOS 26.5.1.

## Executed checks

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
