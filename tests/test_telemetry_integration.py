"""Decode actual OTLP HTTP exports; no mocked tracer calls or model requests."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Status

ROOT = Path(__file__).resolve().parents[1]
STAGES = {"observe", "propose", "validate", "execute", "grade"}
STAGE_ATTRIBUTES = {"agentproof.run_id", "agentproof.variant"}
ROOT_ATTRIBUTES = STAGE_ATTRIBUTES | {
    "agentproof.provider", "agentproof.proposal_budget", "agentproof.status",
    "agentproof.outcome", "agentproof.evaluation_completed", "agentproof.grading_completed",
    "agentproof.model_calls", "agentproof.proposal_calls", "agentproof.retries",
    "agentproof.reported_tokens", "agentproof.passed", "agentproof.safe",
}
PRIVATE_MARKERS = (
    "PRIVATE_PROMPT_SENTINEL", "PRIVATE_NOTE_SENTINEL", "PRIVATE_OUTPUT_SENTINEL",
    "PRIVATE_CREDENTIAL_SENTINEL", "PRIVATE_EXCEPTION_SENTINEL",
)


@pytest.fixture
def collector():
    requests = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def execute(tmp_path, collector, code, *, enabled=True):
    # Child processes isolate the SDK singleton and exercise concurrent first use.
    # Ambient OTEL settings must not send evidence to an unrelated endpoint.
    endpoint, requests = collector
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        AGENTPROOF_DB=str(tmp_path / "otel.sqlite"),
        TEST_COLLECTOR_ENDPOINT=endpoint,
        AGENTPROOF_API_KEY="PRIVATE_CREDENTIAL_SENTINEL",
    )
    if enabled:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
    prefix = """
import json, os
from agentproof.engine import Engine
from agentproof.store import Store
from agentproof.scenarios import BY_ID
from agentproof.providers import ScriptedProvider
from opentelemetry import trace
store = Store(os.environ['AGENTPROOF_DB'])
"""
    suffix = """
from agentproof.telemetry import flush_telemetry
assert flush_telemetry()
provider = trace.get_tracer_provider()
if hasattr(provider, 'shutdown'):
    provider.shutdown()
"""
    result = subprocess.run(
        [sys.executable, "-c", prefix + code + suffix], cwd=ROOT, env=env, check=False,
        capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stderr
    assert "Overriding of current TracerProvider is not allowed" not in result.stderr
    spans = []
    for path, body in requests:
        assert path == "/v1/traces"
        for marker in PRIVATE_MARKERS:
            assert marker.encode() not in body
        message = ExportTraceServiceRequest.FromString(body)
        for resource in message.resource_spans:
            for scope in resource.scope_spans:
                spans.extend(scope.spans)
    return json.loads(result.stdout), spans


def attributes(span):
    return {
        item.key: getattr(item.value, item.value.WhichOneof("value"))
        for item in span.attributes
    }


def assert_run_tree(run, spans, parent_span_id=b""):
    own = [span for span in spans if attributes(span).get("agentproof.run_id") == run["id"]]
    roots = [span for span in own if span.name == "agentproof.run"]
    assert len(roots) == 1
    root = roots[0]
    assert run["trace_context"] == {
        "trace_id": root.trace_id.hex(), "span_id": root.span_id.hex(), "sampled": True,
    }
    assert len(root.trace_id) == 16 and int.from_bytes(root.trace_id) > 0
    assert len(root.span_id) == 8 and int.from_bytes(root.span_id) > 0
    assert root.parent_span_id == parent_span_id
    assert len({span.span_id for span in own}) == len(own)
    for child in own:
        assert child.trace_id == root.trace_id
        assert root.start_time_unix_nano <= child.start_time_unix_nano
        assert child.start_time_unix_nano <= child.end_time_unix_nano <= root.end_time_unix_nano
        if child is not root:
            assert child.parent_span_id == root.span_id
    return root, own


def test_workflow_exports_one_correlated_root_and_private_stage_spans(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
import agentproof.providers as providers
providers.SYSTEM_PROMPT = 'PRIVATE_PROMPT_SENTINEL'
class PrivateFixture(ScriptedProvider):
    def propose(self, *args, **kwargs):
        raw, tokens = super().propose(*args, **kwargs)
        proposal = json.loads(raw)
        proposal['reason'] = 'PRIVATE_OUTPUT_SENTINEL'
        return json.dumps(proposal), tokens
case = BY_ID['eligible'].model_copy(update={'untrusted_note': 'PRIVATE_NOTE_SENTINEL'})
run = Engine(store, lambda _: PrivateFixture()).run(case)
print(json.dumps({'run':run, 'stored':store.get_run(run['id'])}))
""")
    run = data["run"]
    assert data["stored"] == run
    assert run["passed"] and run["safe"] and len(run["final_state"]["effects"]) == 1
    assert len(spans) == 6
    root, own = assert_run_tree(run, spans)
    assert {span.name for span in own} == {"agentproof.run"} | {
        "agentproof." + stage for stage in STAGES
    }
    assert attributes(root) == {
        "agentproof.run_id": run["id"], "agentproof.variant": "guarded",
        "agentproof.provider": "scripted", "agentproof.proposal_budget": 3,
        "agentproof.status": "completed", "agentproof.outcome": "refunded",
        "agentproof.evaluation_completed": True, "agentproof.grading_completed": True,
        "agentproof.model_calls": 0, "agentproof.proposal_calls": 1,
        "agentproof.retries": 0, "agentproof.reported_tokens": 0,
        "agentproof.passed": True, "agentproof.safe": True,
    }
    assert root.status.code == Status.STATUS_CODE_OK
    for span in own:
        assert set(attributes(span)) == (ROOT_ATTRIBUTES if span is root else STAGE_ATTRIBUTES)
        assert not span.events
        assert not span.status.message


def test_concurrent_first_runs_keep_distinct_trace_trees(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
start, proposal = Barrier(2), Barrier(2)
class OverlappingFixture(ScriptedProvider):
    def propose(self, *args, **kwargs):
        proposal.wait(timeout=10)
        return super().propose(*args, **kwargs)
def run_one(case):
    engine = Engine(store, lambda _: OverlappingFixture())
    start.wait(timeout=10)
    run = engine.run(BY_ID[case])
    return {'run':run, 'stored':store.get_run(run['id'])}
with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(run_one, ['eligible', 'partial']))
print(json.dumps(results))
""")
    assert len(spans) == 12
    roots = []
    for pair in data:
        assert pair["stored"] == pair["run"] and pair["run"]["passed"]
        root, own = assert_run_tree(pair["run"], spans)
        assert len(own) == 6
        roots.append(root)
    assert roots[0].trace_id != roots[1].trace_id
    assert max(root.start_time_unix_nano for root in roots) < min(
        root.end_time_unix_nano for root in roots
    )


def test_disabled_tracing_has_null_ids_even_with_an_external_sdk(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
    endpoint=os.environ['TEST_COLLECTOR_ENDPOINT'] + '/v1/traces')))
trace.set_tracer_provider(provider)
class ExternallyInstrumentedFixture(ScriptedProvider):
    def propose(self, *args, **kwargs):
        with trace.get_tracer('external-test').start_as_current_span('external.child'):
            return super().propose(*args, **kwargs)
with trace.get_tracer('external-test').start_as_current_span('external.control'):
    run = Engine(store, lambda _: ExternallyInstrumentedFixture()).run(BY_ID['eligible'])
print(json.dumps({'run':run, 'stored':store.get_run(run['id'])}))
""", enabled=False)
    assert data["run"]["trace_context"] is None
    assert data["stored"]["trace_context"] is None
    assert data["run"]["passed"] and len(data["run"]["final_state"]["effects"]) == 1
    assert {span.name for span in spans} == {"external.control", "external.child"}
    parent = next(span for span in spans if span.name == "external.control")
    child = next(span for span in spans if span.name == "external.child")
    assert child.parent_span_id == parent.span_id
    assert child.trace_id == parent.trace_id


def test_enabled_tracing_coexists_with_an_existing_sdk_and_parent(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
from opentelemetry.sdk.trace import TracerProvider
external = TracerProvider()
trace.set_tracer_provider(external)
with trace.get_tracer('external-test').start_as_current_span('external.control') as parent:
    parent_context = parent.get_span_context()
    run = Engine(store).run(BY_ID['eligible'])
assert trace.get_tracer_provider() is external
print(json.dumps({'run':run, 'stored':store.get_run(run['id']),
    'parent_span_id':format(parent_context.span_id, '016x'),
    'parent_trace_id':format(parent_context.trace_id, '032x')}))
""")
    assert len(spans) == 6
    assert data["stored"] == data["run"]
    root, own = assert_run_tree(data["run"], spans, bytes.fromhex(data["parent_span_id"]))
    assert root.trace_id.hex() == data["parent_trace_id"]
    assert len(own) == 6 and all(span.name.startswith("agentproof.") for span in spans)


def test_unexpected_failure_exports_only_type_and_ungraded_status(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
class BrokenFixture(ScriptedProvider):
    def propose(self, *args, **kwargs):
        raise RuntimeError('PRIVATE_EXCEPTION_SENTINEL PRIVATE_CREDENTIAL_SENTINEL')
try:
    Engine(store, lambda _: BrokenFixture()).run(BY_ID['eligible'])
except RuntimeError as exc:
    with store.connect() as db:
        run_id = db.execute('SELECT id FROM runs').fetchone()['id']
    print(json.dumps({'exception_type':type(exc).__name__, 'run':store.get_run(run_id)}))
else:
    raise AssertionError('The exception must propagate unchanged')
""")
    assert data["exception_type"] == "RuntimeError"
    run = data["run"]
    assert run["status"] == "failed" and not run["checks"]
    root, own = assert_run_tree(run, spans)
    assert {span.name for span in own} == {
        "agentproof.run", "agentproof.observe", "agentproof.propose",
    }
    values = attributes(root)
    assert values["agentproof.status"] == "failed"
    assert values["agentproof.outcome"] == "interrupted"
    assert values["agentproof.evaluation_completed"] is False
    assert values["agentproof.grading_completed"] is False
    assert "agentproof.safe" not in values and "agentproof.passed" not in values
    for span in own:
        assert not span.events and not span.status.message
        if span.name in ("agentproof.run", "agentproof.propose"):
            assert span.status.code == Status.STATUS_CODE_ERROR
            assert attributes(span)["error.type"] == "RuntimeError"
        else:
            assert "error.type" not in attributes(span)


def test_retries_and_approval_are_children_and_keep_final_accounting(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
runs = [Engine(store).run(BY_ID[name]) for name in ['malformed', 'approval', 'wrong-owner']]
print(json.dumps(runs))
""")
    for run in data:
        root, own = assert_run_tree(run, spans)
        values = attributes(root)
        assert values["agentproof.proposal_calls"] == run["proposal_calls"]
        assert values["agentproof.retries"] == run["retries"]
        assert values["agentproof.reported_tokens"] == run["token_usage"]
        assert values["agentproof.outcome"] == run["outcome"]
        assert values["agentproof.status"] == run["status"]
        assert values["agentproof.grading_completed"] and values["agentproof.passed"]
        assert values["agentproof.safe"]
        if run["scenario_id"] == 'malformed':
            assert len([span for span in own if span.name == 'agentproof.propose']) == 2
            assert len(own) == 8
        if run["scenario_id"] == 'approval':
            assert run["final_state"]["effects"] == []
            assert values["agentproof.status"] == 'awaiting_approval'


def test_completed_evaluation_can_have_failed_task_grade(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
run = Engine(store).run(BY_ID['amount-injection'], 'baseline')
print(json.dumps(run))
""")
    assert not data["passed"] and not data["safe"]
    root, _ = assert_run_tree(data, spans)
    assert root.status.code == Status.STATUS_CODE_OK
    values = attributes(root)
    assert values["agentproof.evaluation_completed"] is True
    assert values["agentproof.grading_completed"] is True
    assert values["agentproof.passed"] is False and values["agentproof.safe"] is False
