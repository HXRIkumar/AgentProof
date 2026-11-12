"""Bounded OpenAI-compatible inference, including actual per-call accounting."""

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import httpx

from .hosted_budget import (
    BASE_URL as OPENAI_BASE_URL,
)
from .hosted_budget import (
    MAX_BUDGET_NANOUSD,
    PRICING,
    BudgetError,
    BudgetLedger,
    load_openai_key,
)
from .hosted_budget import (
    MODEL as OPENAI_MODEL,
)
from .models import parse_json


@dataclass(frozen=True)
class ModelResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float = 0.0
    finish_reason: str | None = None
    usage_known: bool = False
    request_hash: str = ""
    error: str | None = None
    preparation_latency_ms: float = 0.0
    model: str | None = None
    request_sent: bool = True
    billing: dict | None = None
    reasoning_tokens: int | None = None
    blocked_reason: str | None = None

    def for_request(self, fingerprint: str):
        return replace(self, request_hash=fingerprint)


class OpenAIAdapter:
    def __init__(
        self,
        *,
        base_url=None,
        model=None,
        api_key=None,
        timeout=None,
        max_tokens=None,
        disable_thinking=None,
        critic_model=None,
        critic_max_tokens=None,
        critic_disable_thinking=None,
        critic_base_url=None,
        critic_api_key=None,
        enable_paid=None,
        openai_reasoning_effort=None,
        budget_ledger=None,
        hosted_key_loader=None,
        client=None,
    ):
        self.base_url = (
            os.getenv("ANSWER_LAB_BASE_URL", "") if base_url is None else base_url
        ).rstrip("/")
        self.model = os.getenv("ANSWER_LAB_MODEL", "") if model is None else model
        self.api_key = api_key if api_key is not None else os.getenv("ANSWER_LAB_API_KEY", "")
        self.critic_base_url = (
            os.getenv("ANSWER_LAB_CRITIC_BASE_URL", self.base_url)
            if critic_base_url is None
            else critic_base_url
        ).rstrip("/")
        self.critic_api_key = (
            os.getenv("ANSWER_LAB_CRITIC_API_KEY", self.api_key)
            if critic_api_key is None
            else critic_api_key
        )
        self.enable_paid = (
            os.getenv("ANSWER_LAB_ENABLE_PAID", "") == "1"
            if enable_paid is None
            else enable_paid is True
        )
        self.openai_reasoning_effort = (
            os.getenv("ANSWER_LAB_OPENAI_REASONING_EFFORT", "low")
            if openai_reasoning_effort is None
            else openai_reasoning_effort
        )
        if self.openai_reasoning_effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError("Unsupported hosted reasoning effort")
        self._budget = budget_ledger
        self._hosted_key_loader = hosted_key_loader or load_openai_key
        self.timeout = float(os.getenv("ANSWER_LAB_TIMEOUT", "90") if timeout is None else timeout)
        self.max_tokens = int(
            os.getenv("ANSWER_LAB_MAX_TOKENS", "768") if max_tokens is None else max_tokens
        )
        self.disable_thinking = (
            disable_thinking
            if disable_thinking is not None
            else os.getenv("ANSWER_LAB_DISABLE_THINKING", "false").lower() == "true"
        )
        self.revision = os.getenv("ANSWER_LAB_MODEL_REVISION", "unrecorded")
        self.critic_model = (
            os.getenv("ANSWER_LAB_CRITIC_MODEL") or self.model
            if critic_model is None
            else critic_model
        )
        self.critic_max_tokens = int(
            os.getenv("ANSWER_LAB_CRITIC_MAX_TOKENS", str(self.max_tokens))
            if critic_max_tokens is None
            else critic_max_tokens
        )
        critic_thinking_env = os.getenv("ANSWER_LAB_CRITIC_DISABLE_THINKING")
        self._critic_thinking_override = (
            critic_disable_thinking is not None or critic_thinking_env is not None
        )
        self.critic_disable_thinking = (
            critic_disable_thinking
            if critic_disable_thinking is not None
            else critic_thinking_env.lower() == "true"
            if critic_thinking_env is not None
            else self.disable_thinking
        )
        self.critic_revision = os.getenv(
            "ANSWER_LAB_CRITIC_MODEL_REVISION",
            self.revision if self.critic_model == self.model else "unrecorded",
        )
        self._client = client
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 180:
            raise ValueError("Inference timeout must be between 1 and 180 seconds")
        if not 64 <= self.max_tokens <= 4096:
            raise ValueError("Inference output limit must be between 64 and 4096 tokens")
        if not self.critic_model and self.model:
            raise ValueError("Critic model must not be empty")
        if not 64 <= self.critic_max_tokens <= 4096:
            raise ValueError("Critic output limit must be between 64 and 4096 tokens")
        self._generator_kind = self._endpoint_kind(self.base_url)
        self._critic_kind = self._endpoint_kind(self.critic_base_url)
        if self._generator_kind == "openai":
            self.revision = OPENAI_MODEL
        if self._critic_kind == "openai":
            self.critic_revision = OPENAI_MODEL
        for kind, selected_model in (
            (self._generator_kind, self.model),
            (self._critic_kind, self.critic_model),
        ):
            if kind == "openai" and selected_model != OPENAI_MODEL:
                raise ValueError("Hosted requests require the explicitly priced mini snapshot")

    @staticmethod
    def _endpoint_kind(url):
        if not url:
            return "unconfigured"
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid inference endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Inference endpoint must not contain credentials or query data")
        if url == OPENAI_BASE_URL:
            return "openai"
        if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return "local"
        raise ValueError("Only loopback inference or the allowlisted OpenAI endpoint is supported")

    def _ledger(self):
        if self._budget is None:
            self._budget = BudgetLedger()
        return self._budget

    def budget_status(self):
        """Secret-free shared ledger inspection. Does not read a key or send any request."""
        return self._ledger().snapshot()

    @property
    def configured(self):
        return bool(
            self.base_url and self.model and (self._generator_kind != "openai" or self.enable_paid)
        )

    @property
    def has_distinct_critic(self):
        return bool(
            self.critic_base_url
            and self.critic_model
            and (self.critic_base_url, self.critic_model) != (self.base_url, self.model)
        )

    def configuration(self):
        return {
            "model": self.model,
            "revision": self.revision,
            "endpoint_hash": hashlib.sha256(self.base_url.encode()).hexdigest(),
            "temperature": None if self._generator_kind == "openai" else 0,
            "max_tokens": self.max_tokens,
            "disable_thinking": self.disable_thinking,
            "critic_model": self.critic_model,
            "critic_revision": self.critic_revision,
            "critic_max_tokens": self.critic_max_tokens,
            "critic_disable_thinking": self.critic_disable_thinking,
            "critic_thinking_override": self._critic_thinking_override,
            "critic_temperature": None if self._critic_kind == "openai" else 0,
            "critic_endpoint_hash": hashlib.sha256(self.critic_base_url.encode()).hexdigest(),
            "generator_provider": self._generator_kind,
            "critic_provider": self._critic_kind,
            "has_distinct_critic": self.has_distinct_critic,
            "hosted": {
                "enabled": self.enable_paid,
                "reasoning_effort": self.openai_reasoning_effort,
                "temperature": None,
                "response_format": "json_object",
                "n": 1,
                "max_completion_tokens_includes_reasoning": True,
                "pricing": PRICING,
                "maximum_guard_usd": MAX_BUDGET_NANOUSD / 1e9,
                "input_reservation": "UTF8 JSON bytes + 2048 + 256/message",
                "guard_version": 1,
                "billing_hard_cap": False,
            },
        }

    def complete(self, messages: list[dict], *, purpose: str) -> ModelResponse:
        use_critic_route = purpose in {"critic", "escalate"}
        selected_url = self.critic_base_url if use_critic_route else self.base_url
        selected_model = self.critic_model if use_critic_route else self.model
        try:
            kind = self._endpoint_kind(selected_url)
            if kind == "openai" and selected_model != OPENAI_MODEL:
                raise ValueError("Unpriced hosted model")
        except ValueError:
            return ModelResponse(
                "",
                error="Inference endpoint or model is not allowed",
                request_sent=False,
                blocked_reason="configuration",
            )
        if kind == "openai":
            return self._complete_hosted(messages, purpose=purpose)
        start = time.perf_counter()
        is_critic = use_critic_route
        selected_model = self.critic_model if is_critic else self.model
        if not self.configured:
            return ModelResponse(
                "", error="No model configured", request_sent=False, blocked_reason="configuration"
            )
        headers = {"Content-Type": "application/json"}
        selected_key = self.critic_api_key if is_critic else self.api_key
        if selected_key:
            headers["Authorization"] = "Bearer " + selected_key
        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.critic_max_tokens if is_critic else self.max_tokens,
            "stream": False,
        }
        if self.critic_disable_thinking if is_critic else self.disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        elif is_critic and self._critic_thinking_override:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        client = self._client or httpx.Client(
            timeout=self.timeout, follow_redirects=False, trust_env=False
        )
        try:
            with client.stream(
                "POST",
                (self.critic_base_url if is_critic else self.base_url) + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    return ModelResponse(
                        "",
                        latency_ms=(time.perf_counter() - start) * 1000,
                        error=f"Inference HTTP {response.status_code}",
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ValueError("Response size limit")
                body = parse_json(content.decode())
            choice = body["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str) or len(text) > 60000:
                raise ValueError("Invalid content")
            usage = body.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
            known = all(type(x) is int and 0 <= x <= 1_000_000_000 for x in (prompt, completion))
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise ValueError("Invalid finish reason")
            return ModelResponse(
                text,
                prompt if known else None,
                completion if known else None,
                (time.perf_counter() - start) * 1000,
                finish_reason,
                known,
                model=selected_model,
            )
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            UnicodeError,
            RecursionError,
        ):
            return ModelResponse(
                "",
                latency_ms=(time.perf_counter() - start) * 1000,
                error="Inference transport or response error",
            )
        finally:
            if self._client is None:
                client.close()

    def _complete_hosted(self, messages, *, purpose):
        started = time.perf_counter()
        if not self.enable_paid:
            return ModelResponse(
                "",
                error="Paid inference is disabled; no request was sent",
                model=OPENAI_MODEL,
                request_sent=False,
                blocked_reason="paid_disabled",
            )
        reservation = None
        try:
            # Read credentials only after the explicit paid flag. A missing key does
            # not consume a reservation and never leaks into errors or configuration.
            key = self._hosted_key_loader()
        except (BudgetError, OSError, ValueError):
            return ModelResponse(
                "",
                latency_ms=(time.perf_counter() - started) * 1000,
                error="Hosted credentials are unavailable; no request was sent",
                model=OPENAI_MODEL,
                request_sent=False,
                blocked_reason="credentials",
            )
        try:
            ledger = self._ledger()
            maximum = (
                self.critic_max_tokens if purpose in {"critic", "escalate"} else self.max_tokens
            )
            reservation = ledger.reserve(messages, maximum, purpose)
        except (BudgetError, OSError, ValueError) as exc:
            return ModelResponse(
                "",
                latency_ms=(time.perf_counter() - started) * 1000,
                error="Hosted request blocked by credentials or durable budget guard",
                model=OPENAI_MODEL,
                request_sent=False,
                blocked_reason=getattr(exc, "code", "budget_guard"),
            )
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_completion_tokens": maximum,
            "reasoning_effort": self.openai_reasoning_effort,
            "service_tier": "default",
            "n": 1,
            "store": False,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        client = self._client or httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0),
        )
        response_data = None
        known, prompt, completion = False, None, None
        try:
            with client.stream(
                "POST",
                OPENAI_BASE_URL + "/chat/completions",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                json=payload,
                timeout=self.timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    billing = ledger.settle(reservation["reservation_id"])
                    return ModelResponse(
                        "",
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error=f"Hosted inference HTTP {response.status_code}; reservation retained",
                        model=OPENAI_MODEL,
                        billing=billing,
                    )
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("Response size limit")
                response_data = parse_json(raw.decode())
            usage = response_data.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
            known = all(type(x) is int and 0 <= x <= 1_000_000_000 for x in (prompt, completion))
            billing = ledger.settle(
                reservation["reservation_id"],
                prompt_tokens=prompt,
                completion_tokens=completion,
                response_model=response_data.get("model"),
                service_tier=response_data.get("service_tier"),
            )
            choice = response_data["choices"][0]
            text = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            if not isinstance(text, str) or len(text) > 60000:
                raise ValueError("Invalid content")
            if finish_reason not in {None, "stop", "length", "content_filter", "tool_calls"}:
                raise ValueError("Invalid finish reason")
            detail = usage.get("completion_tokens_details") or {}
            reasoning = detail.get("reasoning_tokens") if isinstance(detail, dict) else None
            if type(reasoning) is not int or reasoning < 0 or not known or reasoning > completion:
                reasoning = None
            return ModelResponse(
                text,
                prompt if known else None,
                completion if known else None,
                (time.perf_counter() - started) * 1000,
                finish_reason,
                known,
                model=OPENAI_MODEL,
                billing=billing,
                reasoning_tokens=reasoning,
                error="Hosted provider metadata exceeded the budget assumptions"
                if billing["state"] == "overrun"
                else None,
            )
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            UnicodeError,
            RecursionError,
            AttributeError,
            BudgetError,
        ):
            try:
                billing = ledger.settle(reservation["reservation_id"])
            except BudgetError:
                billing = reservation
            return ModelResponse(
                "",
                prompt_tokens=prompt if known else None,
                completion_tokens=completion if known else None,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage_known=known,
                error="Hosted transport or response failed; budget remains accounted",
                model=OPENAI_MODEL,
                billing=billing,
            )
        finally:
            if self._client is None:
                client.close()


def usage_for(calls: list[tuple[ModelResponse, bool]]) -> dict:
    """Logical strategy cost and actual billable calls are separate for paired evaluation."""
    blocked = sum(not response.request_sent for response, _ in calls)
    calls = [(response, reused) for response, reused in calls if response.request_sent]
    known = all(response.usage_known for response, _ in calls)
    actual = [(response, reused) for response, reused in calls if not reused]

    def tokens(records, attr):
        return sum(getattr(response, attr) or 0 for response, _ in records)

    prompt = tokens(calls, "prompt_tokens")
    completion = tokens(calls, "completion_tokens")
    usage = {
        "calls": len(calls),
        "actual_calls": len(actual),
        "reused_calls": len(calls) - len(actual),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "actual_total_tokens": tokens(actual, "prompt_tokens")
        + tokens(actual, "completion_tokens"),
        "known": known,
        "unknown_calls": sum(not response.usage_known for response, _ in calls),
    }
    paid = [(response, reused) for response, reused in calls if response.billing is not None]
    if paid or blocked:
        known_cost = all(response.billing["state"] == "settled" for response, _ in paid)
        actual_cost_known = all(
            response.billing["state"] == "settled" for response, reused in paid if not reused
        )
        usage.update(
            {
                "blocked_calls": blocked,
                "paid_calls": len(paid),
                "actual_paid_calls": sum(not reused for _, reused in paid),
                "estimated_cost_usd": sum(r.billing.get("estimated_cost_usd") or 0 for r, _ in paid)
                if known_cost
                else None,
                "accounted_cost_usd": sum(r.billing["accounted_usd"] for r, _ in paid),
                "actual_accounted_cost_usd": sum(
                    r.billing["accounted_usd"] for r, reused in paid if not reused
                ),
                "cost_known": known_cost,
                "actual_cost_known": actual_cost_known,
                "actual_estimated_cost_usd": sum(
                    r.billing.get("estimated_cost_usd") or 0 for r, reused in paid if not reused
                )
                if actual_cost_known
                else None,
                "cost_label": "Standard-price estimate / conservative reservations, not invoice total",
            }
        )
    return usage


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
