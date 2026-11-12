"""Separate local answer history. Existing agent-workflow evidence is untouched."""

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class AnswerStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS answer_runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, body TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS answer_cache (
                scope TEXT NOT NULL, question TEXT NOT NULL, created_at REAL NOT NULL,
                run_id TEXT NOT NULL, vector TEXT, body TEXT NOT NULL,
                PRIMARY KEY(scope, question))""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, result):
        body = json.dumps(result, ensure_ascii=False, allow_nan=False)
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO answer_runs VALUES (?, ?, ?)",
                (result["id"], result["created_at"], body),
            )

    def get(self, run_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT body FROM answer_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def recent(self, limit=50):
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT body FROM answer_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(100, limit)),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def cached(self, scope, question, ttl):
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT body, run_id FROM answer_cache
                WHERE scope=? AND question=? AND created_at>=?""",
                (scope, question, time.time() - ttl),
            ).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def candidates(self, scope, ttl):
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT question, vector, body, run_id FROM answer_cache
                WHERE scope=? AND created_at>=? AND vector IS NOT NULL
                ORDER BY created_at DESC LIMIT 100""",
                (scope, time.time() - ttl),
            ).fetchall()
        return [
            (question, json.loads(vector), json.loads(body), run_id)
            for question, vector, body, run_id in rows
        ]

    def cache(self, scope, question, vector, result):
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO answer_cache VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scope,
                    question,
                    time.time(),
                    result["id"],
                    json.dumps(vector) if vector is not None else None,
                    json.dumps(result, ensure_ascii=False, allow_nan=False),
                ),
            )
            # Bounded local cache; history is separate and retained for inspection.
            db.execute("""DELETE FROM answer_cache WHERE rowid IN (
                SELECT rowid FROM answer_cache ORDER BY created_at DESC LIMIT -1 OFFSET 2000)""")
