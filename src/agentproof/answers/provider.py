"""Bounded OpenAI-compatible inference, including actual per-call accounting."""

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import httpx

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
        client=None,
    ):
        self.base_url = (
            os.getenv("ANSWER_LAB_BASE_URL", "") if base_url is None else base_url
        ).rstrip("/")
        self.model = os.getenv("ANSWER_LAB_MODEL", "") if model is None else model
        self.api_key = api_key if api_key is not None else os.getenv("ANSWER_LAB_API_KEY", "")
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
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Invalid inference endpoint")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Inference endpoint must not contain credentials or query data")

    @property
    def configured(self):
        return bool(self.base_url and self.model)

    def configuration(self):
        return {
            "model": self.model,
            "revision": self.revision,
            "endpoint_hash": hashlib.sha256(self.base_url.encode()).hexdigest(),
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "disable_thinking": self.disable_thinking,
            "critic_model": self.critic_model,
            "critic_revision": self.critic_revision,
            "critic_max_tokens": self.critic_max_tokens,
            "critic_disable_thinking": self.critic_disable_thinking,
            "critic_thinking_override": self._critic_thinking_override,
        }

    def complete(self, messages: list[dict], *, purpose: str) -> ModelResponse:
        start = time.perf_counter()
        is_critic = purpose == "critic"
        selected_model = self.critic_model if is_critic else self.model
        if not self.configured:
            return ModelResponse("", error="No model configured")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
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
        client = self._client or httpx.Client(timeout=self.timeout, follow_redirects=False)
        try:
            with client.stream(
                "POST",
                self.base_url + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
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


def usage_for(calls: list[tuple[ModelResponse, bool]]) -> dict:
    """Logical strategy cost and actual billable calls are separate for paired evaluation."""
    known = all(response.usage_known for response, _ in calls)
    actual = [(response, reused) for response, reused in calls if not reused]

    def tokens(records, attr):
        return sum(getattr(response, attr) or 0 for response, _ in records)

    prompt = tokens(calls, "prompt_tokens")
    completion = tokens(calls, "completion_tokens")
    return {
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


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
