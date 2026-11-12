import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Database,
  FileCode2,
  FlaskConical,
  History,
  Layers3,
  RefreshCw,
  Search,
  XCircle,
  Zap,
} from "lucide-react";
import type {
  AnswerConfig,
  AnswerReportEntry,
  AnswerResult,
  CacheReportEntry,
} from "./answerTypes";
import {
  answerFetch,
  ANSWER_RECORDED_ONLY,
  date,
  duration,
  number,
  STRATEGIES,
  STRATEGY_LABELS,
} from "./answerUtils";
import { ResultInspector, Status } from "./AnswerLabResult";
import Workspace from "./AnswerLabWorkspace";
import Experiments from "./AnswerLabReports";
import CachePerformance from "./AnswerLabCache";
import "./AnswerLab.css";

type View = "workspace" | "experiments" | "cache" | "history" | "method";

function RunHistory({
  runs,
  onSelect,
  onRefresh,
}: {
  runs: AnswerResult[];
  onSelect: (result: AnswerResult) => void;
  onRefresh: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AnswerResult | null>(null);
  const [error, setError] = useState("");
  const shown = runs.filter((run) =>
    (run.question + run.model + run.strategy)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  async function inspect(run: AnswerResult) {
    setError("");
    try {
      setSelected(
        await answerFetch<AnswerResult>(`/runs/${encodeURIComponent(run.id)}`),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load this run.");
    }
  }
  return (
    <>
      <div className="al-page-heading">
        <div>
          <div className="al-eyebrow">LOCAL RECORDS</div>
          <h1>Run history</h1>
          <p>Every answer, including failed checks and abstentions.</p>
        </div>
        <button className="al-button al-secondary" onClick={onRefresh}>
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      <div className="al-history-toolbar">
        <label className="al-search">
          <Search size={15} />
          <input
            aria-label="Search run history"
            placeholder="Search questions, models, or strategies…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <span>{shown.length} runs</span>
      </div>
      {error && (
        <div role="alert" className="al-error">
          {error}
        </div>
      )}
      {runs.length ? (
        <div className="al-history-layout">
          <div className="al-history-list">
            {shown.map((run) => (
              <button
                className={selected?.id === run.id ? "selected" : ""}
                key={run.id}
                onClick={() => inspect(run)}
              >
                <div>
                  <Status result={run} />
                  <time>{date(run.created_at)}</time>
                </div>
                <h3>{run.question}</h3>
                <footer>
                  <span>{STRATEGY_LABELS[run.strategy]}</span>
                  <span>
                    {duration(run.latency_ms)} · {number(run.usage.calls)} calls
                  </span>
                  <ChevronRight size={15} />
                </footer>
              </button>
            ))}
            {!shown.length && (
              <div className="al-no-rows">No runs match your search.</div>
            )}
          </div>
          <div className="al-history-inspector">
            {selected ? (
              <>
                <button
                  className="al-button al-secondary al-reopen"
                  onClick={() => onSelect(selected)}
                >
                  <ArrowUpRight size={15} />
                  Open in workspace
                </button>
                <ResultInspector result={selected} />
              </>
            ) : (
              <div className="al-empty-selection">
                <History size={26} />
                <p>Select a run to inspect its answer and trace.</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="al-empty-page">
          <History size={35} strokeWidth={1.1} />
          <h2>Your first run starts the record</h2>
          <p>
            Generate an answer in the workspace. Its sources, checks, token
            usage, and correction trace will be saved here.
          </p>
        </div>
      )}
    </>
  );
}

function Method() {
  return (
    <>
      <div className="al-page-heading">
        <div>
          <div className="al-eyebrow">READ THE RESULTS</div>
          <h1>What we measure</h1>
          <p>Separate answer correctness from runtime validation.</p>
        </div>
      </div>
      <div className="al-method-grid">
        <section>
          <h2>One input. Three strategies.</h2>
          <ol className="al-method-steps">
            {STRATEGIES.map((s) => (
              <li key={s}>
                <span className={`al-strategy-dot ${s}`} />
                <div>
                  <h3>{STRATEGY_LABELS[s]}</h3>
                  <p>
                    {s === "baseline"
                      ? "Generate once with the same task prompt. This is the reference for measuring improvement."
                      : s === "validated"
                        ? "Check the response structure and cited evidence. Return failed checks to the model and retry within a fixed budget."
                        : "Add a separately prompted critic to check whether the answer addresses the question and is supported by the sources. Refine only when checks fail."}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <h2>Correctness has a reference</h2>
          <dl>
            <dt>Task success</dt>
            <dd>
              Correct final answers divided by evaluated cases. QA uses exact
              match; extraction checks fields against the reference.
            </dd>
            <dt>Token F1</dt>
            <dd>
              Token overlap with reference answers, balancing precision and
              recall. Useful when an answer is partially correct.
            </dd>
            <dt>Error recovery</dt>
            <dd>
              Initially incorrect cases that finish correct, divided by
              initially incorrect cases.
            </dd>
            <dt>Regression rate</dt>
            <dd>
              Initially correct cases made incorrect by the strategy, divided by
              initially correct cases.
            </dd>
          </dl>
        </section>
        <section>
          <h2>Efficiency includes the full workflow</h2>
          <dl>
            <dt>Calls and tokens</dt>
            <dd>
              Generation, critic, and correction calls all count. Missing
              provider usage is shown as unknown.
            </dd>
            <dt>Latency</dt>
            <dd>
              End-to-end elapsed time, reported as the median (p50) and
              slower-end p95.
            </dd>
            <dt>Tokens per correct answer</dt>
            <dd>
              Total tokens spent divided by successful cases. Failed attempts
              still contribute to cost.
            </dd>
            <dt>Cache speedup</dt>
            <dd>
              Warm repeats are a separate study. Cache hits do not count as
              improved reasoning.
            </dd>
          </dl>
        </section>
        <section className="al-method-caution">
          <h2>A check can pass on a wrong answer</h2>
          <p>
            The runtime validation score describes checks that passed. It is not
            calibrated confidence or a probability that the answer is true.
          </p>
          <p>
            Reference grading measures false acceptance explicitly. Inspect
            individual cases and confidence intervals before treating a change
            as an improvement.
          </p>
          <div className="al-method-links">
            <a
              href="https://rajpurkar.github.io/SQuAD-explorer/"
              target="_blank"
              rel="noreferrer"
            >
              SQuAD benchmark <ArrowUpRight size={13} />
            </a>
            <a
              href="https://github.com/HXRIkumar/AgentProof"
              target="_blank"
              rel="noreferrer"
            >
              Source & methodology <ArrowUpRight size={13} />
            </a>
          </div>
        </section>
      </div>
    </>
  );
}

export default function AnswerLab() {
  const [view, setView] = useState<View>(
    ANSWER_RECORDED_ONLY ? "experiments" : "workspace",
  );
  const [config, setConfig] = useState<AnswerConfig | null>(null);
  const [runs, setRuns] = useState<AnswerResult[]>([]);
  const [reports, setReports] = useState<AnswerReportEntry[]>([]);
  const [cacheReports, setCacheReports] = useState<CacheReportEntry[]>([]);
  const [selected, setSelected] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  async function refresh() {
    setLoading(true);
    setConnectionError("");
    const values = await Promise.allSettled([
      answerFetch<AnswerConfig>("/config"),
      answerFetch<AnswerResult[]>("/runs"),
      answerFetch<AnswerReportEntry[]>("/reports"),
      answerFetch<CacheReportEntry[]>("/cache-reports"),
    ]);
    if (values[0].status === "fulfilled") setConfig(values[0].value);
    else
      setConnectionError(
        "Answer Lab could not reach the server. Start the application, then retry.",
      );
    if (values[1].status === "fulfilled") setRuns(values[1].value);
    if (values[2].status === "fulfilled") setReports(values[2].value);
    else if (ANSWER_RECORDED_ONLY)
      setConnectionError(
        "Recorded experiments could not be loaded. Check your connection, then retry.",
      );
    if (values[3].status === "fulfilled" && Array.isArray(values[3].value))
      setCacheReports(values[3].value);
    setLoading(false);
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    document.title = "Answer Lab · AgentProof";
  }, []);
  const nav: {
    id: View;
    label: string;
    icon: typeof Layers3;
    count?: number;
  }[] = [
    { id: "workspace", label: "Workspace", icon: Layers3 },
    {
      id: "experiments",
      label: "Experiments",
      icon: FlaskConical,
      count: reports.length,
    },
    { id: "cache", label: "Cache performance", icon: Database },
    { id: "history", label: "Run history", icon: History, count: runs.length },
    { id: "method", label: "Measurements", icon: BookOpen },
  ];
  return (
    <div className="answer-lab">
      <a className="al-skip" href="#answer-main">
        Skip to workspace
      </a>
      <aside className="al-sidebar">
        <a
          className="al-brand"
          href={import.meta.env.BASE_URL}
          aria-label="AgentProof Answer Lab"
        >
          <span className="al-brand-symbol">
            <span />
            <span />
            <span />
          </span>
          <span>
            AgentProof<small>ANSWER LAB</small>
          </span>
        </a>
        <div className="al-project">
          <span className="al-project-avatar">A</span>
          <span>
            Answer reliability
            <small>
              {ANSWER_RECORDED_ONLY
                ? "Recorded experiments"
                : "Local workspace"}
            </small>
          </span>
          <ChevronDown size={14} />
        </div>
        <nav aria-label="Answer Lab navigation">
          {nav.map((item) => (
            <button
              key={item.id}
              className={view === item.id ? "active" : ""}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <item.icon size={17} />
              <span>{item.label}</span>
              {item.count ? <small>{item.count}</small> : null}
            </button>
          ))}
        </nav>
        <div className="al-sidebar-bottom">
          <a href={`${import.meta.env.BASE_URL}?workspace=legacy`}>
            <Layers3 size={16} />
            <span>Tool-action lab</span>
            <ArrowUpRight size={13} />
          </a>
          <a
            href="https://github.com/HXRIkumar/AgentProof"
            target="_blank"
            rel="noreferrer"
          >
            <FileCode2 size={16} />
            <span>Source code</span>
            <ArrowUpRight size={13} />
          </a>
          <div className="al-sidebar-note">
            <Database size={15} />
            <div>
              <b>
                {ANSWER_RECORDED_ONLY
                  ? "Read-only evidence"
                  : "Stored on this machine"}
              </b>
              <p>
                {ANSWER_RECORDED_ONLY
                  ? "Actual local-model runs. No inference in this viewer."
                  : "Sources, runs, and cache use local storage."}
              </p>
            </div>
          </div>
        </div>
      </aside>
      <div className="al-main-shell">
        <header className="al-topbar">
          <div>
            <span>Answer reliability</span>
            <ChevronRight size={13} />
            <b>{nav.find((n) => n.id === view)?.label}</b>
          </div>
          <div className="al-server-state">
            <span
              className={`al-dot ${!config?.configured && !ANSWER_RECORDED_ONLY ? "warn" : ""}`}
            />
            {ANSWER_RECORDED_ONLY
              ? "Recorded local-model experiments"
              : loading
                ? "Connecting"
                : config?.configured
                  ? "Model connected"
                  : "Model offline"}
            <button
              className="al-icon-button"
              title="Refresh connection"
              aria-label="Refresh connection"
              onClick={refresh}
            >
              <RefreshCw size={14} className={loading ? "al-spin" : ""} />
            </button>
          </div>
        </header>
        <main
          id="answer-main"
          className={`al-main ${view === "experiments" ? "al-main-wide" : ""}`}
        >
          {connectionError && (
            <div className="al-error" role="alert">
              <XCircle size={17} />
              <span>{connectionError}</span>
              <button onClick={refresh}>Retry</button>
            </div>
          )}
          {view === "workspace" && (
            <Workspace
              config={config}
              initial={selected}
              onOpenReports={() => setView("experiments")}
              onRun={(run) => {
                setRuns((old) => [run, ...old.filter((r) => r.id !== run.id)]);
                setSelected(run);
              }}
            />
          )}
          {view === "experiments" && (
            <Experiments
              entries={reports}
              loading={loading}
              onRefresh={refresh}
            />
          )}
          {view === "cache" && (
            <CachePerformance entries={cacheReports} onRefresh={refresh} />
          )}
          {view === "history" && (
            <RunHistory
              runs={runs}
              onRefresh={refresh}
              onSelect={(run) => {
                setSelected(run);
                setView("workspace");
              }}
            />
          )}
          {view === "method" && <Method />}
        </main>
        <footer className="al-app-footer">
          <span>AgentProof / Answer Lab</span>
          <span>
            <Zap size={12} /> Measured changes. Inspectable answers.
          </span>
        </footer>
      </div>
    </div>
  );
}
