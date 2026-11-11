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
accuracy. The accounting policy below separates current response metadata from
historical aggregate-only evidence. No monetary cost is inferred.

## Token accounting across retries

Proposal-budget ablation reports now distinguish per-response accounting from
older aggregate-only evidence. This is an analysis change: it does not change
model requests, prompts, token limits, proposal budgets, retries, correctness
grading or the provider's `tuple[str, int]` interface. It makes no model calls.

### Why a positive trial total is insufficient

A trial can make two actual requests. Its first response can omit usage while
its second reports ten tokens. The trial then records ten reported tokens, even
though the first request's usage is unknown. Checking only whether the trial's
total is zero misses this gap. A rejected response wrapper creates a similar
problem: diagnostics can expose a usage field, but the provider raises before
returning the tuple that contributes tokens to the run total.

The analysis therefore checks each actual model-attempt event when response
diagnostics are available. These diagnostics contain usage availability and
parser status, not the token count of each response or raw generated text.
The analysis cannot reconstruct missing totals or independently attest the
provider's reported accounting.

### Current metadata-aware policy

If any actual model attempt in the study has a `response_diagnostics` field,
the whole study uses `per_response_diagnostics`. All actual attempts must then
have accounting evidence. This prevents a trial with no response after a
connection failure from being misclassified as older aggregate-only evidence.
Deterministic provider-fault injections are excluded because they make no HTTP
request. Read failures that prevent any model attempt also need no model usage.

An actual attempt has incomplete accounting when:

- Its response diagnostics are absent or malformed.
- Usage is absent, invalid, missing its total, or otherwise unknown.
- The HTTP status or parser category cannot establish the response path.
- Proposal parsing was not attempted, or the recorded error is `ProviderFailure`.
  Even a valid usage field in a rejected wrapper does not establish that its
  count was added to the run total.

A proposal that fails JSON or schema validation can still have accounted usage:
the provider returned its token tuple before the proposal parser rejected the
content. Empty content is handled the same way. These failures remain failures
for workflow purposes; accounting and task correctness are separate questions.

Each arm reports `token_usage_coverage`: the policy, actual request count,
accounted and incomplete attempt counts, affected trial count and fixed reason
categories. A study with any incomplete attempt cannot pass
`adoption.passes_declared_study_rules`. Its correctness result remains separately
available as `adoption.correctness_supported`. Additional reported tokens per
additional correct outcome are withheld when usage is uncertain; reported totals
remain visible rather than being replaced with guessed values.

The historical conservative zero-total check remains in force. An explicitly
reported zero is distinguishable from missing metadata, but it still does not
establish free inference or pass the token-efficiency rule for that trial.
Complete response coverage means every attempt supplied the required accounting
metadata; it is not a guarantee that provider token totals are accurate.

### Historical exports and the frozen study

An entirely older export with no per-response diagnostics uses
`legacy_aggregate_only`. Its per-attempt accounted/incomplete counts are null,
not fabricated zeros. The JSON and Markdown reports display this policy and
state that positive aggregate totals do not establish complete usage coverage.

For these exports, the predeclared historical rule is retained: zero reported
trial totals create uncertainty, more than 50% additional reported tokens raises
an efficiency flag, and the existing latency and correctness rules still apply.
A historical report can therefore pass its declared rules while remaining
aggregate-only. That result describes the old reported-total policy; it does
not certify the stronger per-response coverage requirement. The analysis does
not retroactively change the experiment's design or imply that missing historical
telemetry was collected.

Raw exports are never rewritten by analysis. Re-analysis creates derived summary
and Markdown files with the selected accounting policy. Frozen study data and
the separately frozen ablation checkout remain unchanged. The warm-up remains
excluded from trial efficiency metrics and recorded separately; this change
does not invent response diagnostics for historical warm-up records.

### Verification

The integration tests use deterministic fixture executions and HTTP MockTransport
responses only. They exercise mixed known/missing usage, missing diagnostics in
another trial, malformed usage, rejected wrappers with known usage, JSON parsing
failures with counted tokens, injected non-network faults, explicit zero totals,
and legacy re-analysis without changing raw bytes. No real-model calls or
independent verification cases are used.
