"""Run real local HTTP refund failures and independently inspect the server ledger."""

import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from agentproof.remote_client import RemoteRefundClient
from agentproof.remote_service import RefundRequest

ROOT = Path(__file__).resolve().parents[1]


class ServiceProcess:
    def __init__(self, directory, *, drop=0, hide=False):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "service.sqlite3"
        self.ready = directory / "ready.json"
        self.drop, self.hide = drop, hide
        self.process = None
        self.log = None

    def __enter__(self):
        self.ready.unlink(missing_ok=True)
        command = [
            sys.executable,
            "-m",
            "agentproof.remote_service",
            "--database",
            str(self.database),
            "--ready-file",
            str(self.ready),
            "--drop-after-commit",
            str(self.drop),
        ]
        if self.hide:
            command.append("--hide-operations")
        try:
            self.log = (self.directory / "service.log").open("a")
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=self.log,
                stderr=self.log,
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Synthetic service exited during startup")
                if self.ready.exists():
                    ready = json.loads(self.ready.read_text())
                    self.base_url, self.pid = ready["base_url"], ready["pid"]
                    if self.pid != self.process.pid:
                        raise RuntimeError("Ready file identifies a different process")
                    return self
                time.sleep(0.02)
            raise TimeoutError("Synthetic service did not become ready")
        except BaseException:
            # Context manager __exit__ is not called when __enter__ raises.
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                except BaseException:
                    with contextlib.suppress(ProcessLookupError):
                        self.process.kill()
                    self.process.wait(timeout=5)
                    raise
        finally:
            if self.log is not None:
                self.log.close()


def ledger(database):
    """Independent read-only evidence: no client receipt or client success flag used."""
    with contextlib.closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        db.row_factory = sqlite3.Row
        effects = [dict(row) for row in db.execute("SELECT * FROM effects ORDER BY effect_id")]
        balances = [
            dict(row)
            for row in db.execute("SELECT id,paid_cents,refunded_cents FROM orders ORDER BY id")
        ]
        operations = [
            dict(row)
            for row in db.execute(
                "SELECT operation_key,request_hash FROM operations ORDER BY operation_key"
            )
        ]
    return {
        "effect_count": len(effects),
        "total_cents": sum(e["amount_cents"] for e in effects),
        "effects": effects,
        "orders": balances,
        "operations": operations,
    }


def run_lab(output):
    if output.exists():
        raise FileExistsError("Output directory already exists; choose a new evidence directory")
    output.mkdir(parents=True)
    request = RefundRequest(
        order_id="ORD-100", customer_id="CUS-17", amount_cents=3100, policy_version="refund-v1"
    )
    cases = []

    with ServiceProcess(output / "lost-response", drop=1) as service:
        result = RemoteRefundClient(service.base_url).refund("stable-operation", request)
        evidence = ledger(service.database)
        cases.append(
            {
                "case": "commit_then_socket_close",
                "service_pids": [service.pid],
                "result": result.as_dict(),
                "ledger": evidence,
                "passed": result.outcome == "reconciled"
                and evidence["effect_count"] == 1
                and evidence["total_cents"] == 3100
                and any(e.get("error") for e in result.events if e["method"] == "POST"),
            }
        )

    with ServiceProcess(output / "restart", drop=1) as service:
        first_pid = service.pid
        try:
            httpx.post(
                service.base_url + "/refunds",
                json=request.model_dump(),
                headers={"Idempotency-Key": "restart-operation"},
                timeout=2,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            lost_response = type(exc).__name__
        else:
            raise AssertionError("Expected a genuine connection loss after commit")
        before = ledger(service.database)
    with ServiceProcess(output / "restart") as service:
        result = RemoteRefundClient(service.base_url).refund("restart-operation", request)
        after = ledger(service.database)
        cases.append(
            {
                "case": "service_restart_before_same_key_retry",
                "service_pids": [first_pid, service.pid],
                "first_error": lost_response,
                "result": result.as_dict(),
                "ledger_before_restart": before,
                "ledger": after,
                "passed": first_pid != service.pid
                and before == after
                and after["effect_count"] == 1
                and result.outcome == "committed",
            }
        )

    with ServiceProcess(output / "concurrency") as service:

        def submit(_):
            return RemoteRefundClient(service.base_url).refund("concurrent-operation", request)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(8)))
        evidence = ledger(service.database)
        cases.append(
            {
                "case": "eight_concurrent_same_key_requests",
                "service_pids": [service.pid],
                "results": [r.as_dict() for r in results],
                "ledger": evidence,
                "passed": all(r.outcome == "committed" for r in results)
                and len({r.receipt["effect_id"] for r in results}) == 1
                and evidence["effect_count"] == 1
                and evidence["total_cents"] == 3100,
            }
        )
        changed = request.model_copy(update={"amount_cents": 3200})
        conflict = RemoteRefundClient(service.base_url).refund("concurrent-operation", changed)
        unchanged = ledger(service.database)
        cases.append(
            {
                "case": "same_key_changed_arguments",
                "service_pids": [service.pid],
                "result": conflict.as_dict(),
                "ledger": unchanged,
                "passed": conflict.outcome == "conflict" and unchanged == evidence,
            }
        )

    with ServiceProcess(output / "unresolved", drop=1, hide=True) as service:
        result = RemoteRefundClient(service.base_url, max_attempts=1).refund(
            "unknown-operation", request
        )
        evidence = ledger(service.database)
        cases.append(
            {
                "case": "commit_hidden_by_unavailable_reconciliation",
                "service_pids": [service.pid],
                "result": result.as_dict(),
                "ledger": evidence,
                "passed": result.outcome == "unresolved"
                and result.receipt is None
                and evidence["effect_count"] == 1
                and evidence["total_cents"] == 3100,
            }
        )

    with ServiceProcess(output / "new-key-control", drop=1) as service:
        try:
            httpx.post(
                service.base_url + "/refunds",
                json=request.model_dump(),
                headers={"Idempotency-Key": "naive-first"},
                timeout=2,
                trust_env=False,
            )
        except httpx.HTTPError:
            pass
        else:
            raise AssertionError("Expected the first response to be lost")
        result = RemoteRefundClient(service.base_url).refund("naive-replacement-key", request)
        evidence = ledger(service.database)
        cases.append(
            {
                "case": "new_key_after_ambiguity_duplicates_logical_request",
                "service_pids": [service.pid],
                "result": result.as_dict(),
                "ledger": evidence,
                "passed": result.outcome == "committed"
                and evidence["effect_count"] == 2
                and evidence["total_cents"] == 6200,
                "interpretation": "Deliberately unsafe control: new keys represent distinct "
                "operations to the remote service. A passing test observes the duplicate.",
            }
        )

    source_files = [
        "src/agentproof/remote_service.py",
        "src/agentproof/remote_client.py",
        "scripts/remote_lab.py",
    ]
    report = {
        "schema_version": "agentproof-remote-tool-lab-v1",
        "synthetic": True,
        "model_calls": 0,
        "passed": all(c["passed"] for c in cases),
        "client_pid": os.getpid(),
        "cases": cases,
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files
        },
        "limitations": [
            "Local synthetic service, no real payments or customer adoption.",
            "Customer identity is an assertion; no production authentication.",
            "Independent service process and database; same physical host.",
            "Idempotency keys are retained indefinitely in this fixture.",
            "No high-value approval execution or automatic in-flight graph recovery.",
            "Unresolved is not rejection: an unobserved effect may already exist.",
        ],
    }
    raw = output / "evidence.json"
    raw.write_text(json.dumps(report, indent=2) + "\n")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    lines = [
        "# Local remote-tool integration evidence",
        "",
        "Synthetic HTTP service; zero model calls.",
        "",
        "| Case | Verified condition | Server effects |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {case['case']} | {'PASS' if case['passed'] else 'FAIL'} | "
        f"{case['ledger']['effect_count']} |"
        for case in cases
    )
    lines += [
        "",
        "Each server runs in a separate process. Effects are independently read from its",
        "SQLite database, not inferred from client responses. The new-key control deliberately",
        "creates two effects; PASS means this unsafe behavior was observed as expected.",
        "",
        "The unresolved case has one committed effect that the client cannot verify.",
        "It therefore returns unresolved rather than claiming success or safe rejection.",
        "",
        f"Raw evidence SHA-256: `{digest}`",
        "",
        "## Limits",
        "",
    ]
    lines.extend("- " + limitation for limitation in report["limitations"])
    (output / "report.md").write_text("\n".join(lines) + "\n")
    (output / "SHA256SUMS").write_text(f"{digest}  evidence.json\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run_lab(args.output_dir)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "cases": len(report["cases"]),
                "model_calls": 0,
                "evidence": str(args.output_dir / "evidence.json"),
            }
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
