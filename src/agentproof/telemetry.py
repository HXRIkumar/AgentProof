import os
import threading
from contextlib import contextmanager
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from . import __version__

_initialization_lock = threading.Lock()


@lru_cache(maxsize=1)
def _configured_tracer():
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return trace.NoOpTracer(), None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "agentproof"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces"))
    )
    # Do not replace an SDK owned by the embedding application, or silently send
    # AgentProof spans to its exporter instead of this configured endpoint.
    return provider.get_tracer("agentproof.runtime", __version__), provider


def tracer():
    # lru_cache alone permits simultaneous first callers to initialize twice.
    with _initialization_lock:
        return _configured_tracer()[0]


def flush_telemetry(timeout_millis=5000):
    """Explicit best-effort exporter flush for command-line and integration clients."""
    with _initialization_lock:
        provider = _configured_tracer()[1]
    return provider.force_flush(timeout_millis) if provider is not None else True


@contextmanager
def execution_span(name, attributes):
    """Never let the SDK capture arbitrary exception messages or stack traces."""
    configured = tracer()
    if isinstance(configured, trace.NoOpTracer):
        # A no-op SDK scope can borrow ambient IDs or replace its context. Leave
        # other instrumentation untouched and expose no AgentProof correlation.
        yield trace.INVALID_SPAN
        return
    with configured.start_as_current_span(
        name,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_attribute("error.type", type(exc).__name__[:64])
            span.set_status(Status(StatusCode.ERROR))
            raise


def trace_identity(span):
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return {
        "trace_id": f"{context.trace_id:032x}",
        "span_id": f"{context.span_id:016x}",
        "sampled": context.trace_flags.sampled,
    }


def final_run_attributes(span, run, *, completed):
    """Export controlled outcomes and bounded counters, never arbitrary run contents."""
    span.set_attribute("agentproof.evaluation_completed", completed)
    status = run.get("status") if completed else "failed"
    outcome = run.get("outcome") if completed else "interrupted"
    graded = bool(
        completed and run.get("checks") and status in ("completed", "awaiting_approval")
    )
    span.set_attribute("agentproof.grading_completed", graded)
    span.set_attribute(
        "agentproof.status",
        status if status in ("completed", "awaiting_approval", "failed") else "unknown",
    )
    span.set_attribute(
        "agentproof.outcome",
        outcome
        if outcome in ("refunded", "rejected", "escalated", "approval_required", "interrupted")
        else "unknown",
    )
    for field in ("model_calls", "proposal_calls", "retries", "token_usage"):
        value = run.get(field)
        if type(value) is int:
            label = "reported_tokens" if field == "token_usage" else field
            span.set_attribute("agentproof." + label, max(0, min(value, 2**63 - 1)))
    if graded:
        for field in ("passed", "safe"):
            if type(run.get(field)) is bool:
                span.set_attribute("agentproof." + field, run[field])
    if completed:
        span.set_status(Status(StatusCode.OK))
