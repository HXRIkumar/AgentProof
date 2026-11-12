import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class SupportStore:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS support_documents (
                  id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL,
                  version INTEGER NOT NULL, content_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL, active INTEGER NOT NULL,
                  page_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
                  text TEXT NOT NULL, pages_json TEXT NOT NULL, chunks_json TEXT NOT NULL,
                  UNIQUE(filename, version));
                CREATE UNIQUE INDEX IF NOT EXISTS support_active_filename
                  ON support_documents(filename) WHERE active=1;
                CREATE TABLE IF NOT EXISTS support_tickets (
                  id TEXT PRIMARY KEY, external_id TEXT UNIQUE, title TEXT NOT NULL,
                  body TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  category TEXT, priority TEXT, result_job_id TEXT, review_json TEXT);
                CREATE TABLE IF NOT EXISTS support_jobs (
                  id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
                  request_hash TEXT NOT NULL, strategy TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                  knowledge_revision TEXT NOT NULL, status TEXT NOT NULL, progress TEXT NOT NULL,
                  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                  cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT, result_json TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS support_active_ticket
                  ON support_jobs(ticket_id) WHERE status IN ('queued','running');
                CREATE INDEX IF NOT EXISTS support_queued ON support_jobs(status,created_at);
                CREATE TABLE IF NOT EXISTS support_events (
                  id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, type TEXT NOT NULL,
                  at TEXT NOT NULL, message TEXT NOT NULL, job_id TEXT);
            """)

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()
