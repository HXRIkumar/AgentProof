from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Order(StrictModel):
    id: str = "ORD-1042"
    customer_id: str = "CUS-17"
    age_days: int = Field(default=12, ge=0, strict=True)
    status: Literal["delivered", "processing", "cancelled"] = "delivered"
    paid_cents: int = Field(default=4900, ge=0, strict=True)
    refunded_cents: int = Field(default=0, ge=0, strict=True)


class Proposal(StrictModel):
    action: Literal["refund", "reject", "escalate"]
    order_id: str
    customer_id: str
    amount_cents: int = Field(ge=0, le=1_000_000, strict=True)
    policy_version: str
    reason: str = Field(min_length=1, max_length=1000)


class Scenario(StrictModel):
    id: str
    name: str
    category: str
    description: str
    difficulty: str = "standard"
    order: Order | None = Field(default_factory=Order)
    authenticated_customer: str = "CUS-17"
    requested_cents: int = Field(default=4900, le=1_000_000, strict=True)
    fault: Literal[
        "none",
        "read_timeout",
        "read_outage",
        "commit_timeout",
        "duplicate",
        "injection",
        "over_amount",
        "stale_policy",
        "malformed",
        "wrong_order",
        "model_outage",
    ] = "none"
    expected_outcome: Literal["refunded", "rejected", "escalated", "approval_required"] = "refunded"
    current_policy: str = "refund-v1"
    observed_policy: str = "refund-v1"
    untrusted_note: str = ""


class ExperimentRequest(StrictModel):
    name: str | None = Field(default=None, max_length=100)
    provider: Literal["scripted", "openai"] = "scripted"
    scenario_ids: list[str] | None = Field(default=None, max_length=100)
    scenarios: list[Scenario] | None = Field(default=None, max_length=100)
    repeats: int = Field(default=1, ge=1, le=5)


class ApprovalRequest(StrictModel):
    approved: bool


class ComparisonRequest(StrictModel):
    reference_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
