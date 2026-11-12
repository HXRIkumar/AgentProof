from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Upload(Input):
    filename: str = Field(min_length=1, max_length=240)
    content_base64: str = Field(min_length=1, max_length=7_100_000)


class TicketInput(Input):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("title", "body", "external_id")
    @classmethod
    def nonempty(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank")
        return value.strip() if value is not None else None


class ProcessInput(Input):
    strategy: Literal["adaptive", "validated", "baseline"] = "adaptive"
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Idempotency key must not be blank")
        return value.strip()


class ReviewInput(Input):
    decision: Literal["approve", "escalate"]
    expected_revision: int = Field(ge=1)
    reply: str | None = Field(default=None, max_length=20000)
    note: str | None = Field(default=None, max_length=4000)
