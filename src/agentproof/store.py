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
