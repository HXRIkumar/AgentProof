import type {
  AnswerProviderMetadata,
  AnswerReport,
  AnswerResult,
} from "./answerTypes";
import { budgetDelta, number, usd } from "./answerUtils";

export function ModelMetadata({
  provider,
  model,
}: {
  provider?: AnswerProviderMetadata;
  model?: string;
}) {
  const local =
    provider?.generator_provider === "local" &&
    provider?.critic_provider === "local";
  return (
    <div className="al-model-metadata">
      <dl>
        <div>
          <dt>Draft model</dt>
          <dd>{provider?.model || model || "Unrecorded"}</dd>
        </div>
        <div>
          <dt>Configured critic</dt>
          <dd>{provider?.critic_model || "Unrecorded"}</dd>
        </div>
      </dl>
      <p>
        {local
          ? "Local inference · no API charge. Hardware and energy costs are not measured."
          : provider?.generator_provider || provider?.critic_provider
            ? `Draft provider: ${provider.generator_provider || "unrecorded"} · critic provider: ${provider.critic_provider || "unrecorded"}. API estimates exclude local compute.`
            : "Provider and API pricing were not recorded for this experiment."}
      </p>
    </div>
  );
}

export function RunAccounting({
  result,
  provider,
}: {
  result: AnswerResult;
  provider?: AnswerProviderMetadata;
}) {
  const usage = result.usage;
  const metadata = { ...provider, ...result };
  const costRecorded = usage.cost_known !== undefined;
  const reused = usage.reused_calls ?? 0;
  const local =
    metadata.generator_provider === "local" &&
    (result.strategy !== "adaptive" || metadata.critic_provider === "local");
  return (
    <details className="al-run-accounting">
      <summary>
        <span>Models & API cost</span>
        <b>
          {costRecorded
            ? usage.cost_known
              ? `${usd(usage.estimated_cost_usd)} estimated`
              : "Estimate unknown"
            : local
              ? "No API charge"
              : "Cost unrecorded"}
        </b>
      </summary>
      <ModelMetadata provider={metadata} />
      <dl className="al-accounting-grid">
        <div>
          <dt>Standalone policy calls</dt>
          <dd>{number(usage.calls)}</dd>
        </div>
        <div>
          <dt>Actual calls in this record</dt>
          <dd>{number(usage.actual_calls)}</dd>
        </div>
        <div>
          <dt>Reused study calls</dt>
          <dd>{number(usage.reused_calls)}</dd>
        </div>
        {costRecorded && (
          <>
            <div>
              <dt>Policy API estimate</dt>
              <dd>{usd(usage.cost_known ? usage.estimated_cost_usd : null)}</dd>
            </div>
            <div>
              <dt>Policy accounted amount</dt>
              <dd>{usd(usage.accounted_cost_usd)}</dd>
            </div>
            <div>
              <dt>Actual accounted amount</dt>
              <dd>{usd(usage.actual_accounted_cost_usd)}</dd>
            </div>
          </>
        )}
      </dl>
      <p>
        {reused > 0
          ? "The policy includes a shared initial response. Actual calls and amounts exclude that reused response in this record; the study counts it once."
          : "Standalone policy usage includes all generation and critic calls recorded for this result."}
      </p>
      {costRecorded && (
        <p>
          API cost is a client-side estimate, not an invoice. Accounted amounts
          retain unresolved reservations; an unknown estimate is not zero.
        </p>
      )}
    </details>
  );
}

export function StudyAccounting({ report }: { report: AnswerReport }) {
  const usage = report.actual_usage;
  const hosted = report.hosted_experiment;
  if (!usage && !hosted) return null;
  const before = hosted?.budget_before,
    after = hosted?.budget_after;
  const ledgerChange = budgetDelta(before, after, "accounted_usd");
  const local =
    report.configuration.runtime?.provider?.generator_provider === "local" &&
    report.configuration.runtime?.provider?.critic_provider === "local";
  return (
    <section
      className="al-study-accounting"
      aria-label="Actual study accounting"
    >
      <h3>Actual study usage</h3>
      <dl className="al-accounting-grid">
        <div>
          <dt>Model calls</dt>
          <dd>{number(usage?.calls)}</dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd>{usage?.usage_known ? number(usage.total_tokens) : "Unknown"}</dd>
        </div>
        <div>
          <dt>Shared first responses</dt>
          <dd>{number(usage?.shared_initial_generations)}</dd>
        </div>
        <div>
          <dt>Study API estimate</dt>
          <dd>
            {local
              ? "No API charge"
              : usd(usage?.cost_known ? usage.estimated_cost_usd : null)}
          </dd>
        </div>
      </dl>
      <p>
        Shared first responses count once here. Policy totals above describe
        standalone runs and must not be added to estimate study spend.
      </p>
      {(hosted || usage?.cost_known !== undefined) && (
        <details className="al-billing-details">
          <summary>Cost accounting details</summary>
          <dl className="al-accounting-grid">
            <div>
              <dt>Study accounted amount</dt>
              <dd>{usd(usage?.accounted_cost_usd)}</dd>
            </div>
            {hosted && (
              <>
                <div>
                  <dt>Ledger change · may include other studies</dt>
                  <dd>{usd(ledgerChange)}</dd>
                </div>
                <div>
                  <dt>Unresolved reservations · entire ledger</dt>
                  <dd>{number(after?.unresolved_reservations)}</dd>
                </div>
              </>
            )}
          </dl>
          <p>
            API estimates use reported tokens and configured prices, not an
            invoice. Accounted amounts retain unresolved reservations. Study
            totals come from individual calls; ledger changes are provenance
            only and may include concurrent studies.
          </p>
        </details>
      )}
    </section>
  );
}
