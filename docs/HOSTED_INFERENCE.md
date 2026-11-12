# Optional hosted inference with a shared spending guard

Hosted requests are **off by default**. The local generator and critic continue to
work without an OpenAI key. Automated adapter tests use fake credentials and mocked
HTTP. Separately enabled live studies record their real calls, tokens and estimated
costs in the evidence archive.

The adapter permits one paid snapshot: `gpt-5.4-mini-2026-03-17`, at the exact
endpoint `https://api.openai.com/v1`. Other paid models/endpoints are rejected.
The official [model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
lists standard input at **$0.75 per million tokens** and output at **$4.50 per
million tokens**. This price snapshot was checked on 12 November 2026. Cached-input
discounts are deliberately ignored by the local cost estimate.

## Configuration

The explicit opt-in is `ANSWER_LAB_ENABLE_PAID=1`. Setting a key alone never enables
paid requests. Use the separate secure setup helper to save a key; never paste a key
into a prompt, committed file, shell command or terminal log. At request time only,
the adapter reads `OPENAI_API_KEY`, or falls back to the private owner-only regular
file `~/.config/agentproof/openai-key`. Symlink and group/world-readable key files are
rejected. Configuration reports and errors do not include keys or endpoint credentials.

For a local draft with the hosted critic:

```sh
export ANSWER_LAB_ENABLE_PAID=1
export ANSWER_LAB_BASE_URL=http://127.0.0.1:8089/v1
export ANSWER_LAB_MODEL=your-running-local-model
export ANSWER_LAB_CRITIC_BASE_URL=https://api.openai.com/v1
export ANSWER_LAB_CRITIC_MODEL=gpt-5.4-mini-2026-03-17
export ANSWER_LAB_CRITIC_MAX_TOKENS=1536
export ANSWER_LAB_OPENAI_REASONING_EFFORT=low
```

For a separately labelled all-hosted comparison, set both the generator base URL/model
and the critic base URL/model to that same allowlisted endpoint and pinned snapshot.
`ANSWER_LAB_MAX_TOKENS` controls the hosted generator's output budget;
`ANSWER_LAB_CRITIC_MAX_TOKENS` controls the critic. Each must be 64–4096.

Hosted requests use Chat Completions with `n=1`, `stream=false`, `store=false`,
`response_format=json_object`, `service_tier=default`, and the selected reasoning
effort (`none`, `low`, `medium`, `high`, `xhigh`; default `low`). They omit
`temperature` and local MLX template arguments. Local requests retain their existing
temperature and thinking settings. The [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
defines `max_completion_tokens` as covering visible output and reasoning tokens.
Reported completion tokens are counted once; reasoning tokens are not added again.

## One durable USD 1.50 ceiling

Every production adapter shares:

`~/.config/agentproof/hosted-budget.sqlite3`

There is no environment variable for a per-run replacement ledger and no reset,
refund or automatic expiry method. A new run, restart or separate process continues
using the same ledger. Existing lower ceilings are never increased when reopened.
The default ceiling is **USD 1.50 total**, leaving a buffer relative to the user's
reported USD 2 balance. Manually removing or modifying the ledger invalidates this
protection; application code never does that.

Before each HTTP request, a SQLite `BEGIN IMMEDIATE` transaction reserves:

```text
input bound = UTF-8 bytes of the JSON text messages + 2048 + 256 per message
reservation = input bound × $0.75 / 1,000,000
            + max_completion_tokens × $4.50 / 1,000,000
```

The calculation only permits bounded text messages, without tools, images, multiple
choices, files or other unpriced modalities. Integer nanodollars avoid cumulative
floating-point budget errors. Concurrent processes cannot both spend the same
remaining reservation balance.

A valid response with the pinned model, standard tier and valid usage replaces its
reservation with a conservative standard-price estimate from the reported token
counts. It does not apply prompt-cache discounts. Missing usage, timeout, HTTP error,
interruption or uncertain outcome retains the full reservation. Unresolved
reservations survive restart and cannot be automatically released later. If reported
usage exceeds a bound or the provider returns another model/tier, the ledger freezes
further paid requests. Redirects and automatic transport retries are disabled.

This is an **application-side conservative guard, not an account billing hard cap**.
The byte estimate includes generous framing overhead but is not a provider-attested
token count. Price changes, taxes, unrelated account activity and provider billing
rules remain outside its control. Review the actual OpenAI usage dashboard separately.

## Inspecting and interpreting accounting

These methods read only the ledger; they do not read a key or send a request:

```python
from agentproof.answers.hosted_budget import BudgetLedger
status = BudgetLedger().snapshot()
# Or: status = service.adapter.budget_status()
```

Snapshots report `ceiling_usd`, `accounted_usd`, `reported_usage_estimate_usd`,
`remaining_reservable_usd`, `reservations`, `unresolved_reservations`, and `frozen`.
The difference between snapshots before and after a study is its additional
accounted amount only when no other paid study overlaps it. These cumulative totals
include every process using the ledger. For concurrent studies, use each report's
`actual_usage` to attribute calls and estimated costs; do not assign the entire
shared-ledger change to one study.

Each model response records whether a request was actually sent and its reservation
state. Run usage separates logical policy cost (including a shared initial answer)
from actual newly sent calls and their accounted cost. A budget-denied request is
blocked, not a zero-token model response. `estimated_cost_usd` stays null if any
paid outcome has uncertain cost; `accounted_cost_usd` includes retained reservations.
Neither field is an invoice total. Local inference has no API charge but still uses
hardware, energy and processing time.

## Verification

Mock-only tests cover independent processes competing for one ceiling, restart
persistence, unknown outcomes, lower-only ceilings, missing/deleted ledgers,
explicit opt-in, model/endpoint restrictions, redirects, HTTP errors, timeouts,
provider identity/bound mismatches, token accounting and secret redaction. No test
reads the user's key file or calls a paid endpoint.
