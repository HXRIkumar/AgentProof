import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  FileText,
  FlaskConical,
  Layers3,
  LoaderCircle,
  Plus,
  SlidersHorizontal,
  Terminal,
  Trash2,
  XCircle,
} from "lucide-react";
import type {
  AnswerConfig,
  AnswerResult,
  AnswerSource,
  AnswerStrategy,
  AnswerTask,
} from "./answerTypes";
import {
  answerFetch,
  ANSWER_RECORDED_ONLY,
  number,
  STRATEGIES,
  STRATEGY_LABELS,
} from "./answerUtils";
import { EmptyResult, ResultInspector } from "./AnswerLabResult";

const EXAMPLE_SOURCES: AnswerSource[] = [
  {
    id: "release-notes",
    title: "Atlas · release notes",
    text: "Atlas is a document search service. The private beta opened on 14 March 2024. The general release followed on 22 July 2024. During the beta, workspaces could store 500 documents. The general release increased this limit to 2,000 documents. Atlas is maintained by the Search Platform team.",
  },
];
const EXTRACTION_SOURCE: AnswerSource[] = [
  {
    id: "incident-042",
    title: "Incident 042 · service report",
    text: "Incident INC-042 affected the search API on 8 October 2026. The incident started at 14:20 UTC and was resolved at 14:47 UTC. The severity was SEV-2. Priya Shah was the incident commander. The root cause was a connection pool exhausted by a traffic spike. The team increased the pool capacity and restored service. No customer data was lost.",
  },
];
const EXTRACTION_SCHEMA = JSON.stringify(
  {
    type: "object",
    properties: {
      incident_id: { type: "string" },
      severity: { type: "string", enum: ["SEV-1", "SEV-2", "SEV-3"] },
      owner: { type: "string" },
      data_loss: { type: "boolean" },
    },
    required: ["incident_id", "severity", "owner", "data_loss"],
    additionalProperties: false,
  },
  null,
  2,
);
const EMPTY_SOURCE: AnswerSource = {
  id: "source-1",
  title: "Untitled source",
  text: "",
};

export default function Workspace({
  config,
  onRun,
  initial,
  onOpenReports,
}: {
  config: AnswerConfig | null;
  onRun: (result: AnswerResult) => void;
  initial: AnswerResult | null;
  onOpenReports: () => void;
}) {
  const [sources, setSources] = useState<AnswerSource[]>(
    EXAMPLE_SOURCES.map((s) => ({ ...s })),
  );
  const [sourceIndex, setSourceIndex] = useState(0);
  const [question, setQuestion] = useState(
    "When was Atlas generally released?",
  );
  const [task, setTask] = useState<AnswerTask>("qa");
  const [schema, setSchema] = useState(EXTRACTION_SCHEMA);
  const [strategy, setStrategy] = useState<AnswerStrategy>("adaptive");
  const [attempts, setAttempts] = useState(3);
  const [cache, setCache] = useState(true);
  const [result, setResult] = useState<AnswerResult | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [example, setExample] = useState("release");
  const selected = sources[sourceIndex] || sources[0];
  const questionRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!initial) return;
    setResult(initial);
    setQuestion(initial.question);
    setTask(initial.task);
    setStrategy(initial.strategy);
    if (initial.sources?.length) {
      setSources(initial.sources.map((source) => ({ ...source })));
      setSourceIndex(0);
      setExample("blank");
    }
    if (initial.schema) setSchema(JSON.stringify(initial.schema, null, 2));
  }, [initial]);
  const editSource = (field: "title" | "text", value: string) =>
    setSources((old) =>
      old.map((s, i) => (i === sourceIndex ? { ...s, [field]: value } : s)),
    );
  function chooseExample(name: string) {
    setExample(name);
    setSourceIndex(0);
    setError("");
    if (name === "release") {
      setSources(EXAMPLE_SOURCES.map((s) => ({ ...s })));
      setQuestion("When was Atlas generally released?");
      setTask("qa");
    }
    if (name === "extraction") {
      setSources(EXTRACTION_SOURCE.map((s) => ({ ...s })));
      setQuestion(
        "Extract the incident ID, severity, owner, and whether customer data was lost.",
      );
      setTask("extraction");
      setSchema(EXTRACTION_SCHEMA);
    }
    if (name === "blank") {
      setSources([{ ...EMPTY_SOURCE }]);
      setQuestion("");
    }
    questionRef.current?.focus();
  }
  async function run(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError("");
    let parsed: Record<string, unknown> | null = null;
    if (task === "extraction") {
      try {
        parsed = JSON.parse(schema);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
          throw new Error();
      } catch {
        setError("Enter a valid JSON Schema object before running extraction.");
        return;
      }
    }
    if (
      !question.trim() ||
      sources.some((s) => !s.text.trim() || !s.title.trim())
    ) {
      setError(
        "Add a question, title, and content for every source, or remove empty sources.",
      );
      return;
    }
    if (sources.reduce((sum, source) => sum + source.text.length, 0) > 80000) {
      setError(
        "Source material exceeds 80,000 characters. Shorten or remove a source before running.",
      );
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const output = await answerFetch<AnswerResult>("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question.trim(),
          sources,
          task,
          schema: parsed,
          strategy,
          max_attempts: strategy === "baseline" ? 1 : attempts,
          use_cache: cache && strategy === "adaptive",
          namespace: "workspace",
        }),
      });
      setResult(output);
      onRun(output);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The run failed. Check the local model connection and retry.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="al-page-heading">
        <div>
          <div className="al-eyebrow">ANSWER LAB</div>
          <h1>Workspace</h1>
          <p>Ask from your sources. Inspect every correction.</p>
        </div>
        <button className="al-button al-secondary" onClick={onOpenReports}>
          <FlaskConical size={15} /> View experiments <ArrowUpRight size={14} />
        </button>
      </div>
      <div className="al-workspace-grid">
        <form className="al-editor" onSubmit={run}>
          <div className="al-panel-heading">
            <div>
              <FileText size={16} />
              <h2>Source material</h2>
            </div>
            <select
              aria-label="Load example"
              value={example}
              onChange={(e) => chooseExample(e.target.value)}
              disabled={busy}
            >
              <option value="release">Example: release notes</option>
              <option value="extraction">Example: incident report</option>
              <option value="blank">Start blank</option>
            </select>
          </div>
          <div className="al-source-tabs">
            {sources.map((source, index) => (
              <button
                type="button"
                key={source.id}
                className={sourceIndex === index ? "active" : ""}
                onClick={() => setSourceIndex(index)}
              >
                <FileText size={13} />
                <span>{source.title || `Source ${index + 1}`}</span>
              </button>
            ))}
            <button
              type="button"
              aria-label="Add source"
              title="Add source"
              disabled={sources.length >= 12 || busy}
              onClick={() => {
                setSources((old) => [
                  ...old,
                  {
                    id: `source-${crypto.randomUUID().slice(0, 8)}`,
                    title: `Source ${sources.length + 1}`,
                    text: "",
                  },
                ]);
                setSourceIndex(sources.length);
                setExample("blank");
              }}
            >
              <Plus size={15} />
            </button>
          </div>
          <div className="al-source-editor">
            <div className="al-source-title">
              <input
                aria-label="Source title"
                value={selected.title}
                onChange={(e) => editSource("title", e.target.value)}
                maxLength={200}
                disabled={busy}
              />
              <button
                type="button"
                className="al-icon-button"
                aria-label="Remove source"
                disabled={sources.length === 1 || busy}
                onClick={() => {
                  setSources((old) => old.filter((_, i) => i !== sourceIndex));
                  setSourceIndex(0);
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
            <textarea
              aria-label="Source content"
              value={selected.text}
              onChange={(e) => editSource("text", e.target.value)}
              placeholder="Paste an article, report, or knowledge-base passage…"
              maxLength={24000}
              disabled={busy}
              spellCheck={false}
            />
            <div className="al-editor-foot">
              <span>
                {sources.length} source{sources.length !== 1 ? "s" : ""} ·
                pasted text
              </span>
              <span>{number(selected.text.length)} characters</span>
            </div>
          </div>
          <div className="al-prompt-editor">
            <div className="al-field-heading">
              <label htmlFor="al-question">Question or instruction</label>
              <select
                aria-label="Task type"
                value={task}
                onChange={(e) => setTask(e.target.value as AnswerTask)}
                disabled={busy}
              >
                <option value="qa">Grounded answer</option>
                <option value="extraction">Structured extraction</option>
              </select>
            </div>
            <textarea
              ref={questionRef}
              id="al-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What should the model answer from these sources?"
              maxLength={2000}
              disabled={busy}
              required
            />
            {task === "extraction" && (
              <div className="al-schema">
                <label htmlFor="al-schema">
                  Output schema <span>JSON Schema</span>
                </label>
                <textarea
                  id="al-schema"
                  aria-label="Output schema"
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                  spellCheck={false}
                  disabled={busy}
                  maxLength={12000}
                />
              </div>
            )}
          </div>
          <div className="al-controls">
            <div className="al-control-heading">
              <SlidersHorizontal size={15} />
              <b>Answer strategy</b>
            </div>
            <div className="al-strategy-picker">
              {STRATEGIES.map((s) => (
                <label key={s} className={strategy === s ? "selected" : ""}>
                  <input
                    type="radio"
                    name="answer-strategy"
                    value={s}
                    checked={strategy === s}
                    onChange={() => setStrategy(s)}
                    disabled={busy}
                  />
                  <span>
                    <b>{STRATEGY_LABELS[s]}</b>
                    <small>
                      {s === "baseline"
                        ? "One generation"
                        : s === "validated"
                          ? "Repair invalid output"
                          : "Check evidence and meaning"}
                    </small>
                  </span>
                </label>
              ))}
            </div>
            <div className="al-options">
              <label>
                <input
                  type="checkbox"
                  checked={cache}
                  onChange={(e) => setCache(e.target.checked)}
                  disabled={busy || strategy !== "adaptive"}
                />
                Reuse accepted answers
              </label>
              <label>
                Attempt limit
                <select
                  aria-label="Attempt limit"
                  value={strategy === "baseline" ? 1 : attempts}
                  onChange={(e) => setAttempts(Number(e.target.value))}
                  disabled={busy || strategy === "baseline"}
                >
                  {[1, 2, 3].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          {error && (
            <div className="al-error" role="alert">
              <XCircle size={17} />
              <span>{error}</span>
            </div>
          )}
          {!config?.configured && (
            <div className="al-connection-note">
              <Terminal size={16} />
              <div>
                <b>
                  {ANSWER_RECORDED_ONLY
                    ? "Run the full workspace locally"
                    : "Connect a model to run"}
                </b>
                <p>
                  {ANSWER_RECORDED_ONLY
                    ? "This public viewer reads recorded evidence. Download AgentProof to connect a model and run your own sources."
                    : "Start the local model service, then configure Answer Lab on the server. Saved experiments remain available."}
                </p>
                {ANSWER_RECORDED_ONLY && (
                  <a
                    href="https://github.com/HXRIkumar/AgentProof#run-it"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Run locally <ArrowUpRight size={12} />
                  </a>
                )}
              </div>
            </div>
          )}
          <div className="al-submit-row">
            <span>
              {config?.configured ? (
                <>
                  <span className="al-dot" />
                  {config.model.split("/").at(-1)}
                </>
              ) : (
                "Model not connected"
              )}
            </span>
            <button
              className="al-button al-primary"
              type="submit"
              disabled={busy || !config?.configured}
            >
              {busy ? (
                <LoaderCircle size={16} className="al-spin" />
              ) : (
                <ArrowRight size={16} />
              )}
              {busy ? "Running…" : "Generate answer"}
            </button>
          </div>
        </form>
        <div className="al-output">
          <div className="al-panel-heading">
            <div>
              <Layers3 size={16} />
              <h2>Output</h2>
            </div>
            <span className="al-panel-hint">Answer · evidence · trace</span>
          </div>
          {result ? (
            <ResultInspector result={result} />
          ) : (
            <EmptyResult busy={busy} />
          )}
        </div>
      </div>
    </>
  );
}
