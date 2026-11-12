import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Database,
  FileText,
  Layers3,
  Terminal,
  X,
  XCircle,
} from "lucide-react";
import type {
  AnswerAttempt,
  AnswerResult,
  AnswerProviderMetadata,
} from "./answerTypes";
import { RunAccounting } from "./AnswerLabAccounting";
import {
  date,
  downloadJson,
  duration,
  human,
  number,
  percent,
} from "./answerUtils";

export function Status({ result }: { result: AnswerResult }) {
  const label =
    result.status === "accepted"
      ? "Checks passed"
      : result.status === "abstained"
        ? "Abstained"
        : result.status === "failed"
          ? "Checks failed"
          : "Run error";
  return (
    <span className={`al-status al-status-${result.status}`}>
      {result.status === "accepted" ? (
        <CheckCircle2 size={13} />
      ) : result.status === "abstained" ? (
        <Circle size={12} />
      ) : (
        <XCircle size={13} />
      )}
      {label}
    </span>
  );
}

export function EmptyResult({ busy }: { busy: boolean }) {
  return (
    <div className="al-empty-result" aria-live="polite">
      <div className={`al-empty-symbol ${busy ? "al-working" : ""}`}>
        <Layers3 size={29} strokeWidth={1.25} />
      </div>
      <h3>
        {busy ? "Working through the evidence" : "An answer you can inspect"}
      </h3>
      <p>
        {busy
          ? "The model is generating an answer and running the selected checks. Every model call is included in the final trace."
          : "Add source material and ask a question. See the answer, the evidence behind it, and what changed during correction."}
      </p>
      <div className="al-stage-preview">
        <span>
          <FileText size={15} /> Retrieve
        </span>
        <ArrowRight size={13} />
        <span>
          <Terminal size={15} /> Generate
        </span>
        <ArrowRight size={13} />
        <span>
          <CheckCircle2 size={15} /> Verify
        </span>
      </div>
      {!busy && <small>Results appear only after an actual run.</small>}
    </div>
  );
}

function AttemptPanel({
  attempt,
  selected,
}: {
  attempt: AnswerAttempt;
  selected: boolean;
}) {
  return (
    <details className="al-attempt" open={selected}>
      <summary>
        <span className="al-attempt-index">{attempt.index}</span>
        <span>
          <b>
            {attempt.index === 1
              ? "Initial answer"
              : `Revision ${attempt.index - 1}`}
            {selected && <span className="al-returned-tag">Returned</span>}
          </b>
          <small>
            {attempt.checks.filter((c) => c.passed).length}/
            {attempt.checks.length} checks passed
          </small>
        </span>
        <span className="al-attempt-time">{duration(attempt.latency_ms)}</span>
        <ChevronDown size={15} />
      </summary>
      <div className="al-attempt-body">
        <div className="al-trace-answer">
          {attempt.abstained ? (
            <em>No answer supported by the sources.</em>
          ) : attempt.data != null ? (
            <pre>{JSON.stringify(attempt.data, null, 2)}</pre>
          ) : (
            attempt.answer || <em>No usable answer returned.</em>
          )}
        </div>
        <ul className="al-check-list">
          {attempt.checks.map((check, i) => (
            <li
              key={`${check.name}-${i}`}
              className={check.passed ? "passed" : "failed"}
            >
              {check.passed ? <Check size={14} /> : <X size={14} />}
              <div>
                <b>{human(check.name)}</b>
                {!check.name.startsWith("critic_") && <p>{check.detail}</p>}
              </div>
            </li>
          ))}
        </ul>
        {attempt.critic && (
          <div className="al-critic">
            <div className="al-overline">Critic feedback</div>
            <p>{attempt.critic.feedback || "No additional feedback."}</p>
            <div className="al-critic-flags">
              {[
                ["Supported", attempt.critic.supported],
                ["Responsive", attempt.critic.responsive],
                ["Answerable", attempt.critic.answerable],
              ].map(([label, pass]) => (
                <span key={String(label)} className={pass ? "pass" : "fail"}>
                  {pass ? <Check size={12} /> : <X size={12} />}
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}
        {attempt.feedback && (
          <div className="al-feedback">
            <b>Next correction</b>
            <p>{attempt.feedback}</p>
          </div>
        )}
        <div className="al-trace-meta">
          <span>{number(attempt.usage?.calls)} calls</span>
          <span>
            {attempt.usage?.known
              ? number(attempt.usage.total_tokens)
              : "Unknown"}{" "}
            tokens
          </span>
        </div>
      </div>
    </details>
  );
}

export function ResultInspector({
  result,
  compact = false,
  provider,
}: {
  result: AnswerResult;
  compact?: boolean;
  provider?: AnswerProviderMetadata;
}) {
  const [tab, setTab] = useState<"answer" | "trace" | "raw">("answer");
  useEffect(() => setTab("answer"), [result.id]);
  const error =
    typeof result.error === "string" ? result.error : result.error?.message;
  return (
    <section
      className={`al-inspector ${compact ? "al-compact" : ""}`}
      aria-label="Answer result"
    >
      <div className="al-result-heading">
        <Status result={result} />
        <button
          className="al-icon-button"
          title="Download run JSON"
          aria-label="Download run JSON"
          onClick={() => downloadJson(result, `answer-${result.id}.json`)}
        >
          <ArrowDownToLine size={16} />
        </button>
      </div>
      {!compact && <h3 className="al-result-question">{result.question}</h3>}
      <div className="al-run-measures">
        <div>
          <span>End-to-end</span>
          <b>{duration(result.latency_ms)}</b>
        </div>
        <div>
          <span>Model calls</span>
          <b>{number(result.usage.calls)}</b>
        </div>
        <div>
          <span>Tokens</span>
          <b>
            {result.usage.known ? number(result.usage.total_tokens) : "Unknown"}
          </b>
        </div>
        <div>
          <span>Cache</span>
          <b>{human(result.cache.status)}</b>
        </div>
      </div>
      <RunAccounting result={result} provider={provider} />
      <div className="al-tabs" role="tablist" aria-label="Result details">
        {(["answer", "trace", "raw"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            aria-controls={`result-${result.id}-${t}`}
            onClick={() => setTab(t)}
          >
            {t === "answer" ? (
              "Answer & sources"
            ) : t === "trace" ? (
              <>
                Correction trace <span>{result.attempts.length}</span>
              </>
            ) : (
              "Raw JSON"
            )}
          </button>
        ))}
      </div>
      <div
        className="al-result-content"
        id={`result-${result.id}-${tab}`}
        role="tabpanel"
      >
        {tab === "answer" && (
          <>
            {error && <div className="al-error">{error}</div>}
            {result.abstained ? (
              <div className="al-abstained">
                <BookOpen size={21} />
                <div>
                  <b>The model abstained.</b>
                  <p>
                    It did not find enough evidence to answer. Reference grading
                    is needed to determine whether this was correct.
                  </p>
                </div>
              </div>
            ) : result.data != null ? (
              <pre className="al-json">
                {JSON.stringify(result.data, null, 2)}
              </pre>
            ) : (
              <p className="al-answer-text">
                {result.answer || "No usable answer was returned."}
              </p>
            )}
            <div className="al-validation">
              <div>
                <span className="al-overline">Validation score</span>
                <b>{percent(result.quality.score)}</b>
              </div>
              <div className="al-score-track">
                <span
                  style={{
                    width: `${Math.max(0, Math.min(1, result.quality.score || 0)) * 100}%`,
                  }}
                />
              </div>
              <small>
                Share of runtime checks passed. Not a probability of
                correctness.
              </small>
            </div>
            <div className="al-evidence-heading">
              <FileText size={15} />
              <h4>Cited evidence</h4>
              <span>{result.citations.length}</span>
            </div>
            {result.citations.length ? (
              result.citations.map((citation, i) => (
                <figure
                  className="al-citation"
                  key={`${citation.source_id}-${i}`}
                >
                  <figcaption>
                    <span>{i + 1}</span>
                    {result.sources?.find(
                      (source) => source.id === citation.source_id,
                    )?.title || citation.source_id}
                  </figcaption>
                  <blockquote>{citation.quote}</blockquote>
                </figure>
              ))
            ) : (
              <p className="al-muted">No citations were returned.</p>
            )}
            {result.retrieval && (
              <details className="al-retrieval">
                <summary>
                  Retrieved sources{" "}
                  <span>{human(result.retrieval.method)}</span>
                  <ChevronDown size={14} />
                </summary>
                {result.retrieval.selected.map((source, i) => (
                  <div key={`${source.source_id}-${i}`}>
                    <b>{source.title || source.source_id}</b>
                    <small>Retrieval score {number(source.score, 3)}</small>
                    <p>{source.text}</p>
                  </div>
                ))}
              </details>
            )}
          </>
        )}
        {tab === "trace" && (
          <div className="al-attempts">
            {result.attempts.length ? (
              result.attempts.map((attempt, i) => (
                <AttemptPanel
                  key={i}
                  attempt={attempt}
                  selected={
                    result.final_attempt_index != null
                      ? attempt.index === result.final_attempt_index
                      : i === result.attempts.length - 1
                  }
                />
              ))
            ) : (
              <div className="al-cache-note">
                <Database size={22} />
                <b>
                  {result.cache.status.includes("hit") ||
                  result.cache.status === "exact"
                    ? "Served from the response cache"
                    : "No generation attempts"}
                </b>
                <p>
                  Inspect the raw record for cache provenance and recorded
                  checks.
                </p>
              </div>
            )}
          </div>
        )}
        {tab === "raw" && (
          <pre className="al-json al-raw">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
      <footer className="al-result-footer">
        <span>{result.model}</span>
        <span>{date(result.created_at)}</span>
      </footer>
    </section>
  );
}
