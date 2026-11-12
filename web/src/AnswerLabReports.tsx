import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  Check,
  FlaskConical,
  LoaderCircle,
  RefreshCw,
  Search,
  Terminal,
  X,
} from "lucide-react";
import type {
  AnswerReport,
  AnswerReportEntry,
  AnswerStrategy,
  AnswerProviderMetadata,
  StrategyMetrics,
} from "./answerTypes";
import {
  answerFetch,
  caseChange,
  date,
  downloadJson,
  duration,
  groupCases,
  human,
  number,
  percent,
  STRATEGIES,
  STRATEGY_LABELS,
  usd,
} from "./answerUtils";
import type { CaseRow } from "./answerUtils";
import { ResultInspector } from "./AnswerLabResult";
import { ModelMetadata, StudyAccounting } from "./AnswerLabAccounting";

function MetricCell({ value, hint }: { value: string; hint?: string }) {
  return (
    <div className="al-metric-cell">
      <b>{value}</b>
      {hint && <small>{hint}</small>}
    </div>
  );
}
function QualityChart({
  metrics,
}: {
  metrics: AnswerReport["summary"]["strategies"];
}) {
  return (
    <div className="al-quality-chart">
      <div className="al-chart-header">
        <h3>Quality / latency</h3>
        <span>Measured success · median end-to-end time</span>
      </div>
      {STRATEGIES.map((strategy) => {
        const m = metrics[strategy];
        return m ? (
          <div className={`al-chart-row al-chart-${strategy}`} key={strategy}>
            <span>{STRATEGY_LABELS[strategy]}</span>
            <div className="al-chart-track">
              <span
                style={{
                  width: `${Math.max(0, Math.min(1, m.success_rate ?? 0)) * 100}%`,
                }}
              />
            </div>
            <b>{percent(m.success_rate)}</b>
            <small>{duration(m.latency_p50_ms)}</small>
          </div>
        ) : null;
      })}
      <div className="al-chart-axis">
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  );
}
function CaseDetail({
  row,
  onClose,
  provider,
}: {
  row: CaseRow;
  onClose: () => void;
  provider?: AnswerProviderMetadata;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  const [strategy, setStrategy] = useState<AnswerStrategy>(
    row.trials.adaptive ? "adaptive" : "baseline",
  );
  const trial = row.trials[strategy];
  return (
    <aside className="al-case-detail" aria-label="Case detail">
      <div className="al-case-detail-heading">
        <div>
          <span className="al-overline">CASE DETAIL</span>
          <h3>{row.question}</h3>
          <code>{row.id}</code>
        </div>
        <button
          className="al-icon-button"
          aria-label="Close case detail"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div className="al-case-strategies">
        {STRATEGIES.map((s) => (
          <button
            className={strategy === s ? "active" : ""}
            key={s}
            onClick={() => setStrategy(s)}
            disabled={!row.trials[s]}
          >
            {STRATEGY_LABELS[s]}
            {row.trials[s] &&
              (row.trials[s]!.grade.correct ? (
                <Check size={13} />
              ) : (
                <X size={13} />
              ))}
          </button>
        ))}
      </div>
      {trial && (
        <>
          <div
            className={`al-reference-grade ${trial.grade.correct ? "pass" : "fail"}`}
          >
            <b>
              {trial.grade.correct
                ? "Task passed reference grading"
                : "Task did not pass reference grading"}
            </b>
            <span>
              {trial.task === "qa"
                ? `Exact match ${percent(trial.grade.exact_match)} · token F1 ${percent(trial.grade.token_f1)}`
                : `Field accuracy ${percent(trial.grade.field_accuracy)}`}
            </span>
          </div>
          {(trial.reference_answers || trial.case?.gold?.answers)?.length ? (
            <div className="al-reference-answers">
              <b>Reference answers</b>
              <p>
                {(
                  trial.reference_answers ||
                  trial.case?.gold?.answers ||
                  []
                ).join(" / ")}
              </p>
            </div>
          ) : trial.case?.gold?.data != null ? (
            <details className="al-reference-answers">
              <summary>Reference fields</summary>
              <pre className="al-json">
                {JSON.stringify(trial.case.gold.data, null, 2)}
              </pre>
            </details>
          ) : null}
          <ResultInspector result={trial.result} provider={provider} compact />
        </>
      )}
    </aside>
  );
}

export default function Experiments({
  entries,
  loading,
  onRefresh,
}: {
  entries: AnswerReportEntry[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [report, setReport] = useState<AnswerReport | null>(null);
  const [error, setError] = useState("");
  const [fetching, setFetching] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedCase, setSelectedCase] = useState<CaseRow | null>(null);
  useEffect(() => {
    if (!selectedId && entries.length) setSelectedId(entries[0].id);
  }, [entries, selectedId]);
  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    setFetching(true);
    setError("");
    setSelectedCase(null);
    answerFetch<AnswerReport>(`/reports/${encodeURIComponent(selectedId)}`)
      .then((value) => {
        if (active) setReport(value);
      })
      .catch((cause) => {
        if (active) {
          setReport(null);
          setError(String(cause.message));
        }
      })
      .finally(() => {
        if (active) setFetching(false);
      });
    return () => {
      active = false;
    };
  }, [selectedId]);
  const rows = useMemo(
    () =>
      report
        ? groupCases(report).filter(
            (row) =>
              (row.question + row.id + row.category)
                .toLowerCase()
                .includes(query.toLowerCase()) &&
              (filter === "all" ||
                caseChange(row) === filter ||
                (filter === "failed" &&
                  row.trials.adaptive?.grade.correct === false)),
          )
        : [],
    [report, query, filter],
  );
  const metrics = report?.summary.strategies;
  const metricRows: {
    label: string;
    render: (m: StrategyMetrics) => [string, string?];
  }[] = [
    {
      label: "Task success",
      render: (m) => [
        percent(m.success_rate),
        `${m.correct} / ${m.trials} cases`,
      ],
    },
    { label: "Exact match · QA", render: (m) => [percent(m.exact_match)] },
    { label: "Token F1 · QA", render: (m) => [percent(m.token_f1)] },
    {
      label: "Field accuracy · extraction",
      render: (m) => [percent(m.field_accuracy)],
    },
    {
      label: "Error recovery",
      render: (m) => [
        percent(m.recovery_rate),
        `${m.recovered} / ${m.initial_failures} initial failures`,
      ],
    },
    {
      label: "Regressions",
      render: (m) => [
        percent(m.regression_rate),
        `${m.regressed} / ${m.initial_successes} initial successes`,
      ],
    },
    {
      label: "False acceptance",
      render: (m) => [
        percent(m.false_accept_rate),
        `${m.accepted_incorrect} / ${m.accepted} accepted`,
      ],
    },
    {
      label: "Retries / query",
      render: (m) => [number(m.retries_per_query, 2)],
    },
    { label: "Calls / query", render: (m) => [number(m.calls_per_query, 2)] },
    {
      label: "Tokens / correct answer",
      render: (m) => [number(m.tokens_per_correct, 1)],
    },
    {
      label: "Estimated API cost · policy",
      render: (m) => [usd(m.cost_known ? m.estimated_cost_usd : null)],
    },
    {
      label: "Estimated API cost / correct",
      render: (m) => [usd(m.cost_known ? m.cost_per_correct_usd : null)],
    },
    {
      label: "Latency · p50 / p95",
      render: (m) => [
        duration(m.latency_p50_ms),
        `p95 ${duration(m.latency_p95_ms)}`,
      ],
    },
  ];
  return (
    <>
      <div className="al-page-heading">
        <div>
          <div className="al-eyebrow">MEASURED EVIDENCE</div>
          <h1>Experiments</h1>
          <p>Compare quality gains with their inference cost.</p>
        </div>
        <button
          className="al-button al-secondary"
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw size={15} className={loading ? "al-spin" : ""} />
          Refresh
        </button>
      </div>
      {!entries.length && !loading ? (
        <div className="al-empty-page">
          <FlaskConical size={35} strokeWidth={1.1} />
          <h2>No benchmark reports yet</h2>
          <p>
            Completed benchmark reports appear here with per-case results,
            recovery rates, and measured inference cost.
          </p>
          <div className="al-command">
            <Terminal size={15} />
            <code>python scripts/answer_benchmark.py --help</code>
          </div>
          <small>Workspace runs remain available in Run history.</small>
        </div>
      ) : (
        <>
          <div className="al-report-toolbar">
            <label>
              Experiment
              <select
                aria-label="Experiment report"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                {entries.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.title || entry.id}
                  </option>
                ))}
              </select>
            </label>
            {report && (
              <button
                className="al-button al-secondary"
                onClick={() => downloadJson(report, `${report.id}.json`)}
              >
                <ArrowDownToLine size={15} />
                Export JSON
              </button>
            )}
          </div>
          {error && (
            <div className="al-error" role="alert">
              {error}
            </div>
          )}
          {fetching && (
            <div className="al-loading">
              <LoaderCircle className="al-spin" size={17} />
              Loading recorded experiment…
            </div>
          )}
          {report && !fetching && metrics && (
            <>
              <div className="al-report-meta">
                <span>
                  <span
                    className={`al-dot ${report.summary.complete ? "" : "warn"}`}
                  />
                  {report.summary.complete ? "Complete" : "Partial results"}
                </span>
                <span>
                  {report.summary.finished_trials}/
                  {report.summary.planned_trials} trials
                </span>
                <span>{report.suite.case_count} cases</span>
                <span>{date(report.created_at)}</span>
              </div>
              <ModelMetadata
                provider={report.configuration.runtime?.provider}
                model={report.model}
                runtime={report.configuration.runtime}
              />
              <QualityChart metrics={metrics} />
              <div className="al-metrics-table-wrap">
                <table className="al-metrics-table">
                  <thead>
                    <tr>
                      <th scope="col">Measurement</th>
                      {STRATEGIES.map((s) => (
                        <th key={s} scope="col">
                          <span className={`al-strategy-dot ${s}`} />
                          {STRATEGY_LABELS[s]}
                          <small>
                            {s === "baseline"
                              ? "Single generation"
                              : s === "validated"
                                ? "Validation feedback"
                                : "Validation + critic"}
                          </small>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {metricRows.map((row) => (
                      <tr key={row.label}>
                        <th scope="row">{row.label}</th>
                        {STRATEGIES.map((s) => {
                          const m = metrics[s];
                          const v = m ? row.render(m) : ["—"];
                          return (
                            <td key={s}>
                              <MetricCell value={v[0] ?? "—"} hint={v[1]} />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <StudyAccounting report={report} />
              {report.summary.comparisons.length > 0 && (
                <div className="al-comparison-notes">
                  {report.summary.comparisons.map((c) => (
                    <div key={`${c.reference}-${c.candidate}`}>
                      <b>
                        {STRATEGY_LABELS[c.candidate]} vs.{" "}
                        {STRATEGY_LABELS[c.reference]}
                      </b>
                      <span>
                        Success delta{" "}
                        {c.success_delta == null
                          ? "—"
                          : `${c.success_delta >= 0 ? "+" : ""}${(c.success_delta * 100).toFixed(1)} pp`}
                        {c.success_delta_ci95
                          ? ` · 95% paired interval [${(c.success_delta_ci95[0] * 100).toFixed(1)}, ${(c.success_delta_ci95[1] * 100).toFixed(1)}] pp`
                          : ""}{" "}
                        · {c.paired_cases} paired cases
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <div className="al-cases-heading">
                <div>
                  <h2>Case comparison</h2>
                  <p>
                    Open a row to inspect the actual answer and correction
                    trace.
                  </p>
                </div>
                <div className="al-table-controls">
                  <label className="al-search">
                    <Search size={15} />
                    <input
                      aria-label="Search benchmark cases"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search cases…"
                    />
                  </label>
                  <select
                    aria-label="Filter case outcomes"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">All outcomes</option>
                    <option value="recovered">Recovered</option>
                    <option value="regressed">Regressed</option>
                    <option value="failed">Still incorrect</option>
                    <option value="unchanged">Unchanged</option>
                  </select>
                </div>
              </div>
              <div className="al-cases-table-wrap">
                <table className="al-cases-table">
                  <thead>
                    <tr>
                      <th scope="col">Question / instruction</th>
                      {STRATEGIES.map((s) => (
                        <th scope="col" key={s}>
                          {STRATEGY_LABELS[s]}
                        </th>
                      ))}
                      <th scope="col">Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr
                        key={row.id}
                        className={
                          selectedCase?.id === row.id ? "selected" : ""
                        }
                      >
                        <th scope="row">
                          <button onClick={() => setSelectedCase(row)}>
                            <span>{row.question}</span>
                            <small>
                              {human(row.category)} · {row.id}
                            </small>
                          </button>
                        </th>
                        {STRATEGIES.map((s) => (
                          <td key={s}>
                            {row.trials[s] ? (
                              <span
                                className={`al-outcome ${row.trials[s]!.grade.correct ? "pass" : "fail"}`}
                              >
                                {row.trials[s]!.grade.correct ? (
                                  <Check size={13} />
                                ) : (
                                  <X size={13} />
                                )}
                                {row.trials[s]!.grade.correct ? "Pass" : "Fail"}
                              </span>
                            ) : (
                              <span className="al-muted">Missing</span>
                            )}
                          </td>
                        ))}
                        <td>
                          <span className={`al-change ${caseChange(row)}`}>
                            {human(caseChange(row))}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && (
                  <div className="al-no-rows">No cases match this filter.</div>
                )}
              </div>
              <div className="al-evaluation-footnote">
                <span>{rows.length} visible cases</span>
                <span title={report.suite.sha256}>
                  Suite {report.suite.sha256.slice(0, 12)} ·{" "}
                  {report.suite.split}
                </span>
              </div>
              {selectedCase && (
                <CaseDetail
                  provider={report.configuration.runtime?.provider}
                  key={selectedCase.id}
                  row={selectedCase}
                  onClose={() => setSelectedCase(null)}
                />
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
