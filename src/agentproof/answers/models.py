"""Public input contract. Reference answers deliberately have no place in this model."""

import json
import math
import re
from typing import Any, Literal

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=100, pattern=r"^[\w.:-]+$")
    title: str = Field(default="Source", min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=24000)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
    question: str = Field(min_length=1, max_length=2000)
    sources: list[Source] = Field(min_length=1, max_length=20)
    task: Literal["qa", "extraction"] = "qa"
    output_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    strategy: Literal["baseline", "validated", "adaptive"] = "adaptive"
    max_attempts: int = Field(default=3, ge=1, le=3)
    use_cache: bool = True
    namespace: str = Field(default="workspace", min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded_inputs(self):
        if not self.question.strip() or any(not x.text.strip() for x in self.sources):
            raise ValueError("Question and sources must contain text")
        if len({x.id for x in self.sources}) != len(self.sources):
            raise ValueError("Source IDs must be unique")
        if sum(len(x.text) for x in self.sources) > 80000:
            raise ValueError("Sources exceed the 80,000-character total limit")
        if self.task == "extraction" and self.output_schema is None:
            raise ValueError("Extraction requires a JSON Schema")
        if self.output_schema is not None:
            encoded = json.dumps(self.output_schema, allow_nan=False)
            if len(encoded) > 12000:
                raise ValueError("Schema exceeds 12,000 characters")

            # No external retrieval or remote vocabulary. Bounded schema depth also
            # prevents deeply recursive validation work from a user-supplied schema.
            def inspect(value, depth=0):
                if depth > 16:
                    raise ValueError("Schema nesting exceeds 16 levels")
                if isinstance(value, dict):
                    if any(k in value for k in ("$ref", "$dynamicRef", "$recursiveRef")):
                        raise ValueError("Schema references are not supported")
                    for key, item in value.items():
                        if key == "pattern" or key == "patternProperties":
                            raise ValueError("Regex schemas are not supported in the local service")
                        inspect(item, depth + 1)
                elif isinstance(value, list):
                    for item in value:
                        inspect(item, depth + 1)

            inspect(self.output_schema)
            try:
                Draft202012Validator.check_schema(self.output_schema)
            except SchemaError:
                raise ValueError("Invalid JSON Schema") from None
        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=3000)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(default="", max_length=5000)
    data: Any = None
    abstained: bool = False
    citations: list[Citation] = Field(default_factory=list, max_length=20)


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    responsive: bool
    answerable: bool
    feedback: str = Field(min_length=1, max_length=1600)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_json(text: str):
    """Accept one JSON value; fenced JSON is a common harmless transport wrapper."""
    text = text.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("Nonfinite JSON number")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON number")
        return number

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float
    )
