import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  Database,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import type {
  AnswerResult,
  CacheReport,
  CacheReportEntry,
} from "./answerTypes";
import {
  answerFetch,
  date,
  downloadJson,
  duration,
  human,
  number,
  percent,
} from "./answerUtils";
import { ResultInspector } from "./AnswerLabResult";
import { ModelMetadata } from "./AnswerLabAccounting";

export default function CachePerformance({
  entries,
  onRefresh,
}: {
  entries: CacheReportEntry[];
  onRefresh: () => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [report, setReport] = useState<CacheReport | null>(null);
  const [selectedResult, setSelectedResult] = useState<AnswerResult | null>(
    null,
  );
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedResult(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);
  useEffect(() => {
    if (!selectedId && entries.length) setSelectedId(entries[0].id);
  }, [entries, selectedId]);
  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    setLoading(true);
    setError("");
    setSelectedResult(null);
    answerFetch<CacheReport>(`/cache-reports/${encodeURIComponent(selectedId)}`)
      .then((data) => {
        if (active) setReport(data);
      })
      .catch((cause) => {
        if (active) {
          setError(String(cause.message));
          setReport(null);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedId]);
  const summary = report?.summary;
  const semanticRows =
    report?.groups.flatMap((group) =>
      group.queries.map((query) => ({ ...query, group: group.id })),
    ) || [];
  return (
    <>
      <div className="al-page-heading">
        <div>
          <div className="al-eyebrow">MEASURED REUSE</div>
          <h1>Cache performance</h1>
          <p>How much repeated answers save—and when reuse fails.</p>
        </div>
        <button className="al-button al-secondary" onClick={onRefresh}>
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      {!entries.length ? (
        <div className="al-empty-page">
          <Database size={35} strokeWidth={1.1} />
          <h2>No cache study yet</h2>
          <p>
            Exact replay and semantic near-miss studies are measured separately
            from answer-quality experiments.
          </p>
          <small>Cache misses and incorrect hits remain in the report.</small>
        </div>
      ) : (
        <>
          <div className="al-report-toolbar">
            <label>
              Cache study
              <select
                aria-label="Cache study report"
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
                onClick={() => downloadJson(report, `${selectedId}.json`)}
              >
                <ArrowDownToLine size={15} />
                Export JSON
              </button>
            )}
          </div>
          {error && (
            <div role="alert" className="al-error">
              {error}
            </div>
          )}
          {loading && (
            <div className="al-loading">
              <LoaderCircle size={17} className="al-spin" />
              Loading measured cache study…
            </div>
          )}
          {report && summary && !loading && (
            <>
              <div className="al-report-meta">
                <span>
                  <span
                    className={`al-dot ${report.status !== "completed" ? "warn" : ""}`}
                  />
                  {human(report.status)}
                </span>
                <span>{summary.cold_requests} cold requests</span>
                <span>{summary.exact_replay_requests} exact repeats</span>
                <span>{summary.semantic_queries} semantic probes</span>
                <span>{date(report.created_at)}</span>
              </div>
              <ModelMetadata
                provider={report.configuration.provider}
                runtime={report.configuration}
              />
              <div className="al-cache-latency">
                <div className="al-cache-latency-heading">
                  <div>
                    <span className="al-overline">
                      EXACT REPLAY · MEDIAN LATENCY
                    </span>
                    <h2>Accepted answers, without another generation</h2>
                  </div>
                  <Database size={26} strokeWidth={1.3} />
                </div>
                <div className="al-latency-comparison">
                  <div>
                    <span>Cold request</span>
                    <b>{duration(summary.cold_p50_ms)}</b>
                    <small>Includes model generation & checks</small>
                  </div>
                  <ArrowRight size={23} />
                  <div>
                    <span>Warm exact replay</span>
                    <b>{duration(summary.warm_p50_ms)}</b>
                    <small>SQLite lookup & response delivery</small>
                  </div>
                  <div className="al-speedup">
                    <b>
                      {summary.p50_exact_replay_speedup == null
                        ? "—"
                        : `${number(summary.p50_exact_replay_speedup, 1)}×`}
                    </b>
                    <span>lower median latency</span>
                  </div>
                </div>
                <p>
                  Conditional on {number(summary.paired_cold_requests)} seed
                  requests whose repeats all hit the cache. This is
                  repeated-input speed, not faster reasoning on new questions.
                </p>
              </div>
              <div className="al-cache-outcomes">
                <div>
                  <span>Exact replay hit rate</span>
                  <b>{percent(summary.exact_hit_rate)}</b>
                  <small>
                    {summary.exact_hits} / {summary.exact_replay_requests}{" "}
                    repeated requests
                  </small>
                </div>
                <div>
                  <span>Correct cached answers</span>
                  <b>
                    {summary.exact_answer_matches} / {summary.exact_hits}
                  </b>
                  <small>Reference matches among exact hits</small>
                </div>
                <div>
                  <span>Semantic false-hit rate</span>
                  <b>{percent(summary.semantic_false_hit_rate)}</b>
                  <small>
                    {summary.semantic_false_hits} / {summary.semantic_hits}{" "}
                    semantic hits were incorrect
                  </small>
                </div>
                <div>
                  <span>Total study inference</span>
                  <b>{number(summary.actual_calls)} calls</b>
                  <small>
                    {summary.usage_known ? number(summary.tokens) : "Unknown"}{" "}
                    tokens · all attempts included
                  </small>
                </div>
              </div>
              <div className="al-cases-heading">
                <div>
                  <h2>Cold requests and exact repeats</h2>
                  <p>Each group keeps its original answer and every replay.</p>
                </div>
              </div>
              <div className="al-cases-table-wrap">
                <table className="al-cases-table al-cache-table">
                  <thead>
                    <tr>
                      <th>Seed question</th>
                      <th>Cold result</th>
                      <th>Cold latency</th>
                      <th>Exact hits</th>
                      <th>Repeat correctness</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.groups.map((group) => (
                      <tr key={group.id}>
                        <th scope="row">
                          <button
                            onClick={() => setSelectedResult(group.cold.result)}
                          >
                            <span>{group.cold.result.question}</span>
                            <small>{group.id}</small>
                          </button>
                        </th>
                        <td>
                          <span
                            className={`al-outcome ${group.cold.correct ? "pass" : "fail"}`}
                          >
                            {group.cold.correct ? (
                              <Check size={13} />
                            ) : (
                              <X size={13} />
                            )}
                            {group.cold.correct ? "Pass" : "Fail"}
                          </span>
                        </td>
                        <td className="al-mono-value">
                          {duration(group.cold.end_to_end_ms)}
                        </td>
                        <td className="al-mono-value">
                          {
                            group.replays.filter(
                              (replay) =>
                                replay.result.cache.status === "exact_hit",
                            ).length
                          }{" "}
                          / {group.replays.length}
                        </td>
                        <td className="al-mono-value">
                          {
                            group.replays.filter((replay) => replay.correct)
                              .length
                          }{" "}
                          / {group.replays.length}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="al-cases-heading">
                <div>
                  <h2>Semantic reuse stress test</h2>
                  <p>
                    {summary.semantic_hits} hits, {summary.rejected_candidates}{" "}
                    rejected candidates, {summary.semantic_total_correct}/
                    {summary.semantic_queries} correct final answers.
                  </p>
                </div>
              </div>
              <div className="al-cases-table-wrap">
                <table className="al-cases-table al-cache-table">
                  <thead>
                    <tr>
                      <th>Probe question</th>
                      <th>Cache decision</th>
                      <th>Reference grade</th>
                      <th>Latency</th>
                      <th>Model calls</th>
                    </tr>
                  </thead>
                  <tbody>
                    {semanticRows.map((query, i) => (
                      <tr key={`${query.group}-${i}`}>
                        <th scope="row">
                          <button
                            onClick={() => setSelectedResult(query.result)}
                          >
                            <span>{query.result.question}</span>
                            <small>
                              {human(query.kind)} ·{" "}
                              {query.reuse_expected
                                ? "reuse expected"
                                : "new answer required"}
                            </small>
                          </button>
                        </th>
                        <td>
                          <span className="al-cache-decision">
                            {human(query.result.cache.status)}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`al-outcome ${query.correct ? "pass" : "fail"}`}
                          >
                            {query.correct ? (
                              <Check size={13} />
                            ) : (
                              <X size={13} />
                            )}
                            {query.correct ? "Pass" : "Fail"}
                          </span>
                        </td>
                        <td className="al-mono-value">
                          {duration(query.end_to_end_ms)}
                        </td>
                        <td className="al-mono-value">
                          {number(query.result.usage.calls)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!semanticRows.length && (
                  <div className="al-no-rows">
                    No semantic probes were recorded.
                  </div>
                )}
              </div>
              <div className="al-evaluation-footnote">
                <span>{report.scope}</span>
                <span title={report.suite_sha256}>
                  Suite {report.suite_sha256.slice(0, 12)}
                </span>
              </div>
              {selectedResult && (
                <aside
                  className="al-case-detail"
                  aria-label="Cache result detail"
                >
                  <div className="al-case-detail-heading">
                    <div>
                      <span className="al-overline">CACHE STUDY RESULT</span>
                      <h3>{selectedResult.question}</h3>
                    </div>
                    <button
                      className="al-icon-button"
                      aria-label="Close cache result detail"
                      onClick={() => setSelectedResult(null)}
                    >
                      <X size={18} />
                    </button>
                  </div>
                  <ResultInspector
                    result={selectedResult}
                    provider={report.configuration.provider}
                    compact
                  />
                </aside>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
