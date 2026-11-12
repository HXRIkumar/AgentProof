# A two-minute AgentProof demonstration

Start the application using [the README](../README.md#run-it). The first route
below works with an empty experiment database and no configured model.
It also works in the [public recorded-evidence viewer](https://hxrikumar.github.io/AgentProof/),
which runs no backend or inference. The scripted action demonstration requires
the full local application.

## Recorded evidence: inspect a real failure in about one minute

1. Under **Recorded evidence**, choose **Challenge suite · v0.2**. The banner
   says **Read-only · recorded model evidence**. This opens saved local-model
   results; it does not run inference or populate workspace history.
2. Open **Recorded provenance**. Point out the model revision, executed workflow
   version and report SHA-256. Close it to return to the results.
3. In **Search scenarios**, enter **Suggested nominal refund**. Select the
   guarded trial **1**. In the **Run inspector**, open **Checks** and scroll
   within the inspector to the failed **task outcome** check.
4. Open **Final state**: `effects` is empty and `total_refunded_cents` is zero.
   Then open **Trace** to inspect why the workflow escalated. No incorrect
   refund occurred, but the requested valid task was not completed.
5. Choose **Independent verification · v0.3**. Its guarded workflow passed
   **48/48 trials across 24 separately authored synthetic cases, with two
   repeats per case**. Select **Download recorded JSON** to obtain the exact
   original report bytes, matching the SHA-256 in its provenance.

Suggested explanation:

> “AgentProof checks what the agent actually did against the transaction ledger.
> This is recorded local-model evidence, not a model call happening now. The
> challenge run completed 54 of 60 guarded trials. Here is one remaining failure:
> it escalated without writing a refund, so safety and useful completion are
> separate outcomes. The independent set then tests another 24 synthetic cases.
> These results support the tested workflow; they are not a general model score.”

A hash confirms that the downloaded bytes match the repository's curated report;
it is not an independent signature or proof of authorship. Archived pending
approvals are historical observations. They cannot be approved, replayed or
changed from this view. The independent suite is small, and overlapping suites
and repeated trials must not be counted as independent benchmark tasks.

![Recorded independent verification in an empty workspace](screenshots/recorded-evidence.png)

![A recorded guarded failure and its task check](screenshots/recorded-failure.png)

## Scripted workspace: demonstrate an action and its ledger

This is a separate demonstration that creates new local experiment records.
It tests fault handling deterministically; it does not measure model quality.

1. Select **New experiment**. Keep **Decision provider** set to **Scripted
   fixture · no API calls**, **Trials per scenario** at **1 trial**, and the
   built-in scenarios selected. Choose **Run 48 trials**.
2. When results finish, search **Committed, then timed out**. Inspect the
   baseline and guarded trial **1**. Compare **Trace** and **Final state**:
   the baseline duplicates the effect; the guarded workflow reconciles the
   stable operation key and retains one effect.
3. Explain the boundary: this console uses an injected sandbox fault. The
   separate [remote tool lab](REMOTE_TOOL_LAB.md) exercises a real localhost
   server process, persistent ledger, socket closure and restart. Neither
   demonstration sends real payments.

A useful closing line:

> “In a live run, the model proposes an action. Deterministic policy checks, operation identity,
> approval rules and ledger-based grading decide whether that action is allowed
> and whether the workflow actually succeeded.”

## Demonstration assets

The repository screenshots were captured from an empty workspace while browsing
recorded reports: no experiment writes, live provider configuration or inference
calls. The mobile capture uses a 390 × 844 viewport.

![Recorded evidence at a narrow viewport](screenshots/recorded-mobile.png)

The optional local walkthrough is `artifacts/agentproof-demo.webm`, with capture
checks in `artifacts/demo-verification.json`. Those generated artifacts are
ignored by Git and are not required to run the application.
