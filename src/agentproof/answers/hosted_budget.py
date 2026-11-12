"""Durable conservative request reservations; this is not an OpenAI billing limit.

All production invocations share one file. Unknown outcomes retain their full
reservation, including across restarts. There is intentionally no reset/release API.
"""

import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from contextlib import closing
from pathlib import Path

MODEL = "gpt-5.4-mini-2026-03-17"
BASE_URL = "https://api.openai.com/v1"
MAX_BUDGET_NANOUSD = 1_500_000_000
INPUT_NANOUSD_PER_TOKEN = 750
OUTPUT_NANOUSD_PER_TOKEN = 4500
PRICING_VERSION = "openai-gpt-5.4-mini-standard-2026-11-12"
PRICING = {
    "version": PRICING_VERSION,
    "model": MODEL,
    "input_usd_per_million": 0.75,
    "output_usd_per_million": 4.50,
    "cached_input_discount_applied": False,
    "service_tier": "default",
    "source": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
}


class BudgetError(RuntimeError):
    """Messages are fixed safe labels, never SQL paths, keys or request bodies."""

    def __init__(self, message, *, code="budget_guard"):
        super().__init__(message)
        self.code = code


def default_ledger_path():
    return Path.home() / ".config" / "agentproof" / "hosted-budget.sqlite3"


def dollars(nanodollars):
    return nanodollars / 1_000_000_000


def input_token_bound(messages: list[dict]) -> int:
    """Byte-based text bound plus deliberately generous framing overhead.

    This is an application-side conservative estimate, not provider-attested token
    counting. Only bounded role/content strings are accepted: no tools, images,
    remote files, names, multiple choices or unpriced modalities.
    """
    if not isinstance(messages, list) or not 1 <= len(messages) <= 16:
        raise BudgetError("Hosted request must contain 1–16 text messages")
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in {"system", "developer", "user", "assistant"}
            or not isinstance(message["content"], str)
        ):
            raise BudgetError("Hosted requests support text role/content messages only")
    encoded = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 200_000:
        raise BudgetError("Hosted text exceeds the request byte limit")
    return len(encoded) + 2048 + 256 * len(messages)


def estimate_nanodollars(input_tokens: int, output_tokens: int) -> int:
    if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
        raise BudgetError("Invalid token accounting")
    return input_tokens * INPUT_NANOUSD_PER_TOKEN + output_tokens * OUTPUT_NANOUSD_PER_TOKEN


def load_openai_key(path=None):
    """Called only immediately before an explicitly enabled paid request."""
    value = os.getenv("OPENAI_API_KEY")
    if value is None:
        file_path = (
            Path(path)
            if path is not None
            else (Path.home() / ".config" / "agentproof" / "openai-key")
        )
        try:
            fd = os.open(file_path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077
                    or info.st_size > 4096
                ):
                    raise BudgetError("OpenAI key file must be a private owner-only regular file")
                value = stream.read(4097)
        except (OSError, UnicodeError):
            raise BudgetError("OpenAI key is unavailable; use the secure setup helper") from None
    value = value.strip()
    if not value or len(value) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise BudgetError("OpenAI key is missing or malformed")
    return value


class BudgetLedger:
    def __init__(self, path=None, *, ceiling_nanodollars=MAX_BUDGET_NANOUSD):
        if (
            type(ceiling_nanodollars) is not int
            or not 0 < ceiling_nanodollars <= MAX_BUDGET_NANOUSD
        ):
            raise BudgetError("Hosted budget ceiling must be positive and at most USD 1.50")
        self.path = Path(path) if path is not None else default_ledger_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        created = False
        try:
            descriptor = os.open(
                self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            os.close(descriptor)
            created = True
        except FileExistsError:
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise BudgetError(
                    "Hosted budget ledger must be a private owner-only file"
                ) from None
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if created:
                    db.execute("""CREATE TABLE budget_meta (
                        id INTEGER PRIMARY KEY CHECK(id=1), ledger_id TEXT NOT NULL,
                        ceiling_nano INTEGER NOT NULL, frozen INTEGER NOT NULL DEFAULT 0,
                        pricing TEXT NOT NULL)""")
                    db.execute("""CREATE TABLE reservations (
                        id TEXT PRIMARY KEY, created REAL NOT NULL, purpose TEXT NOT NULL,
                        request_hash TEXT NOT NULL, input_bound INTEGER NOT NULL,
                        output_bound INTEGER NOT NULL, reserved_nano INTEGER NOT NULL,
                        accounted_nano INTEGER NOT NULL, state TEXT NOT NULL,
                        reported_input INTEGER, reported_output INTEGER,
                        estimated_nano INTEGER, reason TEXT)""")
                    db.execute(
                        "INSERT INTO budget_meta VALUES (1, ?, ?, 0, ?)",
                        (
                            uuid.uuid4().hex,
                            ceiling_nanodollars,
                            json.dumps(PRICING, sort_keys=True),
                        ),
                    )
                meta = db.execute("SELECT * FROM budget_meta WHERE id=1").fetchone()
                if meta is None or json.loads(meta["pricing"]) != PRICING:
                    raise BudgetError("Hosted ledger pricing identity does not match this adapter")
                if ceiling_nanodollars < meta["ceiling_nano"]:
                    db.execute(
                        "UPDATE budget_meta SET ceiling_nano=? WHERE id=1", (ceiling_nanodollars,)
                    )
                # Higher configured values never raise an existing lower ceiling.
        except sqlite3.Error:
            raise BudgetError(
                "Hosted budget ledger is unavailable or invalid; request blocked"
            ) from None

    def _connect(self):
        # mode=rw fails closed if the ledger is removed after construction.
        db = sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        return db

    def snapshot(self):
        try:
            with closing(self._connect()) as db:
                meta = db.execute("SELECT * FROM budget_meta WHERE id=1").fetchone()
                totals = db.execute("""SELECT COUNT(*) n, COALESCE(SUM(accounted_nano),0) accounted,
                    COALESCE(SUM(estimated_nano),0) estimated,
                    SUM(CASE WHEN state IN ('reserved','uncertain') THEN 1 ELSE 0 END) uncertain
                    FROM reservations""").fetchone()
                return {
                    "ledger_id": meta["ledger_id"],
                    "ceiling_usd": dollars(meta["ceiling_nano"]),
                    "accounted_usd": dollars(totals["accounted"]),
                    "reported_usage_estimate_usd": dollars(totals["estimated"]),
                    "remaining_reservable_usd": dollars(
                        max(0, meta["ceiling_nano"] - totals["accounted"])
                    ),
                    "reservations": totals["n"],
                    "unresolved_reservations": totals["uncertain"] or 0,
                    "frozen": bool(meta["frozen"]),
                    "pricing": PRICING,
                    "scope": "Conservative local request guard, not an account billing cap",
                }
        except sqlite3.Error:
            raise BudgetError("Hosted budget ledger unavailable; request blocked") from None

    def reserve(self, messages, max_output_tokens, purpose):
        if type(max_output_tokens) is not int or not 64 <= max_output_tokens <= 4096:
            raise BudgetError("Hosted output budget must be 64–4096 tokens including reasoning")
        if purpose not in {"generate", "refine", "critic", "escalate"}:
            raise BudgetError("Unsupported hosted request purpose")
        input_bound = input_token_bound(messages)
        amount = estimate_nanodollars(input_bound, max_output_tokens)
        identifier = uuid.uuid4().hex
        fingerprint = hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                meta = db.execute("SELECT * FROM budget_meta WHERE id=1").fetchone()
                accounted = db.execute(
                    "SELECT COALESCE(SUM(accounted_nano),0) FROM reservations"
                ).fetchone()[0]
                if meta["frozen"]:
                    raise BudgetError("Hosted ledger is frozen after a bound or pricing mismatch")
                if accounted + amount > min(MAX_BUDGET_NANOUSD, meta["ceiling_nano"]):
                    raise BudgetError(
                        "Hosted budget exhausted; no request was sent", code="budget_exhausted"
                    )
                db.execute(
                    """INSERT INTO reservations VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved',
                    NULL, NULL, NULL, NULL)""",
                    (
                        identifier,
                        time.time(),
                        purpose,
                        fingerprint,
                        input_bound,
                        max_output_tokens,
                        amount,
                        amount,
                    ),
                )
            return self.reservation(identifier)
        except sqlite3.Error:
            raise BudgetError("Could not reserve hosted budget; no request was sent") from None

    def reservation(self, identifier):
        try:
            with closing(self._connect()) as db:
                row = db.execute("SELECT * FROM reservations WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise BudgetError("Hosted reservation is missing")
                return {
                    "provider": "openai",
                    "reservation_id": row["id"],
                    "state": row["state"],
                    "reserved_usd": dollars(row["reserved_nano"]),
                    "accounted_usd": dollars(row["accounted_nano"]),
                    "estimated_cost_usd": dollars(row["estimated_nano"])
                    if row["estimated_nano"] is not None
                    else None,
                    "input_token_bound": row["input_bound"],
                    "max_output_tokens": row["output_bound"],
                    "reported_prompt_tokens": row["reported_input"],
                    "reported_completion_tokens": row["reported_output"],
                    "pricing_version": PRICING_VERSION,
                    "reason": row["reason"],
                }
        except sqlite3.Error:
            raise BudgetError("Hosted reservation unavailable") from None

    def settle(
        self,
        identifier,
        *,
        prompt_tokens=None,
        completion_tokens=None,
        response_model=None,
        service_tier=None,
    ):
        known = all(
            type(value) is int and 0 <= value <= 1_000_000_000
            for value in (prompt_tokens, completion_tokens)
        )
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM reservations WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise BudgetError("Hosted reservation is missing")
                if row["state"] != "reserved":
                    # No later retry can release an uncertain reservation or lower a
                    # prior charge; normal settlement is intentionally one-way.
                    return self.reservation(identifier)
                identity_ok = response_model == MODEL and service_tier == "default"
                bounds_ok = (
                    known
                    and prompt_tokens <= row["input_bound"]
                    and completion_tokens <= row["output_bound"]
                )
                estimated = (
                    estimate_nanodollars(prompt_tokens, completion_tokens) if known else None
                )
                if identity_ok and bounds_ok:
                    state, reason, accounted = "settled", None, estimated
                elif (
                    not known
                    and (response_model is None or response_model == MODEL)
                    and (service_tier is None or service_tier == "default")
                ):
                    state, reason, accounted = (
                        "uncertain",
                        "Usage not established; reservation retained",
                        row["reserved_nano"],
                    )
                else:
                    state, reason = "overrun", "Provider identity, tier or token bound mismatch"
                    accounted = max(row["reserved_nano"], estimated or 0)
                    db.execute("UPDATE budget_meta SET frozen=1 WHERE id=1")
                db.execute(
                    """UPDATE reservations SET state=?, accounted_nano=?,
                    reported_input=?, reported_output=?, estimated_nano=?, reason=? WHERE id=?""",
                    (
                        state,
                        accounted,
                        prompt_tokens if known else None,
                        completion_tokens if known else None,
                        estimated,
                        reason,
                        identifier,
                    ),
                )
            return self.reservation(identifier)
        except sqlite3.Error:
            raise BudgetError(
                "Hosted settlement failed; original reservation remains held"
            ) from None
