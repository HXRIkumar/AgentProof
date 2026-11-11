"""SQLite journal and simulated effect ledger. No real payments are performed."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, scenario TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS effects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    effect_key TEXT NOT NULL, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 0, policy_version TEXT NOT NULL DEFAULT '',
                    UNIQUE(run_id, effect_key)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), approved INTEGER NOT NULL,
                    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS experiment_jobs (
                    experiment_id TEXT PRIMARY KEY REFERENCES experiments(id),
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save_run(self, run: dict, scenario: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,document,scenario) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                (run["id"], json.dumps(run), json.dumps(scenario)),
            )

    def get_run(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def get_scenario(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT scenario FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def effects(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM effects WHERE run_id=? ORDER BY id", (run_id,))
            ]

    @staticmethod
    def insert_effect(db, run_id, key, order_id, amount, approved=False, policy_version=""):
        db.execute(
            "INSERT OR IGNORE INTO effects(run_id,effect_key,order_id,amount_cents,approved,policy_version) "
            "VALUES(?,?,?,?,?,?)",
            (run_id, key, order_id, amount, int(approved), policy_version),
        )
        return dict(
            db.execute(
                "SELECT * FROM effects WHERE run_id=? AND effect_key=?", (run_id, key)
            ).fetchone()
        )

    def execute_refund(
        self, run_id, key, order_id, amount, approved=False, policy_version=""
    ) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            effect = self.insert_effect(db, run_id, key, order_id, amount, approved, policy_version)
            # A reused key with different arguments is a conflict, never an implicit success.
            if (effect["order_id"], effect["amount_cents"], effect["policy_version"]) != (
                order_id,
                amount,
                policy_version,
            ):
                raise ValueError("Idempotency key reused with different arguments")
            return effect

    def save_experiment(self, experiment: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO experiments(id,document) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                (experiment["id"], json.dumps(experiment)),
            )

    def get_experiment(self, experiment_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT document FROM experiments WHERE id=?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return json.loads(row[0])

    def experiments(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT document FROM experiments ORDER BY rowid DESC")
            ]

    @staticmethod
    def _experiment_row(db, experiment_id):
        row = db.execute("SELECT document FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return json.loads(row[0])

    @staticmethod
    def _write_experiment(db, experiment):
        db.execute(
            "UPDATE experiments SET document=? WHERE id=?",
            (json.dumps(experiment), experiment["id"]),
        )
        db.execute(
            "UPDATE experiment_jobs SET state=? WHERE experiment_id=?",
            (experiment["status"], experiment["id"]),
        )

    def enqueue_experiment(self, experiment: dict, limit: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            queued = db.execute(
                "SELECT COUNT(*) FROM experiment_jobs WHERE state='queued'"
            ).fetchone()[0]
            if queued >= limit:
                raise OverflowError("The experiment queue is full; wait for a job to finish")
            db.execute(
                "INSERT INTO experiments(id,document) VALUES(?,?)",
                (experiment["id"], json.dumps(experiment)),
            )
            db.execute(
                "INSERT INTO experiment_jobs(experiment_id,state) VALUES(?,'queued')",
                (experiment["id"],),
            )

    def claim_experiment(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT experiment_id FROM experiment_jobs WHERE state='queued' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            experiment = self._experiment_row(db, row[0])
            experiment["status"] = "running"
            self._write_experiment(db, experiment)
            return experiment

    def record_experiment_run(self, experiment_id, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            experiment = self._experiment_row(db, experiment_id)
            if run_id not in experiment["run_ids"]:
                experiment["run_ids"].append(run_id)
            self._write_experiment(db, experiment)
            return experiment

    def finish_experiment(self, experiment_id, status, error=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            experiment = self._experiment_row(db, experiment_id)
            if experiment["status"] in ("completed", "failed", "cancelled"):
                return experiment
            experiment["status"] = "cancelled" if experiment.get("cancel_requested") else status
            if error and experiment["status"] != "cancelled":
                experiment["error"] = error
            self._write_experiment(db, experiment)
            return experiment

    def cancel_experiment(self, experiment_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            experiment = self._experiment_row(db, experiment_id)
            if experiment["status"] not in ("completed", "failed", "cancelled"):
                experiment["cancel_requested"] = True
                if experiment["status"] == "queued":
                    experiment["status"] = "cancelled"
                self._write_experiment(db, experiment)
            return experiment

    def fail_interrupted_jobs(self):
        """Call only after acquiring the exclusive worker lease, never during request handling."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Also recover interrupted pre-queue (v0.1) synchronous experiments.
            rows = db.execute(
                "SELECT id FROM experiments WHERE json_extract(document, '$.status')='running'"
            ).fetchall()
            for row in rows:
                experiment = self._experiment_row(db, row[0])
                experiment["status"] = "failed"
                experiment["error"] = {
                    "type": "InterruptedExecution",
                    "message": "The server stopped during execution. Partial evidence is preserved; interrupted trials are never automatically replayed. Start a new experiment.",
                }
                self._write_experiment(db, experiment)
