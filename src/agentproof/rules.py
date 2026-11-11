"""A deliberately ordinary policy function: no inference, oracle labels or notes."""

from pydantic import BaseModel, ConfigDict, Field

from .models import Order, Proposal


class ObservedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: Order | None
    authenticated_customer: str
    requested_cents: int = Field(strict=True)
    policy_version: str
    retrieved_note: str = ""


def decide(observation: dict) -> Proposal:
    facts = ObservedFacts.model_validate(observation)
    order = facts.order
    if order is None:
        action, reason = "escalate", "Order evidence is missing."
    elif (
        order.customer_id != facts.authenticated_customer
        or order.status != "delivered"
        or order.age_days > 30
        or facts.requested_cents <= 0
        or facts.requested_cents > order.paid_cents - order.refunded_cents
    ):
        action, reason = "reject", "The structured facts do not meet the refund policy."
    else:
        action, reason = "refund", "The structured facts meet the refund policy."
    return Proposal(
        action=action,
        order_id=order.id if order else "unknown",
        customer_id=facts.authenticated_customer,
        amount_cents=facts.requested_cents if action == "refund" else 0,
        policy_version=facts.policy_version,
        reason=reason,
    )


class RulesProvider:
    model = "rules-only-refund-policy-v1"
    is_live = False

    def propose(self, observation, feedback=None, fault="none", attempt=0):
        # The runner excludes model-specific failure fixtures before calling this
        # adapter. No case IDs, expected labels, feedback or fault labels guide it.
        return decide(observation).model_dump_json(), 0
