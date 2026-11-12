import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  FilePlus2,
  FileText,
  Inbox,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import type {
  SupportConfig,
  SupportDemo,
  SupportDocument,
  SupportTicket,
  SupportTicketDetail,
} from "./supportTypes";
import {
  filePayload,
  loadSupport,
  SUPPORT_RECORDED,
  supportApi,
  supportDownload,
  supportPost,
} from "./supportApi";
import { SupportDialog, supportDate, TicketBadge } from "./SupportDeskShared";
import SupportDeskTicket from "./SupportDeskTicket";
import "./SupportDesk.css";

export default function SupportDesk() {
  const [view, setView] = useState<"queue" | "knowledge">("queue");
  const [config, setConfig] = useState<SupportConfig | null>(null);
  const [documents, setDocuments] = useState<SupportDocument[]>([]);
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [demo, setDemo] = useState<SupportDemo | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<SupportTicketDetail | null>(null);
  const [document, setDocument] = useState<SupportDocument | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newTicket, setNewTicket] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null),
    importRef = useRef<HTMLInputElement>(null);
  const selectionRef = useRef("");
  const refresh = useCallback(async () => {
    try {
      const data = await loadSupport();
      setConfig(data.config);
      setDocuments(data.documents);
      setTickets(data.tickets);
      setDemo(data.demo);
      setError("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The workspace could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  async function readTicket(id: string) {
    selectionRef.current = id;
    setSelectedId(id);
    setDetailLoading(true);
    try {
      const value = SUPPORT_RECORDED
        ? demo?.tickets.find((t) => t.id === id)
        : await supportApi<SupportTicketDetail>(
            `/tickets/${encodeURIComponent(id)}`,
          );
      if (selectionRef.current === id) {
        if (!value) throw new Error("This recorded ticket is not available.");
        setSelected(value);
      }
    } catch (e) {
      if (selectionRef.current === id) {
        setSelected(null);
        setError(
          e instanceof Error ? e.message : "The ticket could not be loaded.",
        );
      }
    } finally {
      if (selectionRef.current === id) setDetailLoading(false);
    }
  }
  const hasActiveJobs = tickets.some(
    (t) => t.status === "queued" || t.status === "processing",
  );
  useEffect(() => {
    if (SUPPORT_RECORDED) return;
    if (!hasActiveJobs) return;
    let cancelled = false;
    let polling = false;
    const timer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        if (selectionRef.current) {
          const value = await supportApi<SupportTicketDetail>(
            `/tickets/${selectionRef.current}`,
          );
          if (!cancelled && value.id === selectionRef.current)
            setSelected(value);
        }
      } catch {
        /* Collection refresh displays connection failures. */
      } finally {
        if (!cancelled) await refresh();
        polling = false;
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [hasActiveJobs, refresh]);
  async function action(name: string, operation: () => Promise<void>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The action could not be completed.",
      );
    } finally {
      setBusy("");
    }
  }
  async function process(ids: string[]) {
    await action("process", async () => {
      const failures: string[] = [];
      let queued = 0;
      for (const id of ids) {
        try {
          await supportPost(`/tickets/${id}/process`, {
            strategy: "adaptive",
            idempotency_key: crypto.randomUUID(),
          });
          queued++;
        } catch (e) {
          failures.push(
            e instanceof Error ? e.message : "A ticket could not be queued.",
          );
        }
      }
      await refresh();
      if (selectionRef.current) await readTicket(selectionRef.current);
      setChecked([]);
      setNotice(
        `${queued} ticket${queued === 1 ? "" : "s"} queued for processing.`,
      );
      if (failures.length) throw new Error(failures.join(" "));
    });
  }
  async function readDocument(id: string) {
    setView("knowledge");
    setDetailLoading(true);
    try {
      const value = SUPPORT_RECORDED
        ? demo?.documents.find((d) => d.id === id)
        : await supportApi<SupportDocument>(`/documents/${id}`);
      if (!value)
        throw new Error(
          "This historical document is not included in the recorded demo.",
        );
      setDocument(value);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The document could not be read.",
      );
    } finally {
      setDetailLoading(false);
    }
  }
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    await action("upload", async () => {
      let last: SupportDocument | undefined;
      for (const file of Array.from(files))
        last = await supportPost<SupportDocument>(
          "/documents",
          await filePayload(file, config?.max_upload_bytes || 5 * 1024 * 1024),
        );
      await refresh();
      if (last) await readDocument(last.id);
      setNotice(
        `${files.length} document${files.length === 1 ? "" : "s"} uploaded. New drafts use the updated knowledge.`,
      );
    });
    if (uploadRef.current) uploadRef.current.value = "";
  }
  async function importTickets(file?: File) {
    if (!file) return;
    await action("import", async () => {
      const result = await supportPost<{
        created_count: number;
        duplicate_count: number;
      }>(
        "/tickets/import",
        await filePayload(file, config?.max_ticket_import_bytes || 1024 * 1024),
      );
      await refresh();
      setNotice(
        `${result.created_count} tickets imported; ${result.duplicate_count} existing tickets skipped.`,
      );
    });
    if (importRef.current) importRef.current.value = "";
  }
  async function createTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    await action("create", async () => {
      const ticket = await supportPost<SupportTicketDetail>("/tickets", {
        title: fields.get("title"),
        body: fields.get("body"),
        external_id: fields.get("external_id") || undefined,
      });
      setNewTicket(false);
      await refresh();
      await readTicket(ticket.id);
      setNotice("Ticket added to the work queue.");
    });
  }
  async function review(
    decision: "approve" | "escalate",
    reply: string,
    note: string,
  ) {
    if (!selected) return;
    await action("review", async () => {
      const ticket = await supportPost<SupportTicketDetail>(
        `/tickets/${selected.id}/review`,
        { decision, reply, note, expected_revision: selected.revision },
      );
      setSelected(ticket);
      await refresh();
      setNotice(
        decision === "approve"
          ? "Draft approved. Export it when ready; nothing has been sent."
          : "Ticket escalated. The handoff is ready to export.",
      );
    });
  }
  async function exportTicket() {
    if (!selected) return;
    await action("export", async () => {
      if (SUPPORT_RECORDED) {
        supportDownload(
          { recorded_example: true, ticket: selected },
          `recorded-ticket-${selected.id}.json`,
        );
        return;
      }
      const result = await supportApi(`/tickets/${selected.id}/export`);
      supportDownload(
        result,
        `support-ticket-${selected.external_id || selected.id}.json`,
      );
      setNotice("Reviewed ticket exported as JSON.");
    });
  }
  const shown = tickets.filter(
    (t) =>
      (filter === "all" || t.status === filter) &&
      (t.title + " " + t.body + " " + (t.external_id || ""))
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const actionable = checked.filter(
    (id) =>
      !tickets.some(
        (t) =>
          t.id === id && (t.status === "queued" || t.status === "processing"),
      ),
  );
  const ready =
    !!config?.configured &&
    !!config.worker_available &&
    documents.some((d) => d.active);
  return (
    <div className="support-desk">
      <a className="sd-skip" href="#support-main">
        Skip to workspace
      </a>
      <aside className="sd-sidebar">
        <a className="sd-brand" href={import.meta.env.BASE_URL}>
          <span className="sd-mark">
            <CheckCheck size={22} />
          </span>
          <span>
            AgentProof<small>SUPPORT DESK</small>
          </span>
        </a>
        <div className="sd-nav-label">WORKSPACE</div>
        <nav aria-label="Support navigation">
          <button
            aria-current={view === "queue" ? "page" : undefined}
            onClick={() => setView("queue")}
          >
            <Inbox size={17} />
            Work queue{!loading && <span>{tickets.length}</span>}
          </button>
          <button
            aria-current={view === "knowledge" ? "page" : undefined}
            onClick={() => setView("knowledge")}
          >
            <BookOpen size={17} />
            Knowledge
            {!loading && (
              <span>{documents.filter((d) => d.active).length}</span>
            )}
          </button>
        </nav>
        <div className="sd-sidebar-bottom">
          <a href={`${import.meta.env.BASE_URL}?workspace=answers`}>
            Reliability experiments <ArrowUpRight size={14} />
          </a>
          <a
            href="https://github.com/HXRIkumar/AgentProof#run-it"
            target="_blank"
            rel="noreferrer"
          >
            Run locally <ArrowUpRight size={14} />
          </a>
          <div className="sd-local-note">
            <span className="sd-live-dot" />
            {SUPPORT_RECORDED
              ? "Recorded example workflow"
              : "Single-user local workspace"}
            <small>
              {SUPPORT_RECORDED
                ? "Example inputs. Actual saved model outputs."
                : "Review first. Export when ready."}
            </small>
          </div>
        </div>
      </aside>
      <main className="sd-main" id="support-main">
        <header className="sd-topbar">
          <div>
            <span>Support operations</span>
            <h1>{view === "queue" ? "Work queue" : "Knowledge"}</h1>
          </div>
          <div className="sd-header-actions">
            <a
              className="sd-mobile-lab"
              href={`${import.meta.env.BASE_URL}?workspace=answers`}
              aria-label="Reliability experiments"
            >
              Lab <ArrowUpRight size={12} />
            </a>
            <span
              className={`sd-connection ${config?.configured ? "ready" : ""}`}
            >
              <span />
              {SUPPORT_RECORDED
                ? "Read-only demo"
                : loading
                  ? "Connecting"
                  : config?.configured
                    ? "Model ready"
                    : "Model offline"}
            </span>
            <button
              className="sd-icon"
              aria-label="Refresh workspace"
              onClick={() =>
                action("refresh", async () => {
                  await refresh();
                  if (selectedId) await readTicket(selectedId);
                })
              }
              disabled={!!busy}
            >
              <RefreshCw
                size={16}
                className={busy === "refresh" ? "sd-spin" : ""}
              />
            </button>
          </div>
        </header>
        {SUPPORT_RECORDED && (
          <div className="sd-recorded-banner">
            <FileText size={15} />
            <span>
              {demo
                ? "Recorded example documents and tickets with actual model outputs. Uploads, processing and reviews are disabled."
                : "Read-only viewer. A saved workflow has not been added yet; the reliability experiments are available in the lab."}
            </span>
          </div>
        )}
        {!SUPPORT_RECORDED && !loading && !config?.configured && (
          <div className="sd-notice sd-setup">
            <span>
              Connect a model on the server to process tickets. Documents and
              tickets can be prepared now.
            </span>
          </div>
        )}
        {error && (
          <div className="sd-notice sd-error" role="alert">
            <XCircle size={16} />
            <span>{error}</span>
            <button
              className="sd-icon"
              aria-label="Dismiss error"
              onClick={() => setError("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
        {notice && (
          <div className="sd-notice sd-success" role="status">
            <Check size={16} />
            <span>{notice}</span>
            <button
              className="sd-icon"
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <X size={14} />
            </button>
          </div>
        )}
        <input
          ref={uploadRef}
          type="file"
          accept=".txt,.md,.markdown,.pdf"
          multiple
          hidden
          aria-label="Upload knowledge files"
          onChange={(e) => upload(e.target.files)}
        />
        <input
          ref={importRef}
          type="file"
          accept=".csv,.json"
          hidden
          aria-label="Import ticket file"
          onChange={(e) => importTickets(e.target.files?.[0])}
        />
        {loading ? (
          <div className="sd-loading">
            <LoaderCircle size={20} className="sd-spin" /> Loading workspace…
          </div>
        ) : view === "queue" ? (
          <div
            className={`sd-queue-layout ${selectedId ? "sd-mobile-selected" : ""}`}
          >
            <section className="sd-queue" aria-label="Ticket queue">
              <div className="sd-queue-controls">
                <div className="sd-queue-buttons">
                  <button
                    className="sd-button sd-primary"
                    disabled={SUPPORT_RECORDED || !!busy}
                    onClick={() => setNewTicket(true)}
                  >
                    <Plus size={15} />
                    New ticket
                  </button>
                  <button
                    className="sd-button"
                    disabled={SUPPORT_RECORDED || !!busy}
                    onClick={() => importRef.current?.click()}
                  >
                    <Upload size={14} />
                    Import
                  </button>
                </div>
                <label className="sd-search">
                  <Search size={15} />
                  <input
                    aria-label="Search tickets"
                    placeholder="Search tickets…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <div className="sd-queue-filter">
                  <select
                    aria-label="Filter tickets"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">All tickets</option>
                    <option value="open">Open</option>
                    <option value="review">Needs review</option>
                    <option value="queued">Queued</option>
                    <option value="processing">Processing</option>
                    <option value="approved">Approved</option>
                    <option value="escalated">Escalated</option>
                    <option value="failed">Failed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                  <span>{shown.length} shown</span>
                </div>
                {checked.length > 0 && (
                  <div className="sd-bulk">
                    <span>{checked.length} selected</span>
                    <button
                      disabled={
                        SUPPORT_RECORDED ||
                        !!busy ||
                        !ready ||
                        !actionable.length
                      }
                      onClick={() => process(actionable)}
                    >
                      Process selected
                    </button>
                    <button
                      aria-label="Clear ticket selection"
                      onClick={() => setChecked([])}
                    >
                      <X size={13} />
                    </button>
                  </div>
                )}
              </div>
              <div className="sd-ticket-list">
                {shown.map((ticket) => (
                  <div
                    className={`sd-queue-row ${selectedId === ticket.id ? "selected" : ""}`}
                    key={ticket.id}
                  >
                    <input
                      type="checkbox"
                      aria-label={`Select ${ticket.title}`}
                      checked={checked.includes(ticket.id)}
                      disabled={SUPPORT_RECORDED}
                      onChange={(e) =>
                        setChecked((old) =>
                          e.target.checked
                            ? [...old, ticket.id]
                            : old.filter((id) => id !== ticket.id),
                        )
                      }
                    />
                    <button
                      onClick={() => readTicket(ticket.id)}
                      aria-pressed={selectedId === ticket.id}
                    >
                      <div>
                        <span className="sd-queue-key">
                          {ticket.external_id || ticket.id.slice(0, 8)}
                        </span>
                        <time>{supportDate(ticket.updated_at)}</time>
                      </div>
                      <h3>{ticket.title}</h3>
                      <p>{ticket.body}</p>
                      <TicketBadge status={ticket.status} />
                    </button>
                  </div>
                ))}
                {!shown.length && (
                  <div className="sd-queue-empty">
                    <Inbox size={25} />
                    <b>
                      {tickets.length
                        ? "No matching tickets"
                        : SUPPORT_RECORDED
                          ? "No recorded tickets yet"
                          : "Your queue is clear"}
                    </b>
                    <p>
                      {tickets.length
                        ? "Try another search or status."
                        : SUPPORT_RECORDED
                          ? "Run SupportDesk locally to upload documents and prepare real support drafts."
                          : "Add a ticket or import a CSV / JSON file to begin."}
                    </p>
                  </div>
                )}
              </div>
            </section>
            <div className="sd-detail-area">
              {detailLoading ? (
                <div className="sd-loading">
                  <LoaderCircle size={20} className="sd-spin" /> Loading ticket…
                </div>
              ) : selected && selected.id === selectedId ? (
                <SupportDeskTicket
                  ticket={selected}
                  config={config}
                  recorded={SUPPORT_RECORDED}
                  busy={!!busy}
                  onBack={() => {
                    selectionRef.current = "";
                    setSelectedId("");
                    setSelected(null);
                  }}
                  onProcess={() => process([selected.id])}
                  onCancel={() =>
                    action("cancel", async () => {
                      if (selected.active_job) {
                        await supportPost(
                          `/jobs/${selected.active_job.id}/cancel`,
                          {},
                        );
                        await refresh();
                        await readTicket(selected.id);
                      }
                    })
                  }
                  onReview={review}
                  onExport={exportTicket}
                  onDocument={readDocument}
                />
              ) : (
                <div className="sd-work-start">
                  <div className="sd-start-symbol">
                    <Inbox size={38} strokeWidth={1.25} />
                  </div>
                  <span className="sd-small-label">
                    DOCUMENTS → DRAFT → REVIEW
                  </span>
                  <h2>
                    {SUPPORT_RECORDED && !demo
                      ? "No recorded workflow yet"
                      : "Support replies, grounded in your knowledge"}
                  </h2>
                  <p>
                    {SUPPORT_RECORDED && !demo
                      ? "A real saved workflow will appear here after the first end-to-end run. The reliability experiments remain available in the sidebar."
                      : tickets.length
                        ? "Choose a ticket to inspect its request, source-backed draft and review history."
                        : "Bring your support documents and incoming requests into one place. Generate cited drafts, then decide what is ready to share."}
                  </p>
                  {!tickets.length && !SUPPORT_RECORDED && (
                    <ol>
                      <li>
                        <b>1</b>
                        <div>
                          <strong>Add your knowledge</strong>
                          <span>
                            Upload product guides, policies or troubleshooting
                            notes.
                          </span>
                        </div>
                        <button
                          className="sd-button"
                          onClick={() => {
                            setView("knowledge");
                            uploadRef.current?.click();
                          }}
                        >
                          Upload documents
                        </button>
                      </li>
                      <li>
                        <b>2</b>
                        <div>
                          <strong>Bring in tickets</strong>
                          <span>
                            Create a request or import up to 50 CSV / JSON
                            records.
                          </span>
                        </div>
                        <button
                          className="sd-button"
                          onClick={() => setNewTicket(true)}
                        >
                          New ticket
                        </button>
                      </li>
                      <li>
                        <b>3</b>
                        <div>
                          <strong>Review before export</strong>
                          <span>
                            Read the cited passages, edit the reply and approve
                            or escalate.
                          </span>
                        </div>
                      </li>
                    </ol>
                  )}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div
            className={`sd-knowledge-layout ${document ? "sd-mobile-selected" : ""}`}
          >
            <section className="sd-documents" aria-label="Knowledge documents">
              <div className="sd-documents-head">
                <div>
                  <h2>Active documents</h2>
                  <p>TXT, Markdown or text-based PDF</p>
                </div>
                <button
                  className="sd-button sd-primary"
                  disabled={SUPPORT_RECORDED || !!busy}
                  onClick={() => uploadRef.current?.click()}
                >
                  <Upload size={15} />
                  Upload
                </button>
              </div>
              <p className="sd-doc-help">
                Changing a file creates a new version. Previous citations remain
                readable.
              </p>
              {documents
                .filter((d) => d.active)
                .map((doc) => (
                  <button
                    className={`sd-document-row ${document?.id === doc.id ? "selected" : ""}`}
                    key={doc.id}
                    onClick={() => readDocument(doc.id)}
                  >
                    <FileText size={19} />
                    <span>
                      <b>{doc.filename}</b>
                      <small>
                        Version {doc.version} · {doc.chunk_count} chunks
                        {doc.page_count ? ` · ${doc.page_count} pages` : ""}
                      </small>
                      <time>{supportDate(doc.created_at)}</time>
                    </span>
                  </button>
                ))}
              {!documents.some((d) => d.active) && (
                <div className="sd-queue-empty">
                  <FilePlus2 size={28} />
                  <b>No active knowledge</b>
                  <p>
                    Upload a document before processing tickets. Scanned images
                    and OCR are not supported.
                  </p>
                </div>
              )}
            </section>
            <section
              className="sd-document-content"
              aria-label="Document preview"
            >
              {detailLoading ? (
                <div className="sd-loading">
                  <LoaderCircle className="sd-spin" size={20} /> Reading
                  document…
                </div>
              ) : document ? (
                <>
                  <header>
                    <button
                      className="sd-back"
                      onClick={() => setDocument(null)}
                    >
                      <ArrowLeft size={15} />
                      Documents
                    </button>
                    <div>
                      <h2>{document.filename}</h2>
                      <span className="sd-badge">
                        Version {document.version} ·{" "}
                        {document.active ? "Active" : "Archived"}
                      </span>
                    </div>
                    {document.active && !SUPPORT_RECORDED && (
                      <button
                        className="sd-button"
                        disabled={!!busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Archive ${document.filename}? Existing ticket citations will remain readable.`,
                            )
                          )
                            action("archive", async () => {
                              await supportApi(`/documents/${document.id}`, {
                                method: "DELETE",
                              });
                              setDocument(null);
                              await refresh();
                              setNotice(
                                "Document archived. Regenerate any affected drafts before approval.",
                              );
                            });
                        }}
                      >
                        Archive document
                      </button>
                    )}
                  </header>
                  <div className="sd-document-text">
                    {document.text ? (
                      <pre>{document.text}</pre>
                    ) : document.pages?.length ? (
                      document.pages.map((page, i) => (
                        <article key={i}>
                          <b>Page {page.page}</b>
                          <pre>{page.text}</pre>
                        </article>
                      ))
                    ) : (
                      <p className="sd-muted">
                        Extracted text was not included in this recorded
                        preview. Ticket evidence still includes its cited
                        passages.
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <div className="sd-work-start">
                  <BookOpen size={36} strokeWidth={1.2} />
                  <h2>Knowledge is the source of every draft</h2>
                  <p>
                    Select a document to read its extracted text, or upload a
                    new version. Drafts retain their exact document snapshot.
                  </p>
                </div>
              )}
            </section>
          </div>
        )}
      </main>
      {newTicket && (
        <SupportDialog
          title="New support ticket"
          onClose={() => setNewTicket(false)}
        >
          <form onSubmit={createTicket} className="sd-ticket-form">
            <label className="sd-field">
              Title
              <input
                name="title"
                aria-label="Ticket title"
                autoFocus
                required
                maxLength={200}
                placeholder="What does the customer need help with?"
              />
            </label>
            <label className="sd-field">
              Request
              <textarea
                name="body"
                aria-label="Ticket request"
                required
                maxLength={20000}
                rows={7}
                placeholder="Include the customer's question and relevant context."
              />
            </label>
            <label className="sd-field">
              External ID <span className="sd-optional">optional</span>
              <input
                name="external_id"
                aria-label="External ticket ID"
                maxLength={200}
                placeholder="Your existing ticket reference"
              />
            </label>
            <p className="sd-muted">
              Import format: CSV columns title, body, external_id; or a JSON
              list with those fields. No customer system is connected.
            </p>
            <div className="sd-dialog-actions">
              <button
                type="button"
                className="sd-button"
                onClick={() => setNewTicket(false)}
              >
                Cancel
              </button>
              <button
                className="sd-button sd-primary"
                type="submit"
                disabled={!!busy}
              >
                {busy === "create" ? "Adding…" : "Add ticket"}
              </button>
            </div>
          </form>
        </SupportDialog>
      )}
    </div>
  );
}
