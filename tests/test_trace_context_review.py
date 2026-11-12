"""Independent trace checks decoded from actual local OTLP HTTP exports.

Only scripted providers execute. Each child process isolates the OpenTelemetry
configuration, and the collector is a disposable loopback HTTP server.
"""

import pytest
from opentelemetry.proto.trace.v1.trace_pb2 import Status
from test_telemetry_integration import assert_run_tree, attributes, execute
from test_telemetry_integration import collector as collector  # noqa: PLC0414 - pytest fixture export


def test_sampling_off_keeps_valid_unsampled_ids_without_claiming_export(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
os.environ['OTEL_TRACES_SAMPLER'] = 'always_off'
run = Engine(store).run(BY_ID['eligible'])
print(json.dumps({'run':run, 'stored':store.get_run(run['id'])}))
""")
    run = data["run"]
    assert run == data["stored"] and run["passed"]
    context = run["trace_context"]
    assert context["sampled"] is False
    assert len(context["trace_id"]) == 32 and int(context["trace_id"], 16) > 0
    assert len(context["span_id"]) == 16 and int(context["span_id"], 16) > 0
    assert spans == []


def test_same_engine_concurrent_runs_have_separate_persisted_trace_trees(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
start, proposal = Barrier(2), Barrier(2)
class Overlap(ScriptedProvider):
    def propose(self, *args, **kwargs):
        proposal.wait(timeout=10)
        return super().propose(*args, **kwargs)
engine = Engine(store, lambda _: Overlap())
def run_one(name):
    start.wait(timeout=10)
    run = engine.run(BY_ID[name])
    return {'run':run, 'stored':store.get_run(run['id'])}
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(run_one, ['eligible', 'partial']))
print(json.dumps(results))
""")
    roots = []
    assert len(spans) == 12
    for pair in data:
        assert pair["stored"] == pair["run"] and pair["run"]["passed"]
        root, own = assert_run_tree(pair["run"], spans)
        assert len(own) == 6
        assert attributes(root)["agentproof.grading_completed"] is True
        roots.append(root)
    assert roots[0].trace_id != roots[1].trace_id
    assert max(root.start_time_unix_nano for root in roots) < min(
        root.end_time_unix_nano for root in roots
    )


@pytest.mark.parametrize("exception_name", ["KeyboardInterrupt", "SystemExit"])
def test_baseexception_exports_redacted_error_without_safety_claim(
    tmp_path, collector, exception_name,
):
    data, spans = execute(tmp_path, collector, """
class InterruptingFixture(ScriptedProvider):
    def propose(self, *args, **kwargs):
        raise EXCEPTION_CLASS('PRIVATE_EXCEPTION_SENTINEL PRIVATE_CREDENTIAL_SENTINEL')
try:
    Engine(store, lambda _: InterruptingFixture()).run(BY_ID['eligible'])
except BaseException as exc:
    with store.connect() as db:
        run_id = db.execute('SELECT id FROM runs').fetchone()['id']
    print(json.dumps({'kind':type(exc).__name__, 'run':store.get_run(run_id)}))
else:
    raise AssertionError('The control interruption must propagate')
""".replace("EXCEPTION_CLASS", exception_name))
    assert data["kind"] == exception_name
    root, own = assert_run_tree(data["run"], spans)
    values = attributes(root)
    assert root.status.code == Status.STATUS_CODE_ERROR
    assert values["error.type"] == exception_name
    assert values["agentproof.evaluation_completed"] is False
    assert values["agentproof.grading_completed"] is False
    assert values["agentproof.status"] == "failed"
    assert "agentproof.passed" not in values and "agentproof.safe" not in values
    assert all(not span.events and not span.status.message for span in own)


def test_failure_after_grading_does_not_export_success_or_safety_attributes(tmp_path, collector):
    data, spans = execute(tmp_path, collector, """
real_save = store.save_run
graded_writes = [0]
def fail_final_save(run, scenario):
    if run['checks']:
        graded_writes[0] += 1
        if graded_writes[0] == 2:
            raise OSError('PRIVATE_EXCEPTION_SENTINEL PRIVATE_CREDENTIAL_SENTINEL')
    return real_save(run, scenario)
store.save_run = fail_final_save
try:
    Engine(store).run(BY_ID['eligible'])
except OSError:
    with store.connect() as db:
        run_id = db.execute('SELECT id FROM runs').fetchone()['id']
    print(json.dumps({'run':store.get_run(run_id), 'graded_writes':graded_writes[0]}))
else:
    raise AssertionError('The final persistence failure must propagate')
""")
    run = data["run"]
    assert data["graded_writes"] == 2
    # The prior stage snapshot contains a real synthetic effect and complete grade.
    # The overall run call still failed; its root span must not claim success.
    assert run["checks"] and run["passed"] and len(run["final_state"]["effects"]) == 1
    root, own = assert_run_tree(run, spans)
    values = attributes(root)
    assert root.status.code == Status.STATUS_CODE_ERROR
    assert values["error.type"] == "OSError"
    assert values["agentproof.evaluation_completed"] is False
    assert values["agentproof.grading_completed"] is False
    assert values["agentproof.status"] == "failed"
    assert values["agentproof.outcome"] == "interrupted"
    assert "agentproof.passed" not in values and "agentproof.safe" not in values
    assert all(not span.events and not span.status.message for span in own)
