# Product review: make release decisions from evidence

Reviewed 12 November 2026 against the v0.2 workbench, its browser verification
screenshots, the experiment API and the existing report comparator. These are
proposed improvements, not implemented features or a change to the live-run
configuration. No code or evaluation evidence was modified for this review.

The current workbench already answers “what happened in this experiment?” well:
background progress, cancellation, baseline/guarded results, per-run traces,
checks, ledger state and JSON export are usable. The next product gap is deciding
whether a new runtime version should replace a previous one. The command-line
comparator has stronger release checks than the browser exposes.

## 1. Compare a candidate with a named reference in the workbench

**User problem.** History opens one experiment at a time. Two green experiment
gates can hide a particular case becoming worse, and manually comparing two
aggregate percentages loses suite/model compatibility checks. An engineer should
not have to leave the UI and reconstruct a command to make this release decision.

**Concrete workflow.** Open the candidate, choose **Compare with reference**, and
select a previous completed experiment. The review names both experiment IDs and
dates, shows suite/model/revision/repeat compatibility, and discloses prompt and
source changes. It then presents the existing comparator's decision, denominators,
token totals, p95 latency and guarded case regressions. Keep **Experiment gate**
and **Release comparison** visibly distinct; passing the former does not imply
passing the latter. A rejected comparison shows the actual incompatibility and
retains the selections, with no computed green result.

**Smallest implementation scope.** Add a read-only comparison endpoint accepting
two stored experiment IDs, delegating to `agentproof.comparison.compare_reports`.
Use stored documents, not caller-supplied success counts. Add one comparison panel
with two selectors and a metadata disclosure; retain the comparator's 0.90 default
and existing refusal rules. Export the returned comparison plus input fingerprints.
Start with saved local experiments; importing arbitrary report files and editing
release policies can wait. Reuse the existing Python comparator rather than
reimplementing grading in TypeScript. Comparison must not enqueue trials or call
a model. Source/prompt differences are the intended change under evaluation;
changed suite/model settings remain a refusal, not a warning that can be ignored.

**Meaningful browser acceptance cases.**

- Choose two completed, compatible experiments: counts and the comparison gate
  match the Python comparator, the browser sends no experiment submission,
  and the QA server records no new provider calls.
- Use a candidate whose aggregate improves while one guarded case loses a pass:
  the experiment gate can remain green, but the comparison fails and identifies
  that case.
- Change a suite label or model revision, or select an incomplete experiment:
  show a specific refusal and no success summary. A prompt/source-only change
  remains comparable and is clearly disclosed.
- Switch the reference rapidly while a response is pending: only the latest
  selection may populate the comparison. Refreshing a URL containing both IDs
  restores their roles without reversing reference and candidate.

## 2. Open a regression directly into the evidence that explains it

**User problem.** The current **Failures** filter finds failures within one
experiment, not cases that worsened between versions. The comparator returns
per-case counts, but the UI has no route from a regression to the relevant prior
and candidate traces. Engineers spend time searching history and remembering
which trial they inspected instead of investigating the change.

**Concrete workflow.** From the comparison, select **Regressions** to show guarded
cases with a lower correctness count or effect-invariant count. Each row shows
`before x/n → after y/n`, the observed outcome lists and the kind of decrease.
Opening a row keeps the reference and candidate visible, with a trial selector
for each side and the existing **Trace / Checks / Final state** views. Highlight
failed checks first; allow every event and ledger entry to be inspected. **Next
regression** stays in the same filtered set. A stable link retains both experiment
IDs, scenario, strategy and selected run IDs.

**Smallest implementation scope.** Build on `case_changes` from improvement 1;
join stored runs by scenario ID and strategy, then reuse the current inspector
components in a two-column desktop view and labelled stacked mobile view. Default
to a failed candidate run and a successful reference run when those exist, but
show the selected run IDs and permit other repeats. Keep this view read-only so
an approval decision cannot silently alter evidence during review. Do not claim
that “trial 1” in two experiments is a matched random sample. Avoid an automatic
“root cause” narrative: surface check names, actual proposals, feedback, outcome
and effects; the engineer supplies the explanation.

**Meaningful browser acceptance cases.**

- Select an aggregate-hidden regression: both inspectors contain that scenario
  and their own experiment/run IDs, and the candidate's failed check is visible.
- A case with three repeats and only one new failure exposes all three candidate
  runs; selecting another repeat updates its trace and ledger together.
- An effect-invariant decrease is included even if the number of correct outcomes
  is unchanged. An unchanged case does not appear under **Regressions**.
- Filters and **Next regression** preserve the reference/candidate direction;
  reloading the deep link restores the same case. At 390px both labelled panes
  are readable without horizontal overflow.

## 3. Launch a comparable rerun from the stored suite snapshot

**User problem.** The composer starts from today's built-in suite or a file
import. Recreating an older experiment by name can select changed cases or omit
the original repeats. A single-run replay is useful for debugging, but cannot
supply complete paired evidence for a release comparison. The UI also does not
show the stored configuration fields that already exist in each export.

**Concrete workflow.** Open a completed experiment and choose **Run this suite
again**. The composer loads its exact stored scenario array, order and repeat
count, identifies the source experiment and shows the number of planned trials.
A configuration review compares the recorded provider/model/revision and limits
with the current server settings. The user can run the copied suite against the
current runtime; changed model settings are explicitly labelled as preventing a
like-for-like comparison. The old evidence stays unchanged. The new experiment
links back to its source but receives new IDs and its own current fingerprints.

**Smallest implementation scope.** Expose the already stored scenario/configuration
snapshot to the typed UI, prefill the existing custom-suite composer, and add an
optional source-experiment ID as provenance. The server remains authoritative for
current provider settings; do not pretend that copying metadata changes model
weights or endpoint configuration. Before submission, show only non-secret
configuration and whether a later comparison would be compatible. Do not
introduce another execution path: submit through the current durable queue.
Editing the copied cases creates a new suite and is labelled accordingly. Keep
**Replay in fresh sandbox** as the separate single-run debugging action.

**Meaningful browser acceptance cases.**

- Rerun an old custom suite after the built-in suite changes: the submitted
  scenario array/order and repeats equal the saved snapshot, not today's defaults.
- Show a provider/model setting mismatch before submission; the saved reference
  is unchanged and the new export records actual current settings, never copied
  historical values masquerading as current ones.
- Edit one copied scenario: the new suite hash changes, the UI marks it as edited,
  and the comparator refuses a like-for-like release claim.
- Complete the copied experiment: it has full paired coverage and new run IDs.
  Cancelling it retains partial evidence and never enables a passing comparison.

## Recommended order

Implement comparison first, regression inspection second, then snapshot-based
reruns. The first two turn the existing rigorous comparator into a usable review
workflow with little new evaluation logic. The third reduces accidental
incompatibility when producing the next candidate. None requires another agent
framework, a new vector database, hosted infrastructure, or invented performance
claims.

Current implementation references: [workbench](../web/src/App.tsx),
[experiment API](../src/agentproof/api.py),
[comparator](../src/agentproof/comparison.py),
[CLI comparison](../scripts/compare.py), and
[evaluation protocol](EVALUATION_PROTOCOL.md).
