import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  Clock3,
  Download,
  FileText,
  Flag,
  LoaderCircle,
  MessageSquare,
  Play,
  Square,
  Workflow,
} from "lucide-react";
import type { SupportConfig, SupportTicketDetail } from "./supportTypes";
import { SupportDialog, supportDate, TicketBadge } from "./SupportDeskShared";
import { duration, number, usd } from "./answerUtils";
import { draftCanBeApproved, knowledgeIsStale } from "./supportUtils";

export default function SupportDeskTicket({
  ticket,
  config,
  recorded,
  busy,
  onBack,
  onProcess,
  onCancel,
  onReview,
  onExport,
  onDocument,
}: {
  ticket: SupportTicketDetail;
  config: SupportConfig | null;
  recorded: boolean;
  busy: boolean;
  onBack: () => void;
  onProcess: () => void;
  onCancel: () => void;
  onReview: (
    decision: "approve" | "escalate",
    reply: string,
    note: string,
  ) => Promise<void>;
  onExport: () => void;
  onDocument: (id: string) => void;
}) {
  const [tab, setTab] = useState<"draft" | "evidence" | "activity">("draft");
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [trace, setTrace] = useState(false);
  const result = ticket.result,
    data = result?.data,
    run = result?.answer_run;
  useEffect(() => {
    setReply(ticket.review?.reply || data?.draft_reply || "");
    setNote(ticket.review?.note || "");
  }, [ticket.id, run?.id, ticket.review?.reviewed_at]);
  useEffect(() => setTab("draft"), [ticket.id]);
  const active =
    ticket.active_job &&
    ["queued", "running"].includes(ticket.active_job.status)
      ? ticket.active_job
      : null;
  const stale = knowledgeIsStale(ticket, config?.knowledge_revision);
  const final = ticket.status === "approved" || ticket.status === "escalated";
  const canApprove =
    !recorded &&
    !busy &&
    !active &&
    draftCanBeApproved(ticket, reply, config?.knowledge_revision);
  const reason = stale
    ? "Knowledge changed. Regenerate this ticket before approval."
    : data?.next_action === "clarify"
      ? "The draft needs clarification. Add context to a handoff or regenerate after updating the knowledge."
      : data?.next_action === "escalate"
        ? "The draft recommends a human handoff."
        : run && run.status !== "accepted"
          ? "The model output did not pass its checks. Review the evidence and escalate or regenerate."
          : null;
  return (
    <section className="sd-ticket-detail" aria-label="Selected ticket">
      <header className="sd-ticket-head">
        <div>
          <button className="sd-back" onClick={onBack}>
            <ArrowLeft size={15} /> Work queue
          </button>
          <div className="sd-ticket-id">
            {ticket.external_id || ticket.id.slice(0, 8)} <span>·</span>{" "}
            {supportDate(ticket.created_at)}
          </div>
          <h2>{ticket.title}</h2>
          <div className="sd-ticket-tags">
            <TicketBadge status={ticket.status} />
            {ticket.category && <span>{ticket.category}</span>}
            {ticket.priority && <span>{ticket.priority} priority</span>}
          </div>
        </div>
        <div className="sd-ticket-actions">
          {final && (
            <button
              className="sd-button"
              onClick={onExport}
              disabled={!recorded && (busy || stale)}
              title={
                !recorded && stale
                  ? "Knowledge changed. Regenerate and review before export."
                  : undefined
              }
            >
              <Download size={15} /> {recorded ? "Download record" : "Export"}
            </button>
          )}
          <button
            className="sd-button sd-primary"
            disabled={
              recorded ||
              busy ||
              !!active ||
              !config?.configured ||
              !config?.worker_available
            }
            onClick={onProcess}
          >
            <Play size={14} />
            {run ? "Regenerate" : "Process ticket"}
          </button>
        </div>
      </header>
      <div className="sd-ticket-original">
        <div className="sd-small-label">
          <MessageSquare size={13} /> Incoming request
        </div>
        <p>{ticket.body}</p>
      </div>
      {active && (
        <div className="sd-job" role="status">
          <LoaderCircle size={16} className="sd-spin" />
          <div>
            <b>
              {active.status === "queued"
                ? "Waiting in the processing queue"
                : "Preparing a sourced draft"}
            </b>
            <p>
              {active.cancel_requested
                ? "Cancellation requested. The current bounded inference will finish before this job stops."
                : active.progress ||
                  "The worker retains the result and its evidence for review."}
            </p>
          </div>
          <button
            className="sd-button"
            disabled={recorded || busy || active.cancel_requested}
            onClick={onCancel}
          >
            <Square size={12} />
            {active.cancel_requested ? "Stopping…" : "Cancel job"}
          </button>
        </div>
      )}
      {stale && (
        <div className="sd-notice sd-warning">
          <Clock3 size={16} />
          <span>
            This draft uses an older knowledge snapshot. Its citations remain
            readable; regenerate before approval.
          </span>
        </div>
      )}
      <nav className="sd-detail-tabs" aria-label="Ticket detail tabs">
        {(["draft", "evidence", "activity"] as const).map((t) => (
          <button
            key={t}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
            {t === "evidence" && run && <span>{run.citations.length}</span>}
          </button>
        ))}
        {run && (
          <button className="sd-trace-link" onClick={() => setTrace(true)}>
            <Workflow size={14} /> Model trace
          </button>
        )}
      </nav>
      <div className="sd-ticket-body">
        {tab === "draft" && (
          <>
            {!result && !active && (
              <div className="sd-draft-empty">
                <FileText size={30} strokeWidth={1.3} />
                <h3>
                  {ticket.review?.decision === "escalate"
                    ? "Escalated for human follow-up"
                    : ticket.status === "failed"
                      ? "Processing did not finish"
                      : "Ready for a first draft"}
                </h3>
                <p>
                  {ticket.review
                    ? ticket.review.note ||
                      "This ticket was handed off without a generated reply. Export its record for the next reviewer."
                    : "Process this ticket against the active knowledge. The draft and its source citations will appear here for your review."}
                </p>
              </div>
            )}
            {result && (
              <>
                <div className="sd-draft-summary">
                  <div className="sd-small-label">Draft assessment</div>
                  <p>
                    {data?.summary ||
                      "No structured summary was returned. Inspect the model trace for the actual response."}
                  </p>
                  {data && (
                    <div className="sd-classifications">
                      <span>{data.category}</span>
                      <span>{data.priority} priority</span>
                      <span>Next: {data.next_action}</span>
                    </div>
                  )}
                </div>
                {reason && (
                  <div className="sd-notice sd-warning">
                    <Flag size={15} />
                    <span>{reason}</span>
                  </div>
                )}
                {!!result.reasons?.length && (
                  <ul className="sd-reasons">
                    {result.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
                {data?.follow_up_question && (
                  <div className="sd-followup">
                    <b>Missing information</b>
                    <p>{data.follow_up_question}</p>
                  </div>
                )}
                <label className="sd-field">
                  {ticket.review?.decision === "escalate"
                    ? "Draft retained for handoff · not approved"
                    : final
                      ? "Reviewed reply"
                      : "Reply for review"}
                  <textarea
                    aria-label="Reply for review"
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    disabled={recorded || final || !!active}
                    placeholder="A model-generated reply will appear here when supported by the documents."
                    rows={9}
                  />
                </label>
                {ticket.review && (
                  <div className="sd-review-record">
                    <Check size={14} />
                    <span>
                      {ticket.review.decision === "approve"
                        ? "Approved by the reviewer"
                        : "Escalated for human follow-up"}{" "}
                      · {supportDate(ticket.review.reviewed_at)}
                    </span>
                  </div>
                )}
                {!final && (
                  <label className="sd-field">
                    Review or handoff note{" "}
                    <span className="sd-optional">optional</span>
                    <textarea
                      aria-label="Review note"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      disabled={recorded || !!active}
                      placeholder="What should the next reviewer know?"
                      rows={3}
                    />
                  </label>
                )}
                {!final && (
                  <div className="sd-review-actions">
                    <p>
                      Approval saves a reviewed response. Nothing is sent to the
                      customer.
                    </p>
                    <div>
                      <button
                        className="sd-button"
                        disabled={recorded || busy || !!active}
                        onClick={() => onReview("escalate", reply, note)}
                      >
                        <Flag size={14} /> Escalate
                      </button>
                      <button
                        className="sd-button sd-primary"
                        disabled={!canApprove}
                        onClick={() => onReview("approve", reply, note)}
                      >
                        <Check size={15} /> Approve draft
                      </button>
                    </div>
                  </div>
                )}
                {final && ticket.review?.note && (
                  <div className="sd-followup">
                    <b>Review note</b>
                    <p>{ticket.review.note}</p>
                  </div>
                )}
              </>
            )}
            {!result &&
              !active &&
              ["failed", "cancelled"].includes(ticket.status) && (
                <div className="sd-review-actions">
                  <p>
                    A human handoff can retain this ticket without claiming a
                    generated reply.
                  </p>
                  <button
                    className="sd-button"
                    disabled={recorded || busy}
                    onClick={() => onReview("escalate", "", note)}
                  >
                    <Flag size={14} /> Escalate ticket
                  </button>
                </div>
              )}
          </>
        )}
        {tab === "evidence" && (
          <>
            {run?.status === "failed" && (
              <div className="sd-notice sd-warning">
                <Flag size={15} />
                <span>
                  This result did not pass runtime validation. Listed quotations
                  are the model's actual output; check the source passages and
                  model trace before using them.
                </span>
              </div>
            )}
            {run?.citations.length ? (
              <>
                <div className="sd-section-heading">
                  <h3>Cited evidence</h3>
                  <p>
                    Knowledge citations retain their document version. Ticket
                    excerpts identify customer context, not policy evidence.
                  </p>
                </div>
                {run.citations.map((citation, i) => {
                  const source = result?.sources.find(
                    (s) => s.source_id === citation.source_id,
                  );
                  return (
                    <article
                      className="sd-source"
                      key={`${citation.source_id}-${i}`}
                    >
                      <div className="sd-source-head">
                        <span className="sd-source-number">{i + 1}</span>
                        <div>
                          <b>{source?.filename || citation.source_id}</b>
                          <small>
                            {source?.source_kind === "ticket"
                              ? "Incoming ticket excerpt"
                              : source
                                ? `Version ${source.version}${source.page ? ` · page ${source.page}` : ""} · chunk ${source.chunk}`
                                : "Source mapping unavailable"}
                          </small>
                        </div>
                        {source?.document_id && (
                          <button
                            className="sd-icon"
                            aria-label={`Read ${source.filename} version ${source.version}`}
                            onClick={() =>
                              source.document_id &&
                              onDocument(source.document_id)
                            }
                          >
                            <ArrowUpRight size={16} />
                          </button>
                        )}
                      </div>
                      <blockquote>{citation.quote}</blockquote>
                      {source && (
                        <details>
                          <summary>
                            Show source passage <ChevronDown size={13} />
                          </summary>
                          <p>{source.text}</p>
                        </details>
                      )}
                    </article>
                  );
                })}
              </>
            ) : (
              <div className="sd-draft-empty">
                <FileText size={27} />
                <h3>No cited evidence yet</h3>
                <p>
                  Process the ticket to retrieve passages from the active
                  knowledge.
                </p>
              </div>
            )}
          </>
        )}
        {tab === "activity" && (
          <>
            <div className="sd-section-heading">
              <h3>Ticket activity</h3>
              <p>Processing and review events recorded for this ticket.</p>
            </div>
            {ticket.events.length ? (
              <ol className="sd-events">
                {ticket.events.map((event) => (
                  <li key={event.id}>
                    <span className="sd-event-dot" />
                    <div>
                      <b>{event.message || event.type.replaceAll("_", " ")}</b>
                      <time>{supportDate(event.at)}</time>
                      {event.job_id && (
                        <small>Job {event.job_id.slice(0, 8)}</small>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="sd-muted">No events recorded.</p>
            )}
          </>
        )}
      </div>
      {trace && run && (
        <SupportDialog title="Model trace" onClose={() => setTrace(false)}>
          <div className="sd-trace-metrics">
            <div>
              <span>Runtime status</span>
              <b>{run.status}</b>
            </div>
            <div>
              <span>End-to-end</span>
              <b>{duration(run.latency_ms)}</b>
            </div>
            <div>
              <span>Calls / tokens</span>
              <b>
                {run.usage.calls} /{" "}
                {run.usage.known ? number(run.usage.total_tokens) : "Unknown"}
              </b>
            </div>
            <div>
              <span>API estimate</span>
              <b>
                {run.usage.cost_known
                  ? usd(run.usage.estimated_cost_usd)
                  : run.generator_provider === "local" &&
                      run.critic_provider === "local"
                    ? "No API charge"
                    : "Unrecorded"}
              </b>
            </div>
          </div>
          <p className="sd-muted">
            Checks describe runtime validation, not a probability of
            correctness. API costs are estimates; local compute is not costed.
          </p>
          <div className="sd-trace-attempts">
            {run.attempts.map((attempt) => (
              <details key={attempt.index}>
                <summary>
                  <span>Attempt {attempt.index}</span>
                  <small>
                    {attempt.checks.filter((c) => c.passed).length}/
                    {attempt.checks.length} checks
                  </small>
                </summary>
                <p className="sd-muted">
                  {attempt.generation?.model || run.model}
                  {attempt.route === "critic_escalation"
                    ? " · escalated generation"
                    : ""}
                </p>
                <pre>
                  {JSON.stringify(attempt.data ?? attempt.answer, null, 2)}
                </pre>
                <ul>
                  {attempt.checks.map((c, i) => (
                    <li
                      key={i}
                      className={c.passed ? "sd-check-pass" : "sd-check-fail"}
                    >
                      {c.passed ? "Pass" : "Fail"} ·{" "}
                      {c.name.replaceAll("_", " ")}
                      <p>{c.detail}</p>
                    </li>
                  ))}
                </ul>
                {attempt.critic?.feedback && <p>{attempt.critic.feedback}</p>}
              </details>
            ))}
          </div>
          <details className="sd-raw">
            <summary>Raw answer record</summary>
            <pre>{JSON.stringify(run, null, 2)}</pre>
          </details>
        </SupportDialog>
      )}
    </section>
  );
}
