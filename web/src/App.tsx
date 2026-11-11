import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  Activity,
  BookOpen,
  LockKeyhole,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  ShieldX,
  SlidersHorizontal,
  Terminal,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import { api } from "./api";
import ReleaseComparison from "./ReleaseComparison";
import {
  exampleScenarios,
  MAX_IMPORT_BYTES,
  parseScenarios,
} from "./scenarioImport";
import type {
  Config,
  CustomScenario,
  Experiment,
  ExperimentSource,
  EvidenceCatalogItem,
  EvidenceEnvelope,
  RecordedEvidence,
  Run,
  Scenario,
  VariantSummary,
} from "./types";

const percent = (value: number) => `${Math.round(value * 100)}%`;
const elapsed = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(1)} ms`;
const words = (value: string) =>
  value.replaceAll("_", " ").replaceAll("-", " ");
const date = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const isActive = (status: string) =>
  status === "queued" || status === "running";

function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span
      className={`badge provider ${provider === "scripted" ? "scripted" : "live"}`}
    >
      <Circle size={7} fill="currentColor" />
      {provider === "scripted" ? "Scripted fixture" : "Live model"}
    </span>
  );
}

function RunStatus({ run }: { run: Run }) {
  if (run.status === "awaiting_approval")
    return (
      <span className="status pending">
        <Clock3 size={12} />
        Approval
      </span>
    );
  return (
    <span className={`status ${run.passed ? "pass" : "fail"}`}>
      {run.passed ? <Check size={12} /> : <X size={12} />}
      {run.passed ? "Pass" : "Fail"}
    </span>
  );
}

function VariantResult({
  name,
  data,
  guarded,
}: {
  name: string;
  data: VariantSummary;
  guarded?: boolean;
}) {
  return (
    <div className={`variant-result ${guarded ? "guarded" : ""}`}>
      <div className="variant-heading">
        <span>
          {guarded ? <ShieldCheck size={16} /> : <GitCompareArrows size={16} />}
          {name}
        </span>
        <strong>
          {data.passed}
          <small> / {data.total} passed</small>
        </strong>
      </div>
      <div
        className="meter"
        aria-label={`${name} task pass rate ${percent(data.pass_rate)}`}
      >
        <span style={{ width: percent(data.pass_rate) }} />
      </div>
      <div className="variant-details">
        <span>
          Task success <b>{data.total ? percent(data.pass_rate) : "—"}</b>
        </span>
        <span>
          Effect invariants <b>{data.total ? percent(data.safe_rate) : "—"}</b>
        </span>
        <span>
          p95 latency <b>{data.total ? elapsed(data.p95_latency_ms) : "—"}</b>
        </span>
      </div>
    </div>
  );
}

function NewExperiment({
  scenarios,
  config,
  busy,
  onRun,
  onClose,
}: {
  scenarios: Scenario[];
  config: Config | null;
  busy: boolean;
  onRun: (body: object) => void;
  onClose: () => void;
}) {
  const [provider, setProvider] = useState("scripted");
  const [name, setName] = useState("");
  const [repeats, setRepeats] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(scenarios.map((s) => s.id)),
  );
  const [category, setCategory] = useState("all");
  const [custom, setCustom] = useState<CustomScenario[] | null>(null);
  const [fileName, setFileName] = useState("");
  const [importError, setImportError] = useState("");
  const [importing, setImporting] = useState(false);
  const importVersion = useRef(0);
  const available = custom ?? scenarios;
  const categories = [...new Set(available.map((s) => s.category))];
  const filtered = available.filter(
    (s) => category === "all" || s.category === category,
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    onRun({
      name: name.trim() || undefined,
      provider,
      repeats,
      ...(custom
        ? { scenarios: custom.filter((s) => selected.has(s.id)) }
        : { scenario_ids: [...selected] }),
    });
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    const version = ++importVersion.current;
    setImportError("");
    setImporting(true);
    try {
      if (file.size > MAX_IMPORT_BYTES)
        throw new Error("The JSON file must be 1 MB or smaller.");
      const parsed = parseScenarios(await file.text());
      if (version !== importVersion.current) return;
      setCustom(parsed);
      setFileName(file.name);
      setSelected(new Set(parsed.map((s) => s.id)));
      setCategory("all");
    } catch (err) {
      if (version === importVersion.current)
        setImportError(
          err instanceof Error ? err.message : "Unable to read this file.",
        );
    } finally {
      if (version === importVersion.current) setImporting(false);
    }
  }
  function restoreBuiltIn() {
    ++importVersion.current;
    setImporting(false);
    setCustom(null);
    setFileName("");
    setImportError("");
    setCategory("all");
    setSelected(new Set(scenarios.map((s) => s.id)));
  }
  function downloadExample() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(exampleScenarios, null, 2)], {
        type: "application/json",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "agentproof-scenarios.example.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  return (
    <section className="composer" aria-label="Configure experiment">
      <div className="section-top">
        <div>
          <h2>Configure an experiment</h2>
          <p>Each scenario runs against both strategies in a fresh sandbox.</p>
        </div>
        <button
          className="icon-button"
          aria-label="Close experiment configuration"
          onClick={onClose}
          disabled={busy}
        >
          <X size={18} />
        </button>
      </div>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>
            Experiment name
            <input
              placeholder="e.g. Refund policy regression"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              disabled={busy}
            />
          </label>
          <label>
            Decision provider
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              disabled={busy}
            >
              <option value="scripted">Scripted fixture · no API calls</option>
              <option value="openai" disabled={!config?.live_configured}>
                Live model
                {config?.live_configured
                  ? ` · ${config.model}`
                  : " · configure server first"}
              </option>
            </select>
          </label>
          <label>
            Trials per scenario
            <select
              value={repeats}
              onChange={(e) => setRepeats(Number(e.target.value))}
              disabled={busy}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} {n === 1 ? "trial" : "trials"}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="suite-source">
          <div>
            <b>
              {custom ? "Imported scenario suite" : "Built-in scenario suite"}
            </b>
            <p>
              {custom
                ? `${fileName} · ${custom.length} scenarios · server validates before execution`
                : "Use the authored fixtures, or import your own typed scenario JSON."}
            </p>
          </div>
          <div className="suite-source-actions">
            <label
              className={`button small file-button ${busy || importing ? "disabled" : ""}`}
            >
              <Upload size={13} />
              {importing ? "Reading file…" : "Import JSON"}
              <input
                type="file"
                accept=".json,application/json"
                aria-label="Import scenario JSON"
                disabled={busy || importing}
                onChange={(event) => {
                  void importFile(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
            </label>
            <button
              type="button"
              className="text-button"
              onClick={custom ? restoreBuiltIn : downloadExample}
              disabled={busy}
            >
              {custom ? "Use built-in suite" : "Download example"}
            </button>
          </div>
        </div>
        {importError && (
          <div className="import-error" role="alert">
            <XCircle size={15} />
            <span>
              {importError} The previously selected suite has been kept.
            </span>
          </div>
        )}
        <div className="selection-header">
          <span>
            <b>{selected.size}</b> of {available.length} scenarios selected
          </span>
          <div>
            <button
              type="button"
              className="text-button"
              onClick={() => setSelected(new Set(available.map((s) => s.id)))}
              disabled={busy}
            >
              Select all
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => setSelected(new Set())}
              disabled={busy}
            >
              Clear
            </button>
            <select
              aria-label="Filter scenario categories"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {words(c)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="scenario-picker">
          {filtered.map((s) => (
            <label
              className={`scenario-option ${selected.has(s.id) ? "selected" : ""}`}
              key={s.id}
            >
              <input
                type="checkbox"
                checked={selected.has(s.id)}
                onChange={() => toggle(s.id)}
                disabled={busy}
              />
              <span>
                <b>{s.name}</b>
                <small>{s.description}</small>
              </span>
              <em>{words(s.category)}</em>
            </label>
          ))}
        </div>
        <div className="composer-footer">
          <p>
            {provider === "scripted"
              ? "Scripted runs test the harness and fault recovery. They do not measure LLM quality."
              : "This uses the configured model endpoint. Usage may incur provider charges."}
          </p>
          <button
            className="button primary"
            disabled={busy || importing || !selected.size || !config}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Play size={15} fill="currentColor" />
            )}
            {busy
              ? "Running experiment…"
              : `Run ${selected.size * repeats * 2} trials`}
          </button>
        </div>
      </form>
    </section>
  );
}

function RunInspector({
  run,
  busy,
  replayBlocked,
  readOnly = false,
  onReplay,
  onApprove,
  onClose,
}: {
  run: Run;
  busy: boolean;
  replayBlocked: boolean;
  readOnly?: boolean;
  onReplay: () => void;
  onApprove: (approved: boolean) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("trace");
  useEffect(() => setTab("trace"), [run.id]);
  return (
    <section className="inspector" aria-label="Run inspector">
      <div className="inspector-heading">
        <div>
          <div className="eyebrow">
            Run inspector <span>{run.variant}</span>
          </div>
          <h2>{run.scenario_name}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close run inspector"
        >
          <X size={18} />
        </button>
      </div>
      <div className="run-meta">
        <RunStatus run={run} />
        <ProviderBadge provider={run.provider} />
        <span className="mono">{run.id.slice(0, 8)}</span>
        {readOnly && (
          <span className="archive-read-only">Read-only record</span>
        )}
      </div>
      {run.parent_run_id && (
        <div className="replay-note">
          <RotateCcw size={13} />
          Fresh execution replay of {run.parent_run_id.slice(0, 8)}
        </div>
      )}
      <div className="outcome">
        <span>Observed outcome</span>
        <strong>{words(run.outcome)}</strong>
        <small>Expected: {words(run.expected_outcome)}</small>
      </div>
      <div className="run-stats">
        <div>
          <b>{elapsed(run.latency_ms)}</b>
          <span>Duration</span>
        </div>
        <div>
          <b>{run.model_calls}</b>
          <span>Model calls</span>
        </div>
        <div>
          <b>{run.retries}</b>
          <span>Retries</span>
        </div>
        <div>
          <b>{run.token_usage ?? 0}</b>
          <span>Tokens</span>
        </div>
      </div>
      {readOnly && run.status === "awaiting_approval" && (
        <div className="historical-approval">
          <LockKeyhole size={17} />
          <div>
            <b>Historically pending approval</b>
            <p>
              This record stopped before a refund was executed. Its decision and
              ledger are preserved; approval is unavailable here.
            </p>
          </div>
        </div>
      )}
      {!readOnly && run.status === "awaiting_approval" && (
        <div className="approval-box">
          <ShieldCheck size={18} />
          <div>
            <b>Review required</b>
            <p>
              This simulated refund is paused before execution. Inspect the
              proposed action and checks before deciding.
            </p>
            <div>
              <button
                className="button primary small"
                disabled={busy}
                onClick={() => onApprove(true)}
              >
                Approve refund
              </button>
              <button
                className="button small"
                disabled={busy}
                onClick={() => onApprove(false)}
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Run details">
        {["trace", "checks", "state"].map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            id={`tab-${t}`}
            aria-controls={`panel-${t}`}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t === "trace"
              ? `Trace · ${run.events.length}`
              : t === "checks"
                ? `Checks · ${run.checks.length}`
                : "Final state"}
          </button>
        ))}
      </div>
      <div
        className="inspector-content"
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
      >
        {tab === "trace" && (
          <ol className="trace-list">
            {run.events.map((event, i) => (
              <li key={`${event.index}-${i}`}>
                <div
                  className={`event-dot ${/fail|error|reject|block/i.test(event.status) ? "event-error" : ""}`}
                >
                  {i + 1}
                </div>
                <details open={i === 0}>
                  <summary>
                    <span>
                      <b>{words(event.name)}</b>
                      <small>
                        {words(event.kind)} <span>· {words(event.status)}</span>
                      </small>
                    </span>
                    <em>{elapsed(event.duration_ms)}</em>
                    <ChevronDown size={13} />
                  </summary>
                  <pre>{JSON.stringify(event.detail, null, 2)}</pre>
                </details>
              </li>
            ))}
            {run.events.length === 0 && (
              <p className="empty-inline">No trace events were recorded.</p>
            )}
          </ol>
        )}
        {tab === "checks" && (
          <div className="check-list">
            {run.checks.map((check, index) => (
              <div
                key={`${check.name}-${index}`}
                className={`check-row ${check.passed ? "pass" : "fail"}`}
              >
                {check.passed ? (
                  <CheckCircle2 size={17} />
                ) : (
                  <XCircle size={17} />
                )}
                <div>
                  <b>{words(check.name)}</b>
                  <p>{check.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}
        {tab === "state" && (
          <>
            <p className="state-note">
              Sandbox state after this run. No real customer accounts or
              payments are involved.
            </p>
            <pre className="state-code">
              {JSON.stringify(run.final_state, null, 2)}
            </pre>
          </>
        )}
      </div>
      {!readOnly && (
        <div className="inspector-footer">
          <button
            className="button"
            disabled={busy || replayBlocked}
            onClick={onReplay}
          >
            {busy ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <RotateCcw size={14} />
            )}
            Replay in fresh sandbox
          </button>
          <small>
            {replayBlocked
              ? "Replay is available after the active experiment finishes."
              : "Re-executes the scenario and strategy."}
          </small>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [history, setHistory] = useState<Experiment[]>([]);
  const [source, setSource] = useState<ExperimentSource | null>(null);
  const sourceRef = useRef<ExperimentSource | null>(null);
  const [archive, setArchive] = useState<RecordedEvidence | null>(null);
  const [library, setLibrary] = useState<EvidenceCatalogItem[]>([]);
  const [archiveError, setArchiveError] = useState("");
  const [selectionPending, setSelectionPending] = useState(false);
  const readOnly = source?.kind === "archive";
  function selectSource(next: ExperimentSource) {
    sourceRef.current = next;
    setSource(next);
  }
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [syncError, setSyncError] = useState("");
  const [composer, setComposer] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const selectionVersion = useRef(0);
  const inspectorVersion = useRef(0);
  const inspectorAnchor = useRef<HTMLDivElement>(null);

  async function openExperiment(id: string) {
    const version = ++selectionVersion.current;
    ++inspectorVersion.current;
    setSelectionPending(true);
    setError("");
    setNotice("");
    setSyncError("");
    try {
      const result = await api<Experiment>(
        `/experiments/${encodeURIComponent(id)}`,
      );
      if (version !== selectionVersion.current) return;
      selectSource({ kind: "workspace", id });
      setArchive(null);
      setExperiment(result);
      setSelectedRun(null);
      setComposer(false);
      setSearch("");
      setFilter("all");
    } catch (err) {
      if (version !== selectionVersion.current) return;
      setError(
        err instanceof Error ? err.message : "Unable to load experiment.",
      );
    } finally {
      if (version === selectionVersion.current) setSelectionPending(false);
    }
  }
  async function openArchive(archiveId: string) {
    const version = ++selectionVersion.current;
    ++inspectorVersion.current;
    setSelectionPending(true);
    setError("");
    setNotice("");
    setSyncError("");
    try {
      const result = await api<EvidenceEnvelope>(
        `/evidence/${encodeURIComponent(archiveId)}`,
      );
      if (version !== selectionVersion.current) return;
      selectSource({ kind: "archive", archiveId });
      setArchive(result.archive);
      setExperiment(result.experiment);
      setSelectedRun(null);
      setComposer(false);
      setSearch("");
      setFilter("all");
    } catch (err) {
      if (version === selectionVersion.current)
        setError(
          err instanceof Error
            ? err.message
            : "Recorded evidence could not be opened.",
        );
    } finally {
      if (version === selectionVersion.current) setSelectionPending(false);
    }
  }
  async function initialize() {
    setLoading(true);
    setError("");
    const version = selectionVersion.current;
    try {
      const [newScenarios, newConfig, experiments, recorded] =
        await Promise.all([
          api<Scenario[]>("/scenarios"),
          api<Config>("/config"),
          api<Experiment[]>("/experiments"),
          api<EvidenceCatalogItem[]>("/evidence").catch(() => {
            setArchiveError(
              "Recorded evidence is unavailable. Workspace experiments are still available.",
            );
            return [];
          }),
        ]);
      setLibrary(recorded);
      if (recorded.length) setArchiveError("");
      setScenarios(newScenarios);
      setConfig(newConfig);
      setHistory(experiments);
      if (
        version === selectionVersion.current &&
        sourceRef.current?.kind !== "archive" &&
        experiments.length
      ) {
        const previous =
          sourceRef.current?.kind === "workspace" ? sourceRef.current.id : null;
        await openExperiment(
          experiments.find((item) => item.id === previous)?.id ??
            experiments[0].id,
        );
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to connect to the API.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void initialize();
  }, []);

  const selectedActive = Boolean(
    source?.kind === "workspace" && experiment && isActive(experiment.status),
  );
  const historyActive = history.some((item) => isActive(item.status));
  useEffect(() => {
    if (busy || (!selectedActive && !historyActive)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      const version = selectionVersion.current;
      try {
        const [updatedHistory, updated] = await Promise.all([
          api<Experiment[]>("/experiments", undefined, controller.signal),
          selectedActive && experiment
            ? api<Experiment>(
                `/experiments/${encodeURIComponent(experiment.id)}`,
                undefined,
                controller.signal,
              )
            : Promise.resolve(null),
        ]);
        if (stopped || version !== selectionVersion.current) return;
        setHistory(updatedHistory);
        setSyncError("");
        if (updated) {
          setExperiment(updated);
          setSelectedRun((previous) =>
            previous
              ? (updated.runs?.find((run) => run.id === previous.id) ??
                previous)
              : null,
          );
          if (!isActive(updated.status))
            setNotice(
              updated.status === "completed"
                ? "Experiment complete. All planned trials have finished."
                : `Experiment ${updated.status}. Completed trial evidence is available for review.`,
            );
        }
      } catch (err) {
        if (
          !stopped &&
          version === selectionVersion.current &&
          !(err instanceof DOMException && err.name === "AbortError")
        )
          setSyncError(
            "Live updates could not connect. Retrying automatically; your current results are preserved.",
          );
      } finally {
        if (!stopped) timer = setTimeout(() => void poll(), 1000);
      }
    }
    timer = setTimeout(() => void poll(), 500);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [experiment?.id, selectedActive, historyActive, busy]);

  async function runExperiment(body: object) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<Experiment>(
        "/experiments?background=true",
        body,
      );
      ++selectionVersion.current;
      ++inspectorVersion.current;
      selectSource({ kind: "workspace", id: result.id });
      setArchive(null);
      setSelectionPending(false);
      setExperiment(result);
      setSelectedRun(null);
      setComposer(false);
      setSearch("");
      setFilter("all");
      setHistory(await api<Experiment[]>("/experiments"));
      setNotice(
        isActive(result.status)
          ? "Experiment queued. Results update automatically as each trial finishes."
          : "Experiment complete. Select a trial to inspect its evidence.",
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The experiment could not complete.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function cancelExperiment() {
    if (
      sourceRef.current?.kind !== "workspace" ||
      selectionPending ||
      !experiment ||
      !isActive(experiment.status)
    )
      return;
    const id = experiment.id;
    const version = selectionVersion.current;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Experiment>(
        `/experiments/${encodeURIComponent(id)}/cancel`,
        {},
      );
      if (version !== selectionVersion.current) return;
      setExperiment(updated);
      setHistory(await api<Experiment[]>("/experiments"));
      setNotice(
        updated.status === "cancelled"
          ? "Experiment stopped. Completed trials are retained."
          : "Stop requested. The current trial will finish before the experiment stops.",
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to request cancellation.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function runAction(action: "replay" | "approve", approved = true) {
    if (
      sourceRef.current?.kind !== "workspace" ||
      selectionPending ||
      !selectedRun
    )
      return;
    const version = selectionVersion.current;
    const inspector = inspectorVersion.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const run = await api<Run>(
        `/runs/${encodeURIComponent(selectedRun.id)}/${action}`,
        action === "approve" ? { approved } : {},
      );
      if (version !== selectionVersion.current) return;
      if (inspector === inspectorVersion.current) setSelectedRun(run);
      if (experiment && action === "approve")
        setExperiment(
          await api<Experiment>(
            `/experiments/${encodeURIComponent(experiment.id)}`,
          ),
        );
      setHistory(await api<Experiment[]>("/experiments"));
      setNotice(
        action === "replay"
          ? "Replay complete. The new run is shown in the inspector; the original experiment remains the comparison record."
          : approved
            ? "Approval recorded. The inspector shows the updated run."
            : "Rejection recorded. No new refund was approved.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update run.");
    } finally {
      setBusy(false);
    }
  }
  function selectRun(run: Run) {
    ++inspectorVersion.current;
    setSelectedRun(run);
    if (window.innerWidth < 1100)
      setTimeout(
        () =>
          inspectorAnchor.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          }),
        30,
      );
  }

  const grouped = useMemo(() => {
    const groups = new Map<
      string,
      {
        id: string;
        name: string;
        category: string;
        baseline: Run[];
        guarded: Run[];
      }
    >();
    for (const run of experiment?.runs ?? []) {
      if (!groups.has(run.scenario_id))
        groups.set(run.scenario_id, {
          id: run.scenario_id,
          name: run.scenario_name,
          category: run.category,
          baseline: [],
          guarded: [],
        });
      groups.get(run.scenario_id)![run.variant].push(run);
    }
    return [...groups.values()].filter((group) => {
      const runs = [...group.baseline, ...group.guarded];
      const matchesSearch = `${group.name} ${group.category} ${group.id}`
        .toLowerCase()
        .includes(search.toLowerCase());
      return (
        matchesSearch &&
        (filter === "all" ||
          (filter === "failed" && runs.some((r) => !r.passed)) ||
          (filter === "approval" &&
            runs.some((r) => r.status === "awaiting_approval")) ||
          (filter === "recovered" &&
            group.baseline.some((r) => !r.passed) &&
            group.guarded.length > 0 &&
            group.guarded.every((r) => r.passed)))
      );
    });
  }, [experiment, search, filter]);

  const failureCount = (experiment?.runs ?? []).filter((r) => !r.passed).length;
  const approvalCount = (experiment?.runs ?? []).filter(
    (r) => r.status === "awaiting_approval",
  ).length;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#main">
          <div className="brand-mark">
            <Layers3 size={23} />
          </div>
          <span>
            AgentProof<small>RELEASE WORKBENCH</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-dot" />
          Refund operations<span className="mono">LAB</span>
        </div>
        <button
          className="nav-active"
          onClick={() => {
            setComposer(false);
            document.getElementById("main")?.scrollIntoView();
          }}
        >
          <GitCompareArrows size={17} />
          Experiments<span>{history.length}</span>
        </button>
        <div className="history-heading">
          <span>RECENT EXPERIMENTS</span>
          <button
            className="icon-button"
            title="Refresh experiments"
            aria-label="Refresh experiments"
            onClick={() => void initialize()}
            disabled={busy || loading}
          >
            <RefreshCw size={13} />
          </button>
        </div>
        <nav className="history" aria-label="Experiment history">
          {history.map((item) => (
            <button
              key={item.id}
              className={`history-item ${source?.kind === "workspace" && source.id === item.id ? "selected" : ""}`}
              onClick={() => void openExperiment(item.id)}
              disabled={busy}
            >
              <span
                className={`history-indicator ${item.summary?.gate?.passed ? "green" : "amber"}`}
              />
              <span>
                <b>{item.name || "Untitled experiment"}</b>
                <small>
                  {date(item.created_at)} ·{" "}
                  {item.provider === "scripted" ? "Scripted" : "Live"}
                  {isActive(item.status) &&
                    ` · ${item.status} ${item.summary.total_runs}/${item.summary.expected_runs ?? "?"}`}
                </small>
              </span>
            </button>
          ))}
          {!history.length && (
            <p className="history-empty">
              Your experiment history will appear here.
            </p>
          )}
        </nav>
        <section
          className="archive-library"
          aria-label="Recorded evidence library"
        >
          <div className="archive-heading">
            <BookOpen size={14} />
            <span>RECORDED EVIDENCE</span>
          </div>
          <p>Inspect saved trials. No model needed.</p>
          <nav className="archive-list" aria-label="Recorded evidence">
            {library.map((item) => (
              <button
                key={item.id}
                className={`archive-item ${source?.kind === "archive" && source.archiveId === item.id ? "selected" : ""}`}
                disabled={busy || !item.available}
                title={item.available ? item.suite_provenance : item.error}
                aria-label={`Open recorded ${item.title}`}
                onClick={() => void openArchive(item.id)}
              >
                <BookOpen size={13} />
                <span>
                  <b>{item.title}</b>
                  <small>
                    {item.available
                      ? `${item.trial_count} trials · ${item.provider === "openai" ? "Live model" : "Scripted"}`
                      : "Unavailable · integrity or packaging check"}
                  </small>
                </span>
              </button>
            ))}
          </nav>
          {archiveError && <p className="archive-error">{archiveError}</p>}
        </section>
        <div className="sidebar-bottom">
          <div>
            <FlaskConical size={16} />
            <b>Isolated test environment</b>
          </div>
          <p>
            Synthetic orders. Simulated refunds. Every trial starts with fresh
            state.
          </p>
          <span className="version mono">AgentProof / v0.4</span>
        </div>
      </aside>
      <main id="main" className="main-content">
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <b>Agent reliability</b>
          </div>
          <span className={`connection ${config ? "connected" : ""}`}>
            <span />
            {loading
              ? "Connecting"
              : config
                ? "API connected"
                : "API unavailable"}
          </span>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">Evaluate before you release</div>
              <h1>Experiment workbench</h1>
              <p>
                Compare agent decisions when tools, policies, and context fail.
              </p>
            </div>
            <button
              className="button primary"
              onClick={() => setComposer(!composer)}
              disabled={busy || !config}
            >
              {composer ? <X size={16} /> : <Plus size={16} />}
              {composer ? "Close setup" : "New experiment"}
            </button>
          </div>
          {selectionPending && (
            <p className="selection-loading" role="status">
              <LoaderCircle size={14} className="spin" />
              Loading selected evidence…
            </p>
          )}
          {error && (
            <div className="alert error" role="alert">
              <XCircle size={18} />
              <div>
                <b>Something needs attention</b>
                <p>{error}</p>
              </div>
              <button
                className="button small"
                onClick={() => void initialize()}
                disabled={busy}
              >
                Reconnect
              </button>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert notice" role="status">
              <CheckCircle2 size={16} />
              <p>{notice}</p>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {syncError && (
            <div className="alert sync-warning" role="status">
              <RefreshCw size={15} />
              <p>{syncError}</p>
            </div>
          )}
          {composer && (
            <NewExperiment
              scenarios={scenarios}
              config={config}
              busy={busy}
              onRun={(body) => void runExperiment(body)}
              onClose={() => setComposer(false)}
            />
          )}
          {loading && !experiment && (
            <div className="loading-state">
              <LoaderCircle className="spin" size={24} />
              <p>Loading the workbench…</p>
            </div>
          )}
          {!loading && !experiment && !composer && (
            <section className="welcome">
              <div className="welcome-visual">
                <div className="rail-label">BASELINE</div>
                <div className="rail">
                  <span />
                  <span />
                  <i />
                  <span />
                  <i />
                </div>
                <div className="rail-label">GUARDED</div>
                <div className="rail guarded-rail">
                  <span />
                  <span />
                  <span />
                  <span />
                  <span />
                </div>
              </div>
              <div className="welcome-copy">
                <span className="eyebrow">Your first release test</span>
                <h2>See exactly where an agent fails.</h2>
                <p>
                  Run the built-in refund scenarios, compare both strategies,
                  and follow each decision from tool observation to final ledger
                  state.
                </p>
                <button
                  className="button primary"
                  onClick={() => setComposer(true)}
                  disabled={!config}
                >
                  <Play size={14} />
                  Configure first experiment
                  <ArrowRight size={15} />
                </button>
                <small>
                  Start with scripted fixtures. No API key required.
                </small>
                {library.some((item) => item.available) && (
                  <button
                    className="button welcome-archive"
                    onClick={() =>
                      void openArchive(
                        library.find((item) => item.available)!.id,
                      )
                    }
                  >
                    <BookOpen size={15} />
                    Inspect recorded model evidence
                  </button>
                )}
              </div>
              <div className="welcome-features">
                <span>
                  <Activity size={16} />
                  <b>Controlled failures</b>
                  <small>Timeouts, stale policy, injected instructions</small>
                </span>
                <span>
                  <Terminal size={16} />
                  <b>Inspectable evidence</b>
                  <small>Tool events, checks, and final sandbox state</small>
                </span>
                <span>
                  <ShieldCheck size={16} />
                  <b>Explicit release checks</b>
                  <small>Safety and outcome gates for this suite</small>
                </span>
              </div>
            </section>
          )}
          {experiment && (
            <>
              {readOnly && archive && (
                <section
                  className="archive-banner"
                  aria-label="Recorded evidence provenance"
                >
                  <div className="archive-banner-top">
                    <LockKeyhole size={20} />
                    <div>
                      <strong>
                        Read-only · recorded{" "}
                        {archive.provider === "openai" ? "model" : "scripted"}{" "}
                        evidence
                      </strong>
                      <p>
                        {archive.title} · {archive.trial_count} trials across{" "}
                        {archive.distinct_cases} cases. Browsing makes no model
                        calls.
                      </p>
                    </div>
                  </div>
                  <p className="archive-provenance">
                    {archive.suite_provenance}
                  </p>
                  <details>
                    <summary>Recorded provenance</summary>
                    <dl>
                      <div>
                        <dt>Recorded</dt>
                        <dd>
                          {date(archive.recorded_at)} · {archive.source_version}
                        </dd>
                      </div>
                      <div>
                        <dt>Model</dt>
                        <dd>{archive.model}</dd>
                      </div>
                      <div>
                        <dt>Model revision</dt>
                        <dd>{archive.model_revision}</dd>
                      </div>
                      <div>
                        <dt>Executed source SHA-256</dt>
                        <dd>{archive.backend_source_sha256}</dd>
                      </div>
                      <div>
                        <dt>Suite SHA-256</dt>
                        <dd>{archive.suite_hash}</dd>
                      </div>
                      <div>
                        <dt>Original file SHA-256</dt>
                        <dd>{archive.sha256}</dd>
                      </div>
                    </dl>
                    <p>
                      {archive.validation} {archive.integrity_note}
                    </p>
                  </details>
                </section>
              )}
              <section className="experiment-overview">
                <div className="experiment-title">
                  <div>
                    <div className="eyebrow mono">
                      {readOnly ? "RECORDED EXPERIMENT" : "EXPERIMENT"} /{" "}
                      {experiment.id.slice(0, 8)}
                    </div>
                    <h2>
                      {readOnly && archive
                        ? archive.title
                        : experiment.name || "Untitled experiment"}
                    </h2>
                    <div className="experiment-meta">
                      <ProviderBadge provider={experiment.provider} />
                      <span>{date(experiment.created_at)}</span>
                      <span>{experiment.summary.total_runs} trials</span>
                      <span
                        className={`experiment-status ${experiment.status}`}
                      >
                        {words(experiment.status)}
                      </span>
                    </div>
                  </div>
                  <a
                    className="button"
                    href={
                      readOnly && archive
                        ? archive.download_url
                        : `/api/experiments/${encodeURIComponent(experiment.id)}/export`
                    }
                    download
                  >
                    <ArrowDownToLine size={15} />
                    {readOnly ? "Download recorded JSON" : "Export JSON"}
                  </a>
                </div>
                {experiment.status !== "completed" && (
                  <div className={`experiment-progress ${experiment.status}`}>
                    <div className="progress-copy">
                      <div>
                        {selectedActive ? (
                          <LoaderCircle
                            size={15}
                            className={
                              experiment.cancel_requested ? "" : "spin"
                            }
                          />
                        ) : (
                          <Circle size={13} />
                        )}
                        <b>
                          {experiment.cancel_requested && selectedActive
                            ? "Stopping after current trial…"
                            : experiment.status === "queued"
                              ? "Waiting to start"
                              : experiment.status === "running"
                                ? "Evaluating scenarios"
                                : `Experiment ${experiment.status}`}
                        </b>
                      </div>
                      <span>
                        {experiment.summary.total_runs} of{" "}
                        {experiment.summary.expected_runs ??
                          experiment.summary.total_runs}{" "}
                        trials completed
                      </span>
                    </div>
                    <progress
                      aria-label="Experiment progress"
                      value={experiment.summary.total_runs}
                      max={Math.max(
                        experiment.summary.expected_runs ??
                          experiment.summary.total_runs,
                        1,
                      )}
                    />
                    <div className="progress-actions">
                      <p>
                        {selectedActive
                          ? "Inspect finished trials while the remaining scenarios run. Partial results cannot pass the release gate."
                          : "Completed trials are retained. This incomplete experiment cannot pass the release gate."}
                      </p>
                      {selectedActive && (
                        <button
                          className="button small"
                          disabled={
                            busy ||
                            selectionPending ||
                            experiment.cancel_requested
                          }
                          onClick={() => void cancelExperiment()}
                        >
                          Stop after current trial
                        </button>
                      )}
                    </div>
                  </div>
                )}
                <div className="comparison">
                  <VariantResult
                    name="Baseline"
                    data={experiment.summary.baseline}
                  />
                  <VariantResult
                    name="Guarded"
                    data={experiment.summary.guarded}
                    guarded
                  />
                  <div
                    className={`gate-result ${selectedActive ? "gate-pending" : experiment.summary.gate.passed ? "gate-pass" : "gate-fail"}`}
                  >
                    <span>
                      {selectedActive ? (
                        <Clock3 size={20} />
                      ) : experiment.summary.gate.passed ? (
                        <ShieldCheck size={20} />
                      ) : (
                        <ShieldX size={20} />
                      )}
                      Experiment gate
                    </span>
                    <strong>
                      {selectedActive
                        ? "Evaluation in progress"
                        : experiment.summary.gate.passed
                          ? "Checks passed"
                          : "Review required"}
                    </strong>
                    <p>
                      {experiment.summary.gate.reasons.length
                        ? experiment.summary.gate.reasons.join(" ")
                        : "Guarded outcomes meet this experiment’s safety and success thresholds."}
                    </p>
                    <small>Scope: this scenario suite only</small>
                  </div>
                </div>
                <div className="evidence-note">
                  <FlaskConical size={14} />
                  <span>
                    {experiment.provider === "scripted"
                      ? "Scripted evidence measures harness behavior and fault recovery, not LLM intelligence or real-world success."
                      : `Live model evidence · ${experiment.summary.provider_label || config?.model || "configured endpoint"} · Results apply to these scenarios and trials.`}
                  </span>
                </div>
              </section>
              {!readOnly && (
                <ReleaseComparison
                  key={`workspace:${experiment.id}`}
                  candidate={experiment}
                  history={history}
                />
              )}
              {readOnly && (
                <p className="archive-comparison-note">
                  This historical snapshot is preserved. Release comparisons are
                  available for experiments in your workspace.
                </p>
              )}
              <div
                className={`results-layout ${selectedRun ? "with-inspector" : ""}`}
              >
                <section className="matrix-panel">
                  <div className="section-top">
                    <div>
                      <h2>
                        Scenario comparison{" "}
                        <span className="count">{grouped.length}</span>
                      </h2>
                      <p>
                        Select a trial to inspect decisions and state changes.
                      </p>
                    </div>
                    <SlidersHorizontal size={17} className="muted" />
                  </div>
                  <div className="matrix-toolbar">
                    <div className="filter-pills" aria-label="Filter results">
                      {[
                        ["all", "All"],
                        ["failed", `Failures ${failureCount}`],
                        ["recovered", "Recovered"],
                        ["approval", `Approval ${approvalCount}`],
                      ].map(([value, label]) => (
                        <button
                          key={value}
                          className={filter === value ? "active" : ""}
                          onClick={() => setFilter(value)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <label className="search-field">
                      <Search size={14} />
                      <input
                        aria-label="Search scenarios"
                        placeholder="Find scenario…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="matrix-scroll">
                    <table className="scenario-table">
                      <thead>
                        <tr>
                          <th>Scenario</th>
                          <th>Baseline</th>
                          <th>Guarded</th>
                        </tr>
                      </thead>
                      <tbody>
                        {grouped.map((group) => (
                          <tr
                            key={group.id}
                            className={
                              selectedRun?.scenario_id === group.id
                                ? "selected-row"
                                : ""
                            }
                          >
                            <td>
                              <b>{group.name}</b>
                              <span>{words(group.category)}</span>
                            </td>
                            {(["baseline", "guarded"] as const).map(
                              (variant) => (
                                <td key={variant}>
                                  <div className="trial-cells">
                                    {group[variant].map((run, index) => (
                                      <button
                                        className={`trial-button ${selectedRun?.id === run.id ? "selected" : ""}`}
                                        key={run.id}
                                        onClick={() => selectRun(run)}
                                        title={`${variant}, trial ${index + 1}: ${run.outcome}`}
                                        aria-label={`Inspect ${group.name}, ${variant}, trial ${index + 1}`}
                                      >
                                        <RunStatus run={run} />
                                        {group[variant].length > 1 && (
                                          <small>{index + 1}</small>
                                        )}
                                        <ChevronRight size={12} />
                                      </button>
                                    ))}
                                  </div>
                                </td>
                              ),
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!grouped.length && (
                      <div className="no-results">
                        {selectedActive && !experiment.runs?.length ? (
                          <Clock3 size={22} />
                        ) : (
                          <Search size={22} />
                        )}
                        <h3>
                          {selectedActive && !experiment.runs?.length
                            ? "Waiting for the first trial"
                            : "No matching scenarios"}
                        </h3>
                        <p>
                          {selectedActive && !experiment.runs?.length
                            ? "Completed trials will appear here automatically."
                            : "Try another search or reset the result filters."}
                        </p>
                        {!!experiment.runs?.length && (
                          <button
                            className="button small"
                            onClick={() => {
                              setSearch("");
                              setFilter("all");
                            }}
                          >
                            Reset filters
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="matrix-footer">
                    <span>
                      <span className="legend-dot pass-dot" />
                      Task passed
                    </span>
                    <span>
                      <span className="legend-dot fail-dot" />
                      Check failed
                    </span>
                    <span>
                      <span className="legend-dot pending-dot" />
                      Waiting for review
                    </span>
                  </div>
                </section>
                {selectedRun && (
                  <div ref={inspectorAnchor} className="inspector-anchor">
                    <RunInspector
                      run={selectedRun}
                      busy={busy || selectionPending}
                      readOnly={readOnly}
                      replayBlocked={selectedActive || historyActive}
                      onReplay={() => void runAction("replay")}
                      onApprove={(approved) =>
                        void runAction("approve", approved)
                      }
                      onClose={() => {
                        ++inspectorVersion.current;
                        setSelectedRun(null);
                      }}
                    />
                  </div>
                )}
              </div>
            </>
          )}
          <footer className="page-footer">
            <span>AgentProof</span>
            <p>
              Deterministic checks. Visible decisions. Reproducible experiments.
            </p>
            <a href="/api/docs">
              API reference
              <ArrowRight size={12} />
            </a>
          </footer>
        </div>
      </main>
    </div>
  );
}
