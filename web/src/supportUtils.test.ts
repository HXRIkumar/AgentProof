import assert from "node:assert/strict";
import test from "node:test";
import { draftCanBeApproved, knowledgeIsStale } from "./supportUtils.ts";
import type { SupportTicketDetail } from "./supportTypes.ts";

function reviewTicket() {
  return {
    status: "review",
    result: {
      knowledge_revision: "kb-1",
      stale: false,
      approval_blockers: [],
      data: { next_action: "reply" },
      answer_run: {
        status: "accepted",
        citations: [{ source_id: "policy-1", quote: "Read the policy." }],
      },
      sources: [
        {
          source_id: "policy-1",
          source_kind: "knowledge",
          document_id: "doc-1",
        },
      ],
    },
  } as unknown as SupportTicketDetail;
}

test("approval requires current knowledge, accepted output and a cited knowledge document", () => {
  const ticket = reviewTicket();
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), true);
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-2"), false);
  assert.equal(knowledgeIsStale(ticket, "kb-2"), true);
  ticket.result!.stale = true;
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
});

test("ticket context alone cannot authorize a policy-backed reply", () => {
  const ticket = reviewTicket();
  ticket.result!.sources[0].source_kind = "ticket";
  ticket.result!.sources[0].document_id = null;
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
});

test("server approval blockers and incomplete drafts remain blocked in the UI", () => {
  const ticket = reviewTicket();
  assert.equal(draftCanBeApproved(ticket, "   ", "kb-1"), false);
  ticket.result!.approval_blockers = ["Financial action requires a human."];
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
  ticket.result!.approval_blockers = [];
  ticket.result!.data!.next_action = "clarify";
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
  ticket.result!.data!.next_action = "reply";
  ticket.result!.answer_run.status = "failed";
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
  ticket.result!.answer_run.status = "accepted";
  ticket.status = "approved";
  assert.equal(draftCanBeApproved(ticket, "Reviewed reply", "kb-1"), false);
});
