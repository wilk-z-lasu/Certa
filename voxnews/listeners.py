"""Versioned listener settings, delivered editions and reversible daily feedback."""

from contextlib import contextmanager
import json
import sqlite3
from secrets import token_hex

from build_preai import preferences
from .luna import canonical_json
from .official_releases import digest
from .topic_rules import TOPICS


DEPTHS = ("headlines", "standard", "detailed")
PERSONAS = {
    "technology": ("Maya", {"topics": ["technology_ai", "companies_stocks"],
        "minutes": 3, "depth": "headlines", "weights": {"technology_ai": 2}}),
    "macro": ("Ellis", {"topics": ["economy_central_banks", "currencies"],
        "minutes": 8, "depth": "detailed", "weights": {"economy_central_banks": 2}}),
    "noor": ("Noor", {"topics": ["economy_central_banks", "politics_world", "other_news"],
        "region": "NL", "language": "nl", "minutes": 4, "depth": "standard"}),
    "jonas": ("Jonas", {"topics": ["companies_stocks", "economy_central_banks"],
        "region": "DE", "language": "de", "minutes": 6, "depth": "detailed", "weights": {"companies_stocks": 2}}),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS person(
 browser TEXT, id TEXT, name TEXT NOT NULL, PRIMARY KEY(browser,id));
CREATE TABLE IF NOT EXISTS removed_person(
 browser TEXT, id TEXT, PRIMARY KEY(browser,id));
CREATE TABLE IF NOT EXISTS profile(
 listener TEXT, version INTEGER, settings TEXT NOT NULL, reason TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(listener,version));
CREATE TABLE IF NOT EXISTS composition_job(
 listener TEXT, day TEXT, owner TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY(listener,day));
CREATE TABLE IF NOT EXISTS delivery(
 listener TEXT, day TEXT, edition TEXT NOT NULL, version INTEGER NOT NULL, draft TEXT NOT NULL,
 briefing TEXT NOT NULL, PRIMARY KEY(listener,day), UNIQUE(listener,edition),
 FOREIGN KEY(listener,version) REFERENCES profile(listener,version));
CREATE TABLE IF NOT EXISTS feedback(
 listener TEXT, edition TEXT, answers TEXT NOT NULL, applied_version INTEGER NOT NULL,
 before_version INTEGER NOT NULL, undone INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(listener,edition),
 FOREIGN KEY(listener,edition) REFERENCES delivery(listener,edition));
"""


class Conflict(ValueError):
    pass


@contextmanager
def storage(directory):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "listeners.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        with db:
            yield db
    finally:
        db.close()


def settings(data):
    if not isinstance(data, dict):
        raise ValueError("Expected listener settings.")
    result = preferences(data.get("topics"), data.get("region"), data.get("language", "en"))
    duration = data.get("minutes", 3)
    depth = data.get("depth", "standard")
    weights = data.get("weights", {})
    if type(duration) != int or not 1 <= duration <= 10 or depth not in DEPTHS:
        raise ValueError("Choose 1–10 minutes and a listed depth.")
    if not isinstance(weights, dict) or any(
        t not in TOPICS or type(w) != int or abs(w) > 2 for t, w in weights.items()
    ):
        raise ValueError("Topic weights must be integers from −2 to 2.")
    return {**result, "minutes": duration, "depth": depth, "weights": {t: w for t, w in weights.items() if w}}


def current(db, listener):
    row = db.execute(
        "SELECT * FROM profile WHERE listener=? ORDER BY version DESC LIMIT 1", (listener,)
    ).fetchone()
    return unpack(row) if row else None


def people(db, browser, *, include_legacy=False):
    removed = {row[0] for row in db.execute("SELECT id FROM removed_person WHERE browser=?", (browser,))}
    profiles = [{"id": key, "name": name} for key, (name, _) in PERSONAS.items()] + [
        dict(row) for row in db.execute(
            "SELECT id,name FROM person WHERE browser=? ORDER BY name COLLATE NOCASE,id", (browser,)
        )
    ]
    if include_legacy and current(db, browser):
        profiles.insert(0, {"id": "", "name": "My profile"})
    return [p for p in profiles if p["id"] not in removed]


def remove_person(db, browser, persona):
    if not isinstance(persona, str) or not any(p["id"] == persona for p in people(db, browser, include_legacy=True)):
        raise ValueError("Unknown listener profile.")
    db.execute("INSERT INTO removed_person(browser,id) VALUES (?,?)", (browser, persona))


def scope(db, browser, persona=None):
    if db.execute("SELECT 1 FROM removed_person WHERE browser=? AND id=?", (browser, persona or "")).fetchone():
        raise ValueError("Unknown listener profile.")
    if not persona:
        return browser
    if persona not in PERSONAS and not db.execute(
        "SELECT 1 FROM person WHERE browser=? AND id=?", (browser, persona)
    ).fetchone():
        raise ValueError("Unknown listener profile.")
    return digest([browser, persona])


def add_person(db, browser, name, preferences):
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 60 or any(not c.isprintable() for c in name):
        raise ValueError("Enter a name of 1–60 characters.")
    persona = token_hex(16)
    db.execute("INSERT INTO person VALUES (?,?,?)", (browser, persona, name))
    listener = scope(db, browser, persona)
    profile = revise(db, listener, preferences, "New listener")
    return {"id": persona, "name": name, "profile": profile}


def persona_profile(db, browser, persona=None):
    profile = current(db, scope(db, browser, persona))
    if profile is None and persona in PERSONAS:
        return {**settings(PERSONAS[persona][1]), "version": 0}
    return profile


def unpack(row):
    return {
        **json.loads(row["settings"]),
        "version": row["version"],
        "reason": row["reason"],
        "created": row["created"],
    }


def revise(db, listener, new, reason, version=None):
    old = current(db, listener)
    previous = old["version"] if old else 0
    if version is not None and version != previous:
        raise Conflict("Your settings have changed. Reload before saving.")
    clean = settings(new)
    if old and settings(old) == clean:
        return old
    db.execute(
        "INSERT INTO profile(listener,version,settings,reason) VALUES(?,?,?,?)",
        (listener, previous + 1, canonical_json(clean), reason),
    )
    return current(db, listener)


def delivered(db, listener, day):
    row = db.execute("SELECT briefing FROM delivery WHERE listener=? AND day=?", (listener, day)).fetchone()
    return json.loads(row[0]) if row else None


def previous_claims(db, listener, day):
    by_event, coverage, wording = {}, set(), set()
    for row in db.execute(
        "SELECT briefing FROM delivery WHERE listener=? AND day<? ORDER BY day", (listener, day)
    ):
        for s in json.loads(row[0])["segments"]:
            by_event.setdefault(s["event_id"], set()).add(s["claim_id"])
            wording.add(s["text"].casefold())
            if s.get("coverage_id"):
                coverage.add(s["coverage_id"])
    return {"by_event": by_event, "coverage": coverage, "wording": wording}


def record_delivery(db, listener, draft, briefing):
    edition = digest([listener, draft["id"], briefing])
    result = {
        **briefing,
        "edition": edition,
        "date": draft["date"],
        "draft_id": draft["id"],
        "profile_version": draft["profile_version"],
        "coverage": draft["coverage"],
        "cutoff_exclusive": draft["cutoff_exclusive"],
    }
    db.execute(
        "INSERT INTO delivery VALUES(?,?,?,?,?,?)",
        (
            listener,
            draft["date"],
            edition,
            draft["profile_version"],
            canonical_json(draft),
            canonical_json(result),
        ),
    )
    return result


def check_in(db, listener, edition, answers, undo=False):
    if not db.execute(
        "SELECT 1 FROM delivery WHERE listener=? AND edition=?", (listener, edition)
    ).fetchone():
        raise ValueError("Unknown briefing for this listener.")
    prior = db.execute(
        "SELECT * FROM feedback WHERE listener=? AND edition=?", (listener, edition)
    ).fetchone()
    profile = current(db, listener)
    if undo:
        if not prior:
            raise ValueError("No feedback to undo.")
        if prior["undone"] or prior["applied_version"] == prior["before_version"]:
            return profile
        if profile["version"] != prior["applied_version"]:
            raise Conflict("Later profile changes exist. Edit your current settings to keep those changes.")
        old = db.execute(
            "SELECT * FROM profile WHERE listener=? AND version=?", (listener, prior["before_version"])
        ).fetchone()
        profile = revise(db, listener, unpack(old), "undo feedback")
        db.execute("UPDATE feedback SET undone=1 WHERE listener=? AND edition=?", (listener, edition))
        return profile
    if not isinstance(answers, dict) or set(answers) - {"useful", "length", "depth", "more", "less", "skip"}:
        raise ValueError("Invalid feedback fields.")
    if prior:
        if prior["answers"] != canonical_json(answers):
            raise Conflict("Feedback already recorded.")
        return profile
    before = profile["version"]
    changes = []
    new = settings(profile)
    if answers != {"skip": True}:
        if "skip" in answers or answers.get("useful") not in (None, "yes", "no"):
            raise ValueError("Invalid check-in.")
        for name, key, steps in (("length", "minutes", list(range(1, 11))), ("depth", "depth", list(DEPTHS))):
            direction = answers.get(name, "same")
            if direction not in ("less", "same", "more"):
                raise ValueError("Choose less, same or more.")
            index = steps.index(new[key]) + {"less": -1, "same": 0, "more": 1}[direction]
            new[key] = steps[max(0, min(len(steps) - 1, index))]
            if new[key] != profile[key]:
                changes.append(f"{key} → {new[key]}")
        more, less = answers.get("more", []), answers.get("less", [])
        if any(not isinstance(items, list) or any(t not in TOPICS for t in items) for items in (more, less)):
            raise ValueError("Choose listed feedback topics.")
        if set(more) & set(less):
            raise ValueError("Choose one direction per topic.")
        for topics, step in ((more, 1), (less, -1)):
            for t in sorted(set(topics)):
                w = max(-2, min(2, new["weights"].get(t, 0) + step))
                new["weights"][t] = w
                if step > 0 and t not in new["topics"]:
                    new["topics"].append(t)
                changes.append(f"{t} → {w:+d}")
        profile = revise(db, listener, new, "Daily feedback: " + ", ".join(changes))
    db.execute(
        "INSERT INTO feedback VALUES(?,?,?,?,?,0)",
        (listener, edition, canonical_json(answers), profile["version"], before),
    )
    return profile
