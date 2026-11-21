"""Import licensed feeds into an internal, revisioned source store."""

from collections import Counter
from contextlib import closing
import json
import sqlite3
import zlib

from .categorization import categorize_article
from .group_events import indexed_jsonl, timestamp, write_jsonl
from .luna import canonical_json
from .official_releases import digest, safe_url


SCHEMA = """
CREATE TABLE IF NOT EXISTS story_version(
    revision TEXT PRIMARY KEY, article_id TEXT NOT NULL, feed TEXT NOT NULL, raw BLOB NOT NULL,
    classification TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS story_history ON story_version(article_id);
CREATE TABLE IF NOT EXISTS source_import(id TEXT PRIMARY KEY, members TEXT NOT NULL);
"""


def import_feeds(directory, store, reviewer=None):
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise ValueError(f"No JSONL feeds in {directory}")
    if directory.resolve() in store.resolve().parents:
        raise ValueError("Keep the internal database outside the input directory")
    store.parent.mkdir(parents=True, exist_ok=True)
    members, seen, counts = [], set(), Counter()
    inserted = 0
    with closing(sqlite3.connect(store)) as db:
        db.executescript(SCHEMA)
        with db:
            for feed in files:
                for location, raw, _, _ in indexed_jsonl(feed):
                    try:
                        category = categorize_article(raw)
                        aid = category["article_id"]
                        if aid in seen:
                            raise ValueError("duplicate article ID")
                        timestamp(raw["date"])
                        safe_url(raw["permalink"])
                        if not isinstance(raw.get("text_content"), str):
                            raise ValueError("missing source text")
                        if not (raw.get("publication") or {}).get("name"):
                            raise ValueError("missing publisher")
                        if reviewer:
                            category = reviewer.apply(raw, category)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        raise ValueError(f"{location}: {exc}") from exc
                    seen.add(aid)
                    revision = digest([feed.name, raw, category])
                    members.append(revision)
                    counts[feed.name] += 1
                    if not db.execute("SELECT 1 FROM story_version WHERE revision=?", (revision,)).fetchone():
                        db.execute(
                            "INSERT INTO story_version VALUES(?,?,?,?,?)",
                            (
                                revision,
                                aid,
                                feed.name,
                                zlib.compress(canonical_json(raw).encode()),
                                canonical_json(category),
                            ),
                        )
                        inserted += 1
            edition = digest(members)
            db.execute("INSERT OR IGNORE INTO source_import VALUES(?,?)", (edition, canonical_json(members)))
    return {"edition": edition, "feeds": dict(counts), "articles": len(members), "new_versions": inserted}


def export_import(store, edition, destination):
    """Materialize exactly one immutable import for the existing JSONL stage interfaces."""
    with closing(sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute(
            """SELECT s.feed,s.raw,s.classification FROM source_import i, json_each(i.members) m
            JOIN story_version s ON s.revision=m.value WHERE i.id=? ORDER BY m.key""",
            (edition,),
        )
        by_feed, categories = {}, []
        for feed, raw, classification in rows:
            by_feed.setdefault(feed, []).append(json.loads(zlib.decompress(raw)))
            categories.append(json.loads(classification))
        if not categories:
            raise ValueError("Empty or unknown source import")
        for feed, articles in by_feed.items():
            write_jsonl(destination / "feeds" / feed, articles)
        write_jsonl(destination / "categories.jsonl", categories)
