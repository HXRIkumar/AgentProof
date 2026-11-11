"""Local integration fixture with a real HTTP boundary and independent effect ledger.

This is a synthetic refund service, not a payment provider. Customer identity is
asserted by the caller; there is deliberately no production authentication.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import socket
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_BODY_BYTES = 8_192
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
POLICY_VERSION = "refund-v1"
ORDERS = (
    ("ORD-100", "CUS-17", 12, "delivered", 9000),
    ("ORD-HIGH", "CUS-17", 12, "delivered", 20000),
    ("ORD-OLD", "CUS-17", 45, "delivered", 9000),
    ("ORD-PROCESS", "CUS-17", 12, "processing", 9000),
)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    customer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    amount_cents: int = Field(gt=0, le=1_000_000)
    policy_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def request_hash(request: RefundRequest) -> str:
    payload = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def connect(database):
    db = sqlite3.connect(database, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db


def initialize(database):
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(connect(database)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, age_days INTEGER NOT NULL,
                status TEXT NOT NULL, paid_cents INTEGER NOT NULL,
                refunded_cents INTEGER NOT NULL DEFAULT 0,
                CHECK(refunded_cents >= 0 AND refunded_cents <= paid_cents)
            );
            CREATE TABLE IF NOT EXISTS operations (
                operation_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                receipt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS effects (
                effect_id TEXT PRIMARY KEY,
                operation_key TEXT NOT NULL UNIQUE REFERENCES operations(operation_key),
                order_id TEXT NOT NULL REFERENCES orders(id), customer_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents > 0 AND amount_cents <= 10000),
                created_at TEXT NOT NULL
            );
        """)
        db.executemany(
            "INSERT OR IGNORE INTO orders(id,customer_id,age_days,status,paid_cents) "
            "VALUES(?,?,?,?,?)",
            ORDERS,
        )


def refund(database, key, request):
    """Atomically bind a key to arguments, update balance, and persist one receipt."""
    digest = request_hash(request)
    with contextlib.closing(connect(database)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT request_hash,receipt FROM operations WHERE operation_key=?", (key,)
        ).fetchone()
        if existing:
            if existing["request_hash"] != digest:
                return 409, {"code": "idempotency_conflict"}, False
            return 200, json.loads(existing["receipt"]), False
        order = db.execute("SELECT * FROM orders WHERE id=?", (request.order_id,)).fetchone()
        if order is None:
            return 404, {"code": "order_not_found"}, False
        if order["customer_id"] != request.customer_id:
            return 403, {"code": "customer_mismatch"}, False
        if request.policy_version != POLICY_VERSION:
            return 409, {"code": "stale_policy", "current_policy": POLICY_VERSION}, False
        if order["age_days"] > 30 or order["status"] != "delivered":
            return 422, {"code": "ineligible_order"}, False
        if request.amount_cents > order["paid_cents"] - order["refunded_cents"]:
            return 422, {"code": "insufficient_balance"}, False
        if request.amount_cents > 10000:
            return 409, {"code": "approval_required"}, False
        receipt = {
            "operation_key": key,
            "request_hash": digest,
            "status": "committed",
            **request.model_dump(),
            "effect_id": uuid.uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
        }
        db.execute("INSERT INTO operations VALUES(?,?,?)", (key, digest, json.dumps(receipt)))
        db.execute(
            "INSERT INTO effects VALUES(?,?,?,?,?,?)",
            (
                receipt["effect_id"],
                key,
                request.order_id,
                request.customer_id,
                request.amount_cents,
                receipt["created_at"],
            ),
        )
        db.execute(
            "UPDATE orders SET refunded_cents=refunded_cents+? WHERE id=?",
            (request.amount_cents, request.order_id),
        )
    # Only return after COMMIT; the transport fault is injected by the HTTP layer.
    return 201, receipt, True


class RefundServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, database, drop_after_commit=0, hide_operations=False):
        self.database = str(database)
        self.drop_after_commit = drop_after_commit
        self.hide_operations = hide_operations
        self.fault_lock = threading.Lock()
        initialize(database)
        super().__init__(("127.0.0.1", port), Handler)

    def should_drop(self):
        with self.fault_lock:
            if self.drop_after_commit:
                self.drop_after_commit -= 1
                return True
            return False


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentProofLocalRefund/1"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, format, *args):
        pass

    def respond(self, status, body):
        encoded = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True

    def valid_host(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] != f"127.0.0.1:{self.server.server_port}":
            self.respond(400, {"code": "invalid_host"})
            return False
        return True

    def do_GET(self):
        if not self.valid_host():
            return
        if self.path == "/health":
            self.respond(200, {"status": "ready", "pid": os.getpid(), "synthetic": True})
            return
        prefix = "/operations/"
        key = self.path.removeprefix(prefix)
        if not self.path.startswith(prefix) or not KEY_PATTERN.fullmatch(key):
            self.respond(404, {"code": "not_found"})
            return
        if self.server.hide_operations:
            self.respond(503, {"code": "injected_reconciliation_unavailable"})
            return
        with contextlib.closing(connect(self.server.database)) as db:
            row = db.execute(
                "SELECT receipt FROM operations WHERE operation_key=?", (key,)
            ).fetchone()
        self.respond(200, json.loads(row["receipt"])) if row else self.respond(
            404, {"code": "operation_not_found"}
        )

    def do_POST(self):
        if not self.valid_host():
            return
        if self.path != "/refunds":
            self.respond(404, {"code": "not_found"})
            return
        keys = self.headers.get_all("Idempotency-Key", [])
        if len(keys) != 1 or not KEY_PATTERN.fullmatch(keys[0]):
            self.respond(400, {"code": "invalid_idempotency_key"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1:
            self.respond(400, {"code": "content_length_required"})
            return
        if self.headers.get("Content-Type") != "application/json":
            self.respond(415, {"code": "json_required"})
            return
        try:
            length = int(lengths[0])
            if length <= 0 or length > MAX_BODY_BYTES:
                self.respond(413, {"code": "body_limit"})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self.respond(400, {"code": "incomplete_body"})
                return
            request = RefundRequest.model_validate_json(body)
        except (ValueError, ValidationError, TimeoutError):
            self.respond(422, {"code": "invalid_request"})
            return
        status, result, created = refund(self.server.database, keys[0], request)
        if created and self.server.should_drop():
            # This deliberately produces an actual client-side transport exception.
            self.close_connection = True
            with contextlib.suppress(OSError):
                self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.respond(status, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--drop-after-commit", type=int, default=0)
    parser.add_argument("--hide-operations", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or not 0 <= args.drop_after_commit <= 100:
        parser.error("port or fault count outside supported range")
    with RefundServer(
        args.port, args.database, args.drop_after_commit, args.hide_operations
    ) as server:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready = {"pid": os.getpid(), "base_url": f"http://127.0.0.1:{server.server_port}"}
        temporary = args.ready_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(ready))
        temporary.replace(args.ready_file)
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    main()
