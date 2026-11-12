import type { AnswerResult } from "./answerTypes";

export type SupportConfig = {
  configured: boolean;
  model: string;
  critic_model: string;
  embedding_status: string;
  worker_available: boolean;
  knowledge_revision: string;
  max_upload_bytes: number;
  max_ticket_import_bytes?: number;
};
export type SupportDocument = {
  id: string;
  filename: string;
  title: string;
  version: number;
  content_sha256: string;
  created_at: string;
  active: boolean;
  page_count: number;
  chunk_count: number;
  text?: string;
  pages?: { page: number; text: string }[];
};
export type TicketStatus =
  | "open"
  | "queued"
  | "processing"
  | "review"
  | "approved"
  | "escalated"
  | "failed"
  | "cancelled";
export type SupportJob = {
  id: string;
  ticket_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested: boolean;
  error: string | null;
  progress?: string;
  strategy?: string;
  knowledge_revision?: string;
};
export type SupportSource = {
  source_id: string;
  source_kind: "knowledge" | "ticket";
  document_id: string | null;
  filename: string;
  title: string;
  version: number | null;
  page: number | null;
  chunk: number;
  text: string;
};
export type SupportData = {
  summary: string;
  category: "technical" | "account" | "billing" | "other";
  priority: "low" | "normal" | "high";
  next_action: "reply" | "clarify" | "escalate";
  draft_reply: string;
  follow_up_question: string;
};
export type SupportResult = {
  data: SupportData | null;
  answer_run: AnswerResult;
  sources: SupportSource[];
  knowledge_revision: string;
  stale: boolean;
  reasons: string[];
  approval_blockers?: string[];
  context?: { ticket_characters: number; used: number; omitted: number };
};
export type SupportTicket = {
  id: string;
  external_id: string | null;
  title: string;
  body: string;
  status: TicketStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  category: string | null;
  priority: string | null;
};
export type SupportTicketDetail = SupportTicket & {
  result: SupportResult | null;
  events: {
    id: string;
    type: string;
    at: string;
    message: string;
    job_id: string | null;
  }[];
  active_job: SupportJob | null;
  review: {
    decision: "approve" | "escalate";
    reply: string;
    note: string;
    reviewed_at: string;
    knowledge_revision: string;
    answer_run_id: string;
  } | null;
};
export type SupportDemo = {
  format: "agentproof-support-demo-v1";
  config: SupportConfig;
  documents: SupportDocument[];
  tickets: SupportTicketDetail[];
};
