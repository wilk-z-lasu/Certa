"""Reserve a listener's composition work and publish an immutable daily text."""

from contextlib import nullcontext
from secrets import token_hex
from time import time, perf_counter

from build_preai import database_path
from generate_script import compose_draft, validate_daily
from .editions import personal_draft
from .listeners import Conflict, current, delivered, previous_claims, record_delivery, storage
from . import providers
from .usage import writer_attempt


def compose_day(directory, listener, day, expected_version=None):
    owner = token_hex(16)
    with storage(directory) as db:
        db.execute("BEGIN IMMEDIATE")
        existing = delivered(db, listener, day)
        if existing is not None:
            if providers.cloud_only() and (existing.get("provider") != "openai" or not existing.get("cloud_only")):
                raise Conflict("This saved edition used local or offline processing. Use the isolated cloud demo.")
            return existing
        profile = current(db, listener)
        if not profile:
            raise ValueError("Save your preferences first.")
        if expected_version is not None and expected_version != profile["version"]:
            raise Conflict("Reload your updated preferences.")
        job = db.execute(
            "SELECT expires FROM composition_job WHERE listener=? AND day=?", (listener, day)
        ).fetchone()
        if job and job["expires"] > time():
            raise Conflict("Your briefing is being prepared. Try again shortly.")
        history = previous_claims(db, listener, day)
        db.execute(
            "INSERT OR REPLACE INTO composition_job VALUES(?,?,?,?)",
            (listener, day, owner, int(time()) + 900),
        )
    try:
        start = perf_counter()
        draft = personal_draft(database_path(), profile, day, history)
        retrieval = perf_counter() - start
        hosted = not providers.local() and providers.api_key() and not providers.requests_paused()
        with writer_attempt(directory, draft["date"]) if hosted else nullcontext():
            briefing = compose_draft(draft, draft["selection"])
            validate_daily(draft, briefing)
        briefing["retrieval_seconds"] = round(retrieval, 3)
        with storage(directory) as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute(
                "SELECT owner FROM composition_job WHERE listener=? AND day=?", (listener, day)
            ).fetchone()
            if not lease or lease["owner"] != owner:
                raise Conflict("Another request is preparing this edition. Please retry.")
            if (
                current(db, listener)["version"] != profile["version"]
                or previous_claims(db, listener, day) != history
            ):
                raise Conflict(
                    "Your preferences or briefing history changed during composition. Please retry."
                )
            return record_delivery(db, listener, draft, briefing)
    finally:
        with storage(directory) as db:
            db.execute(
                "DELETE FROM composition_job WHERE listener=? AND day=? AND owner=?", (listener, day, owner)
            )
