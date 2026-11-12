import type { SupportTicketDetail } from "./supportTypes";

export function knowledgeIsStale(
  ticket: SupportTicketDetail,
  revision?: string,
) {
  return (
    !!ticket.result &&
    (ticket.result.stale ||
      (!!revision && ticket.result.knowledge_revision !== revision))
  );
}

/** Mirror the server's visible review requirements; the server remains authoritative. */
export function draftCanBeApproved(
  ticket: SupportTicketDetail,
  reply: string,
  revision?: string,
) {
  const result = ticket.result;
  return (
    ticket.status === "review" &&
    !!result &&
    !knowledgeIsStale(ticket, revision) &&
    !result.approval_blockers?.length &&
    result.answer_run.status === "accepted" &&
    result.data?.next_action === "reply" &&
    !!reply.trim() &&
    result.answer_run.citations.some((citation) =>
      result.sources.some(
        (source) =>
          source.source_id === citation.source_id &&
          source.source_kind === "knowledge" &&
          !!source.document_id,
      ),
    )
  );
}
