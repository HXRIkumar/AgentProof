"""Exercise the actual OTLP HTTP exporter against a local collector fixture."""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def test_workflow_exports_stage_spans_without_prompt_bodies(tmp_path):
    requests = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = """
from agentproof.engine import Engine
from agentproof.store import Store
from agentproof.scenarios import SCENARIOS
from opentelemetry import trace
import os
Engine(Store(os.environ['AGENTPROOF_DB'])).run(SCENARIOS[0])
trace.get_tracer_provider().shutdown()
"""
    try:
        env = {
            **os.environ,
            "AGENTPROOF_DB": str(tmp_path / "otel.sqlite"),
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
        }
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        assert requests
        spans = []
        for path, body in requests:
            assert path == "/v1/traces"
            message = ExportTraceServiceRequest.FromString(body)
            for resource in message.resource_spans:
                for scope in resource.scope_spans:
                    spans.extend(scope.spans)
        assert {s.name for s in spans} == {
            "agentproof.observe",
            "agentproof.propose",
            "agentproof.validate",
            "agentproof.execute",
            "agentproof.grade",
        }
        for span in spans:
            assert span.end_time_unix_nano >= span.start_time_unix_nano
            assert {a.key for a in span.attributes} == {"agentproof.run_id", "agentproof.variant"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
