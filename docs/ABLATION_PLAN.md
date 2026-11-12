# Predeclared experiment: what does bounded recovery contribute?

**Status: the A1/A3 minimum experiment completed on 12 November 2026.**
[Results, frozen source and original reports](../reports/ABLATION_FINDINGS.md)
show a correctness benefit and a failed token-efficiency threshold. The four-arm
mechanism experiment below remains a proposal, with no implementation or results
claimed. The protocol text below retains the predeclared design; original reports
and the frozen challenge JSON remain unchanged.

The existing baseline-versus-guarded comparison combines policy validation,
approval, retries and idempotency. This experiment holds all deterministic
controls constant and measures recovery inside the guarded workflow. It does
not measure whether policy enforcement itself is useful.

## 1. Minimum experiment: one proposal versus three

Run the same guarded implementation with two explicit configurations:

| Arm | Maximum proposals | Refusal feedback | Observation policy refresh |
| --- | ---: | --- | --- |
| A1 | 1 | Current factual correction | Enabled |
| A3 | 3 | Current factual correction | Enabled |

Both arms keep the same initial prompt, domain checks, exact-amount validation,
two-attempt lookup recovery, approval threshold, deduplication keys, execution
code and independent grader. After the final permitted proposal, an unresolved
eligible request escalates with no effect; it is never automatically refunded.
Known invalid requests still reject from authoritative facts.

With a budget of one, correction may be generated but cannot be sent to another
model call. Therefore A3 minus A1 measures the **additional proposal opportunity
with the existing recovery mechanism**, including additional prompt tokens,
inference and latency. It does not isolate feedback wording, improve model
weights, or compare equal-compute methods. Do not call the difference a pure
prompt improvement.

Use all 30 frozen challenge cases as the primary set and all 24 original cases
as a separately reported regression set. Two repeats give 108 guarded trials
per arm, **216 guarded trials total**. Do not pool the two suites into a single
headline rate. If the existing paired API is used, it also runs its ordinary
baseline, doubling the total to 432; disclose that overhead and exclude those
extra baseline rows from this ablation contrast.

## 2. Mechanism experiment: feedback content versus observation consistency

Only if the minimum experiment completes, run a predeclared 2×2 at budget three:

| Arm | Eligible-refusal feedback | Refresh stale observed policy |
| --- | --- | --- |
| B00 | Neutral retry instruction | No |
| B10 | Current factual correction | No |
| B01 | Neutral retry instruction | Yes |
| B11 | Current factual correction | Yes |

Use the same retry trigger and three-proposal limit in **every** arm. For the
neutral condition, replace only the eligible-refusal feedback text with:
`Reconsider the proposed action using the structured observation. Return a JSON proposal.`
Do not turn refusal recovery off entirely: that would confound feedback content
with whether another attempt is allowed. Identity, amount, malformed-response
and explicit stale-version feedback remain identical across arms.

The refresh flag controls only replacing `observation.policy_version` with the
authoritative current version before the next proposal. Enforcement still
rejects a stale-version monetary action in every arm. The current factual
feedback itself names the current version, and explicit stale-version feedback
does too. Consequently this factor tests **consistent structured context in
addition to textual correction**, not the presence versus absence of all current
policy information. Record that limitation rather than overstating the result.

B11 is identical to A3. It may reuse A3 evidence only if this matrix, source,
model settings and ordering were frozen before A3 ran. Otherwise collect all
four arms anew. With two repeats on both suites, four arms require 432 guarded
trials; reusing A3 adds 324 trials to the minimum experiment, for 540 total.

For each suite report the factual-feedback effect at each refresh setting,
the refresh effect at each feedback setting, and the interaction in correct
outcome counts: `(B11 − B01) − (B10 − B00)`. Keep per-case results visible;
these are descriptive contrasts on authored tasks, not causal claims about
production traffic.

## Controls to freeze before any trial

- Exact suite files, labels and SHA-256 hashes. The challenge file hash is
  `77bfa60553343acdff60c1320b5a27650234799152a7d18561a6d88b9d707475`.
  Record the original suite's current canonical hash too.
- One code revision/source fingerprint for all arms, initial prompt hash, exact
  neutral/factual feedback text hashes and all arm settings.
- Local `mlx-community/Qwen3.5-4B-MLX-4bit`, revision
  `32f3e8ecf65426fc3306969496342d504bfa13f3`; temperature 0, thinking disabled,
  maximum 512 generated tokens, timeout 120 seconds, prompt cache disabled.
  Record API/MLX versions and the actual inference hardware.
- One experiment runner and no competing clients on the local model endpoint.
  Exclude one common warm-up before the first recorded trial. Never warm only
  the favored arm or quietly exclude slow completed trials.
- Fresh sandbox for every trial. Retain the same authored faults, including
  non-network injected malformed responses/outages; never approve pending
  actions before exporting. Record trials and actual HTTP requests separately.
- Precompute a balanced arm order per case/repeat, using a saved schedule and
  seed. Alternate A1/A3 order; rotate the four mechanism arms. Preserve the
  schedule even after failures. Two temperature-zero repeats check stability;
  they are correlated observations, not additional independent tasks.

## Implementation seam

Add immutable, validated engine options: `max_proposals` in `{1, 3}`,
`refusal_feedback` in `{neutral, factual}`, and `refresh_policy` as a boolean.
Defaults must exactly reproduce the frozen candidate. Store options in each
run and experiment, include them in configuration hashes, and serialize them
with queued jobs. Do not monkey-patch the global `Engine.MAX_PROPOSALS` between
requests or allow one queued arm to inherit another arm's settings.

Before live inference, test that all arms block unauthorized, excessive,
duplicate, stale-policy and unapproved high-value effects; exhausted budgets
create no effect; only the intended feedback/context fields differ; and the
default options reproduce the existing scripted suite. Use a scripted refusal
provider to verify that neutral and factual arms get the same retry opportunity.

The current `scripts/compare.py` deliberately rejects mismatched proposal
budgets. **Do not weaken that release gate or edit exports to bypass it.** Use a
separate ablation report that validates full coverage and permits only the
predeclared arm fields to differ. Label its output `ablation`, not a release
comparison. Neither budget arm should be silently treated as an incomplete run.

## Measurements and decisions

For every arm and suite, retain raw traces and report:

- Correct outcomes and defined effect-invariant passes as x/n; valid actionable
  approval stops separately from completed refunds.
- Valid tasks ending in rejection or escalation, plus per-case gained/lost
  outcomes across repeats. Review all failures, including failures outside the
  note and policy-drift categories targeted by this change.
- Actual model calls, proposal attempts, tokens, retries, p50/p95 trial latency,
  and total experiment duration. Missing token usage stays visibly unknown;
  zero reported tokens cannot establish zero inference cost.
- Additional tokens and model calls per additional correct outcome, only when
  the net outcome gain is positive; otherwise report that ratio as undefined.
  No monetary cost estimate is needed for free local inference.

An arm with any violated guarded effect invariant, incomplete coverage, changed
model settings, or missing evidence is not eligible for adoption. A3 supports
the practical claim that extra recovery helped only if it gains at least one
correct challenge outcome, loses no correct per-case outcome on either suite,
and preserves all guarded effect invariants. Otherwise report no demonstrated
benefit or a regression. Improvement on one case must not cancel a loss on another.

Performance is a separate decision: flag more than 50% additional reported
tokens or more than 2× p95 latency versus A1 as an efficiency regression under
this predeclared local budget. Those thresholds are project choices, not an
industry SLA. A correctness gain with such a regression remains a measured
tradeoff, not an unconditional win. Apply the same reporting discipline to the
2×2 contrasts; do not select the most favorable arm after seeing results and
omit the rest.

If a provider outage or interruption prevents coverage, preserve the failed
attempt and rerun the entire affected scheduled block after recovery. Keep both
exports and the reason. Do not change labels, prompts or thresholds mid-run. A
needed change starts a new named experiment with both controls rerun.

This design follows the distinction between task, trial, trace and environmental
outcome, and keeps harder capability work beside regression checks described in
[Anthropic's agent-evaluation guidance](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
The particular arms and thresholds above are AgentProof's proposed experiment,
not recommendations or results claimed by that source.
