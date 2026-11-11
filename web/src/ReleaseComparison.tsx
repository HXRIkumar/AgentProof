import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  GitCompareArrows,
  LoaderCircle,
  ShieldCheck,
  ShieldX,
  X,
} from "lucide-react";
import { api } from "./api";
import type { CaseChange, Experiment, ReleaseComparisonResponse } from "./types";

const delta = (value: number, decimals = 0) =>
  `${value > 0 ? "+" : ""}${value.toFixed(decimals)}`;
const words = (value: string) => value.replaceAll("_", " ");
const regressed = (row: CaseChange) =>
  row.correct_delta < 0 || row.safe_delta < 0;
const improved = (row: CaseChange) =>
  !regressed(row) && (row.correct_delta > 0 || row.safe_delta > 0);

type Evidence = {
  report: ReleaseComparisonResponse;
  reference: Experiment;
  candidate: Experiment;
};

function EvidencePane({
  experiment,
  row,
  role,
}: {
  experiment: Experiment;
  row: CaseChange;
  role: "Reference" | "Candidate";
}) {
  const runs = (experiment.runs ?? []).filter(
    (run) => run.scenario_id === row.scenario_id && run.variant === row.variant,
  );
  const preferred =
    runs.find((run) => (role === "Candidate" ? !run.passed : run.passed)) ??
    runs[0];
  const [runId, setRunId] = useState(preferred?.id ?? "");
  const [tab, setTab] = useState("checks");
  const run = runs.find((item) => item.id === runId) ?? preferred;
  if (!run) return <p>No stored trial evidence is available.</p>;
  return (
    <section
      className="comparison-evidence-pane"
      aria-label={`${role} evidence`}
    >
      <header>
        <span className="eyebrow">
          {role} · {row.variant}
        </span>
        <h4>{experiment.name}</h4>
        <small className="mono">Experiment {experiment.id.slice(0, 8)}</small>
      </header>
      <div className="comparison-trial-picker">
        <label>
          {role} trial
          <select
            value={run.id}
            onChange={(event) => setRunId(event.target.value)}
          >
            {runs.map((item, index) => (
              <option key={item.id} value={item.id}>
                Trial {index + 1} · {item.passed ? "pass" : "fail"} ·{" "}
                {words(item.outcome)}
              </option>
            ))}
          </select>
        </label>
        <div className="comparison-run-meta">
          <span className={`status ${run.passed ? "pass" : "fail"}`}>
            {run.passed ? "Pass" : "Fail"}
          </span>
          <span>{words(run.outcome)}</span>
          <span className="mono">Run {run.id.slice(0, 8)}</span>
        </div>
      </div>
      <div
        className="comparison-tabs"
        role="tablist"
        aria-label={`${role} evidence views`}
      >
        {["checks", "trace", "final state"].map((value) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
          >
            {value === "final state"
              ? "Final state"
              : value[0].toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      <div className="comparison-evidence-content">
        {tab === "checks" &&
          [...run.checks]
            .sort((a, b) => Number(a.passed) - Number(b.passed))
            .map((check) => (
              <div
                key={check.name}
                className={`comparison-check ${check.passed ? "pass" : "fail"}`}
              >
                {check.passed ? (
                  <ShieldCheck size={14} />
                ) : (
                  <ShieldX size={14} />
                )}
                <div>
                  <b>{words(check.name)}</b>
                  <p>{check.detail}</p>
                </div>
              </div>
            ))}
        {tab === "trace" &&
          run.events.map((event) => (
            <details key={event.index} className="comparison-event">
              <summary>
                <span>
                  {event.index + 1}. {words(event.name)}
                </span>
                <small>
                  {event.status} · {event.duration_ms.toFixed(1)} ms
                </small>
              </summary>
              <pre>{JSON.stringify(event.detail, null, 2)}</pre>
            </details>
          ))}
        {tab === "final state" && (
          <pre>{JSON.stringify(run.final_state, null, 2)}</pre>
        )}
      </div>
    </section>
  );
}

export default function ReleaseComparison({
  candidate,
  history,
}: {
  candidate: Experiment;
  history: Experiment[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [referenceId, setReferenceId] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [variant, setVariant] = useState<"baseline" | "guarded">("guarded");
  const [filter, setFilter] = useState("changed");
  const [selectedCase, setSelectedCase] = useState<CaseChange | null>(null);
  const request = useRef<AbortController | null>(null);
  const references = history.filter(
    (item) => item.id !== candidate.id && item.status === "completed",
  );

  function invalidate() {
    request.current?.abort();
    setEvidence(null);
    setSelectedCase(null);
    setError("");
    setPending(false);
  }
  useEffect(() => {
    invalidate();
    return () => request.current?.abort();
  }, [candidate]);

  async function compare() {
    if (!referenceId || candidate.status !== "completed") return;
    invalidate();
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    try {
      const report = await api<ReleaseComparisonResponse>(
        "/comparisons",
        { reference_id: referenceId, candidate_id: candidate.id },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setEvidence({
        report,
        reference: report.reference_snapshot,
        candidate: report.candidate_snapshot,
      });
      setVariant("guarded");
      setFilter(
        report.case_changes.some(
          (row) => row.variant === "guarded" && regressed(row),
        )
          ? "regressed"
          : "changed",
      );
    } catch (err) {
      if (!controller.signal.aborted)
        setError(
          err instanceof Error
            ? err.message
            : "Unable to compare these experiments.",
        );
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }
  function download() {
    if (!evidence) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(evidence.report, null, 2)], {
        type: "application/json",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `agentproof-comparison-${evidence.report.reference_id.slice(0, 8)}-${evidence.report.candidate_id.slice(0, 8)}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const report = evidence?.report;
  const allRows =
    report?.case_changes.filter((row) => row.variant === variant) ?? [];
  const rows = allRows.filter(
    (row) =>
      filter === "all" ||
      (filter === "regressed" && regressed(row)) ||
      (filter === "improved" && improved(row)) ||
      (filter === "changed" && (regressed(row) || improved(row))),
  );
  const names = new Map(
    (evidence?.candidate.runs ?? []).map((run) => [
      run.scenario_id,
      run.scenario_name,
    ]),
  );
  const model = evidence?.candidate.runs?.[0]?.model;

  return (
    <section className="release-comparison" aria-label="Release comparison">
      <div className="section-top">
        <div>
          <h2>
            <GitCompareArrows size={17} /> Release comparison
          </h2>
          <p>
            Check this candidate against a previous evaluation, including
            regressions hidden by aggregate gains.
          </p>
        </div>
        <button
          className="button small"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {expanded ? "Hide comparison" : "Compare with reference"}
        </button>
      </div>
      {expanded && (
        <div className="release-comparison-body">
          <div className="comparison-selection">
            <label>
              Reference experiment
              <select
                aria-label="Reference experiment"
                value={referenceId}
                onChange={(event) => {
                  invalidate();
                  setReferenceId(event.target.value);
                }}
              >
                <option value="">Choose a completed experiment</option>
                {references.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.id.slice(0, 8)} ·{" "}
                    {item.provider === "scripted" ? "scripted" : "live"}
                  </option>
                ))}
              </select>
            </label>
            <div className="candidate-label">
              <span>Candidate</span>
              <b>{candidate.name}</b>
              <small className="mono">
                {candidate.id.slice(0, 8)} · {candidate.status}
              </small>
            </div>
            <button
              className="button primary"
              disabled={
                !referenceId || pending || candidate.status !== "completed"
              }
              onClick={() => void compare()}
            >
              {pending ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <GitCompareArrows size={14} />
              )}
              {pending ? "Checking evidence…" : "Compare releases"}
            </button>
          </div>
          {candidate.status !== "completed" && (
            <p className="comparison-guidance" role="status">
              This candidate is {candidate.status}. Comparison requires a
              completed experiment with full paired coverage. Inspect partial
              results above or run a complete evaluation.
            </p>
          )}
          {!references.length && (
            <p className="comparison-guidance">
              Run another experiment on the same suite and model settings to
              create a reference. Comparisons only read saved evidence; they do
              not run models.
            </p>
          )}
          {error && (
            <div className="comparison-error" role="alert">
              <ShieldX size={17} />
              <div>
                <b>These experiments cannot be compared</b>
                <p>{error}</p>
                <small>
                  Choose a completed reference with the same suite and model
                  settings, before human approval decisions. No release decision
                  has been produced.
                </small>
              </div>
            </div>
          )}
          {report && evidence && (
            <>
              <div
                className={`release-decision ${report.gate.passed ? "pass" : "fail"}`}
                role="status"
              >
                {report.gate.passed ? (
                  <ShieldCheck size={23} />
                ) : (
                  <ShieldX size={23} />
                )}
                <div>
                  <span>RELEASE COMPARISON GATE</span>
                  <h3>
                    {report.gate.passed
                      ? "Comparison checks passed"
                      : "Release comparison failed"}
                  </h3>
                  <p>
                    {report.gate.reasons.length
                      ? report.gate.reasons.join(". ")
                      : "No guarded case regressed; candidate outcomes meet this comparison's thresholds."}
                  </p>
                </div>
                <button className="button small" onClick={download}>
                  <ArrowDownToLine size={14} /> Export comparison
                </button>
              </div>
              <div className="comparison-context">
                <span>
                  {candidate.provider === "scripted"
                    ? "Scripted fixtures · not LLM accuracy"
                    : "Live model evaluation"}
                </span>
                <span>{model}</span>
                <span>{report.distinct_cases} cases</span>
                <span>
                  Prompt {report.prompt_changed ? "changed" : "unchanged"}
                </span>
                <span>
                  Source {report.source_changed ? "changed" : "unchanged"}
                </span>
              </div>
              <p className="comparison-explanation comparison-snapshot">
                Snapshot captured{" "}
                <time dateTime={report.captured_at}>
                  {new Date(report.captured_at).toLocaleString()}
                </time>
                . The gate, metrics and evidence below use this same saved
                snapshot. Later approvals do not rewrite this review; compare
                again to check the current saved state.
              </p>
              <p className="comparison-explanation">
                This gate compares versions and rejects any guarded case
                regression. The experiment gate above compares the candidate's
                own two strategies. Token and latency changes are descriptive,
                with no automatic budget gate.
              </p>
              <div className="comparison-metrics-grid">
                {(["baseline", "guarded"] as const).map((strategy) => {
                  const { before, after } = report.variants[strategy];
                  return (
                    <section
                      key={strategy}
                      className="comparison-metrics"
                      aria-label={`${strategy} release metrics`}
                    >
                      <h3>{strategy === "guarded" ? "Guarded" : "Baseline"}</h3>
                      <table>
                        <thead>
                          <tr>
                            <th>Measure</th>
                            <th>Reference</th>
                            <th>Candidate</th>
                            <th>Change</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <th>Correct outcomes</th>
                            <td>
                              {before.correct}/{before.trials}
                            </td>
                            <td>
                              {after.correct}/{after.trials}
                            </td>
                            <td>{delta(after.correct - before.correct)}</td>
                          </tr>
                          <tr>
                            <th>Effect invariants</th>
                            <td>
                              {before.safe}/{before.trials}
                            </td>
                            <td>
                              {after.safe}/{after.trials}
                            </td>
                            <td>{delta(after.safe - before.safe)}</td>
                          </tr>
                          <tr>
                            <th>Reported tokens</th>
                            <td>{before.tokens.toLocaleString()}</td>
                            <td>{after.tokens.toLocaleString()}</td>
                            <td>{delta(after.tokens - before.tokens)}</td>
                          </tr>
                          <tr>
                            <th>p95 latency · ms</th>
                            <td>{before.p95_ms.toFixed(1)}</td>
                            <td>{after.p95_ms.toFixed(1)}</td>
                            <td>{delta(after.p95_ms - before.p95_ms, 1)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>
                  );
                })}
              </div>
              <div className="comparison-case-toolbar">
                <h3>Changes by case</h3>
                <label>
                  Strategy
                  <select
                    aria-label="Comparison strategy"
                    value={variant}
                    onChange={(event) => {
                      setVariant(event.target.value as "baseline" | "guarded");
                      setSelectedCase(null);
                    }}
                  >
                    <option value="guarded">Guarded</option>
                    <option value="baseline">Baseline</option>
                  </select>
                </label>
                <label>
                  Show
                  <select
                    aria-label="Case change filter"
                    value={filter}
                    onChange={(event) => {
                      setFilter(event.target.value);
                      setSelectedCase(null);
                    }}
                  >
                    <option value="regressed">
                      Regressions ({allRows.filter(regressed).length})
                    </option>
                    <option value="improved">
                      Improvements ({allRows.filter(improved).length})
                    </option>
                    <option value="changed">All changed cases</option>
                    <option value="all">All cases</option>
                  </select>
                </label>
              </div>
              <div className="comparison-case-list">
                {rows.map((row) => (
                  <button
                    key={`${row.scenario_id}-${row.variant}`}
                    className={`comparison-case ${regressed(row) ? "regression" : improved(row) ? "improvement" : "unchanged"}`}
                    aria-label={`Inspect ${names.get(row.scenario_id) ?? row.scenario_id} ${row.variant} comparison`}
                    aria-pressed={
                      selectedCase?.scenario_id === row.scenario_id &&
                      selectedCase.variant === row.variant
                    }
                    onClick={() => setSelectedCase(row)}
                  >
                    <span>
                      <b>{names.get(row.scenario_id) ?? row.scenario_id}</b>
                      <small className="mono">{row.scenario_id}</small>
                    </span>
                    <span>
                      {row.before_correct}/{row.trials_each} →{" "}
                      {row.after_correct}/{row.trials_each}
                      <small>correct outcomes</small>
                    </span>
                    <span>
                      {delta(row.safe_delta)}
                      <small>invariant passes</small>
                    </span>
                    <ChevronRight size={15} />
                  </button>
                ))}
                {!rows.length && (
                  <p className="comparison-guidance">
                    No cases match this filter. Choose another filter to inspect
                    all stored outcomes.
                  </p>
                )}
              </div>
              {selectedCase && (
                <section
                  className="comparison-evidence"
                  aria-label="Compared case evidence"
                >
                  <div className="comparison-evidence-heading">
                    <div>
                      <h3>
                        {names.get(selectedCase.scenario_id) ??
                          selectedCase.scenario_id}
                      </h3>
                      <p>
                        Choose trials independently. Repeat numbers across
                        releases are not matched random samples. These panes are
                        read-only.
                      </p>
                    </div>
                    <button
                      className="icon-button"
                      aria-label="Close compared evidence"
                      onClick={() => setSelectedCase(null)}
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <div className="comparison-evidence-grid">
                    <EvidencePane
                      key={`reference-${selectedCase.scenario_id}-${selectedCase.variant}`}
                      experiment={evidence.reference}
                      row={selectedCase}
                      role="Reference"
                    />
                    <EvidencePane
                      key={`candidate-${selectedCase.scenario_id}-${selectedCase.variant}`}
                      experiment={evidence.candidate}
                      row={selectedCase}
                      role="Candidate"
                    />
                  </div>
                </section>
              )}
              <details className="comparison-method">
                <summary>Compatibility checks and interpretation</summary>
                <p>
                  Suite: <span className="mono">{report.suite_hash}</span>
                </p>
                <p>
                  Matched settings:{" "}
                  {report.compared_settings.map(words).join(", ")}. Candidate
                  minimum task rate: {Math.round(report.minimum_rate * 100)}%.
                </p>
                <ul>
                  {report.limitations.map((limit) => (
                    <li key={limit}>{limit}</li>
                  ))}
                </ul>
              </details>
            </>
          )}
        </div>
      )}
    </section>
  );
}
