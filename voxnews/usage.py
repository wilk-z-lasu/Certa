"""Persist preparation and writing attempts, including interrupted hosted requests."""

from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import sqlite3
from time import perf_counter
from uuid import uuid4


_active = ContextVar("hosted_usage", default=None)


def preparation_attempt(directory, mode, lookback_days):
    return _attempt(directory, mode, lookback_days)


def writer_attempt(directory, day):
    return _attempt(directory / "usage" / "days" / day, "openai", None)


@contextmanager
def _attempt(directory, mode, lookback_days):
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / "usage.sqlite3", timeout=60)) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS attempt(
                id TEXT PRIMARY KEY, started TEXT, mode TEXT, lookback_days INTEGER, status TEXT);
            CREATE TABLE IF NOT EXISTS request(
                id INTEGER PRIMARY KEY, attempt TEXT, stage TEXT, model TEXT,
                input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER, seconds REAL);
        """)
        aid = uuid4().hex
        with db:
            db.execute("INSERT INTO attempt VALUES(?,?,?,?,?)",
                       (aid, datetime.now(timezone.utc).isoformat(), mode, lookback_days, "unfinished"))
        token = _active.set((db, aid))
        try:
            yield aid
        except Exception:
            with db:
                db.execute("UPDATE attempt SET status='failed' WHERE id=?", (aid,))
            raise
        else:
            with db:
                db.execute("UPDATE attempt SET status='completed' WHERE id=?", (aid,))
        finally:
            _active.reset(token)


def provider_response(request, opener, *, stage, model, timeout):
    """Record a pending charge before transmission. Missing receipts have unknown cost."""
    active = _active.get()
    if active:
        db, aid = active
        with db:
            rid = db.execute("INSERT INTO request(attempt,stage,model) VALUES(?,?,?)",
                             (aid, stage, model)).lastrowid
    start = perf_counter()
    with opener(request, timeout=timeout) as response:
        data = json.load(response)
    if active:
        usage = data.get("usage") or {}
        inputs = usage.get("input_tokens", usage.get("prompt_tokens"))
        outputs = 0 if stage == "embedding" else usage.get("output_tokens")
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        with db:
            db.execute("UPDATE request SET input_tokens=?,cached_tokens=?,output_tokens=?,seconds=? WHERE id=?",
                       (inputs, cached, outputs, perf_counter() - start, rid))
    return data


def history(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        attempts = [dict(row) for row in db.execute("SELECT * FROM attempt ORDER BY started")]
        rows = db.execute("""
            SELECT stage,model,count(*) calls,sum(input_tokens) input_tokens,
                   sum(cached_tokens) cached_tokens,sum(output_tokens) output_tokens,
                   sum(seconds) seconds,sum(input_tokens IS NULL OR output_tokens IS NULL) unmetered_calls
            FROM request GROUP BY stage,model ORDER BY stage,model
        """)
        return attempts, [dict(row) for row in rows]
