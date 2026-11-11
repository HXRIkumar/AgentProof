# Run the proposal-budget ablation

This implements only the A1 versus A3 experiment from `ABLATION_PLAN.md`.
The optional 2×2 feedback/context study remains deferred. Both arms use the same
guarded policy, approval, lookup recovery and idempotency logic. Only the maximum
number of proposals differs. The API continues to use three by default.

From the project root, first run the free deterministic fixture check:

```bash
uv run python scripts/ablate.py run --provider scripted \
  --output-dir artifacts/ablation-fixture --seed 20261112
```

For a real local-model run, configure the existing OpenAI-compatible loopback
endpoint and pin its revision; remote endpoints are rejected by this runner.
These settings match the earlier local Qwen experiment, but the server must
actually be serving this revision with its prompt cache disabled:

```bash
export AGENTPROOF_BASE_URL=http://127.0.0.1:8089/v1
export AGENTPROOF_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
export AGENTPROOF_MODEL_REVISION=32f3e8ecf65426fc3306969496342d504bfa13f3
export AGENTPROOF_DISABLE_THINKING=true
export AGENTPROOF_MAX_TOKENS=512
export AGENTPROOF_TIMEOUT_SECONDS=120
export AGENTPROOF_INFERENCE_NOTE='Record actual inference hardware, MLX versions and cache settings here'
uv run python scripts/ablate.py run --provider openai \
  --output-dir reports/ablation-local-20261112 --seed 20261112
```

The runner uses only guarded arms: 24 original cases and 30 frozen challenge
cases, two repeats, two budgets = **216 trials**, not 216 independent tasks.
Each case runs A1 first once and A3 first once; the seeded schedule is stored
before any inference. No redundant unguarded baseline is executed. One common
live warm-up is recorded separately and excluded from trial metrics. Avoid
running other clients against the model endpoint during this study.

Each new output directory contains:

- `raw.json`: full configuration, source/prompt/suite hashes, saved schedule,
  completed trial traces/effects, and active/incomplete status. Atomic checkpoint
  replacement occurs before and after each trial.
- `ledger.sqlite3`: the isolated journal, including evidence from any interrupted
  trial. It is never resumed automatically.
- `summary.json` and `report.md`: validated results, separately reported by suite,
  per-case changes, actual model calls, reported tokens and latency.

Existing output directories are refused. Ctrl-C or SIGTERM retains partial
evidence with `interrupted` status. A hard kill can leave `running` status and
an active trial; it cannot produce a completed adoption decision. Start a new
output directory to repeat an interrupted study. Do not append replacements to
the old schedule or silently drop failed trials.

To inspect or regenerate analysis without model calls:

```bash
uv run python scripts/ablate.py analyse reports/ablation-local-20261112/raw.json
```

Analysis regrades final ledger states, verifies exact frozen suites, schedule
coverage, immutable arm budgets and common configuration. Attempt, retry and
injected-fault counts must agree with recorded trace events; scripted trials
cannot report HTTP requests or inference tokens. A completed study containing
an execution error is invalid. Live warm-up completion needs request/token/
latency accounting, and failed warm-ups retain a redacted terminal state and
their attempted request count. Partial results remain
visible but cannot support adoption. The existing release-comparison command
still rejects different proposal budgets; this separate analysis does not relax
that gate.

A3 supports the stated correctness benefit only when it gains a challenge
outcome, loses no per-case outcome on either suite and both arms preserve all
defined effect invariants. Token growth over 50% or p95 latency growth over 2×
is separately flagged as a local efficiency regression. These are predeclared
project thresholds, not a production SLA. Report unfavorable and unchanged
results too; more attempts also consume more compute.

Exit status 0 means a complete valid study, not a favorable scientific result;
read the adoption decision. Status 2 means invalid/incomplete/failed work, and
130 means an orderly interruption. Scripted results test the harness, not LLM
accuracy. Missing provider usage cannot be distinguished from zero reported
tokens, so token coverage remains uncertain and no monetary cost is inferred.
Any live trial with actual requests and zero reported tokens makes token
efficiency explicitly uncertain and prevents a combined efficiency-rule pass;
correctness results remain reported separately. Positive reported totals still
do not prove complete per-request billing coverage.
