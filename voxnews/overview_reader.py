"""Select an editorial packet or display a claim's complete public source log."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import sqlite3
import zlib

from .event_candidates import fingerprint
from .official_releases import digest, safe_url
from .overview_material import SECTIONS


def connect(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def source_directory(db):
    location = json.loads(db.execute("SELECT metadata FROM build_info WHERE id=1").fetchone()[0])["directory"]
    path = next(path for _, name, path in db.execute("PRAGMA database_list") if name == "main")
    return (Path(path).parent / location).resolve()


def catalogue(db, *, topic=None, region=None, query="", disputes=False):
    clauses, values = [], []
    for col, value in (("topics", topic), ("regions", region)):
        if value:
            clauses.append(f"EXISTS (SELECT 1 FROM json_each(c.{col}) WHERE value=?)")
            values.append(value)
    if query:
        clauses.append("(instr(lower(title),lower(?))>0 OR c.event_id=?)")
        values.extend([query, query])
    if disputes:
        clauses.append("issues>0")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute("SELECT event_id,revision,title,topics,regions,latest,issues FROM catalogue c"
                      + where + " ORDER BY latest DESC,event_id", values)
    return [{"event_id": r[0], "revision": r[1], "title": r[2], "topics": json.loads(r[3]), "regions": json.loads(r[4]),
             "latest": r[5], "disagreements": r[6]} for r in rows]


def get_event(db, event_id, revision=None):
    if revision:
        row = db.execute("SELECT dossier FROM overview_revision WHERE event_id=? AND revision=?", (event_id, revision)).fetchone()
    else:
        row = db.execute("SELECT dossier FROM catalogue JOIN overview_revision USING(event_id,revision) WHERE event_id=?",
                         (event_id,)).fetchone()
    if row is None:
        raise ValueError("unknown event or overview revision")
    return json.loads(zlib.decompress(row[0]))


class Passages:
    """Resolve only the rows needed for this packet and check the source edition."""

    def __init__(self, db):
        self.db = db
        self.root = source_directory(db)
        self.rows = {}

    def text(self, ref, sources):
        aid = ref["source_id"]
        if aid not in self.rows:
            root = self.root
            old = None
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='source_location_version'").fetchone():
                old = self.db.execute("SELECT directory,feed_file,offset,size FROM source_location_version "
                                      "WHERE article_id=? AND fields=? AND url=?",
                                      (aid, digest(sources[aid]["field_hashes"]), sources[aid]["url"])).fetchone()
            if old:
                directory, path, offset, size = old
                main = next(p for _, name, p in self.db.execute("PRAGMA database_list") if name == "main")
                root = Path(main).parent / directory
            else:
                path, offset, size = self.db.execute("SELECT feed_file,offset,size FROM article_location WHERE article_id=?",
                                                    (aid,)).fetchone()
            if Path(path).name != path:
                raise ValueError("invalid local feed filename")
            with (root / path).open("rb") as f:
                f.seek(offset)
                row = json.loads(f.read(size))
            if row["$id"] != aid or row["permalink"] != sources[aid]["url"] or any(
                    fingerprint(row.get(k) or "") != h for k, h in sources[aid]["field_hashes"].items()):
                raise ValueError(f"source edition has changed for {aid}; rebuild or restore the original feed")
            self.rows[aid] = row
        text = self.rows[aid][ref["field"]][ref["start"]:ref["end"]]
        if digest(text) != ref["span_hash"]:
            raise ValueError(f"evidence span has changed for {aid}")
        return text


def source_log(event, item):
    rows = [{**event["sources"][r["source_id"]], **r} for r in item["evidence"]]
    used = {r["source_id"] for r in rows}
    rows.extend({**event["sources"][sid], "source_id": sid, "role": "examined"}
                for sid in item.get("examined_source_ids", []) if sid not in used)
    return rows


def select(event, depth="standard", focus=(), language="en"):
    """Round-robin over facets, then diversify origins and prefer the requested source language."""
    if depth not in {"brief", "standard", "technical", "full"} or set(focus) - set(SECTIONS):
        raise ValueError("invalid depth or editorial focus")
    candidates = [i for i in event["items"] if i["draft_use"] not in {"review_only", "omit"}]
    if focus:
        candidates = [i for i in candidates if set(focus).intersection(i["sections"])]
    chosen, used, represented = [], set(), set()

    def take(pool):
        remaining = [i for i in pool if i["id"] not in used]
        if not remaining:
            return
        def rank(i):
            origins = {event["sources"][r["source_id"]].get("origin") for r in i["evidence"]}
            return (i["draft_use"] == "approved_wording", i["language"] == language,
                    bool(origins - represented), i["priority"])
        pick = max(remaining, key=rank)
        chosen.append(pick)
        used.add(pick["id"])
        represented.update(event["sources"][r["source_id"]].get("origin") for r in pick["evidence"])

    cap = {"brief": 3, "standard": 10, "technical": 30, "full": len(candidates)}[depth]
    sections = tuple(focus) or (("development", "mechanism", "figures", "timeline", "uncertainty", "outlook",
                                "reaction","implications","background") if depth == "technical" else SECTIONS)
    for section in sections:
        if len(chosen) >= cap:
            break
        take(i for i in candidates if section in i["sections"])
    # Keep the full option linear even for a large multi-publisher event.
    rest = sorted((i for i in candidates if i["id"] not in used),
                  key=lambda i: (i["language"] == language, i["priority"]), reverse=True)
    return chosen + rest[:max(0, cap-len(chosen))]


def packet(db, event, *, depth="technical", focus=(), language="en"):
    reader = Passages(db)
    selected = select(event, depth, focus, language)
    by_id = {i["id"]: i for i in event["items"]}

    def expand(item):
        row = dict(item)
        if item["type"] == "passage":
            ref = item["evidence"][0]
            row["source_statement"] = reader.text(ref, event["sources"])
            if ref.get("context_span"):
                start, end = ref["context_span"]
                row["source_context"] = reader.rows[ref["source_id"]][ref["field"]][start:end]
        return row

    # Conflicting positions are carried together regardless of focus or length budget.
    issue_ids = {k for d in event["disagreements"] for k in d["claim_ids"]}
    evidence = [expand(by_id[k]) for k in sorted(issue_ids)]
    held = [expand(i) for i in event["items"] if i["draft_use"] == "review_only" and i["id"] not in issue_ids]
    expanded = [expand(i) for i in selected]
    # The overview is readable independently of the technical ledger. Every
    # sentence keeps a direct pointer to its evidence, and retains its source language.
    key_points = {}
    for section in tuple(focus) or SECTIONS:
        point = next((i for i in expanded if section in i["sections"]), None)
        if point:
            key_points[point["id"]] = point
    synopsis = [{"claim_id": i["id"], "section": i["sections"][0], "language": i["language"],
                 "text": i.get("summary") or i.get("source_context") or i["source_statement"],
                 "source_ids": list(dict.fromkeys(r["source_id"] for r in i["evidence"])),
                 "draft_use": i["draft_use"], "qualifiers": i["qualifiers"]}
                for i in key_points.values()]
    return {"event_id": event["event_id"], "revision": event["revision"], "verification_revision": event["verification_revision"],
            "title": event["title"], "title_source_id": event["title_source_id"], "topics": event["topics"],
            "regions": event["regions"], "source_languages": event["languages"], "limitations": event["limitations"],
            "reporting_chronology": event["reporting_chronology"], "sources": event["sources"],
            "selection": {"depth": depth, "focus": list(focus), "preferred_source_language": language},
            "synopsis": synopsis, "scope_evidence": event["scope_evidence"],
            "editorial_use": "Internal research. Paraphrase source statements, retain qualifiers and attribution, "
                             "and verify the final wording. Preserve each claim ID when composing.",
            "items": expanded, "disagreements": event["disagreements"], "synthesis": event.get("synthesis"),
            "disputed_or_revised_material": evidence, "other_held_material": held}


def markdown(data):
    lines = ["# " + data["title"], "", data["editorial_use"], "",
             " · ".join(data["topics"]), "", f"Event `{data['event_id']}` · overview revision `{data['revision']}`", ""]
    sections = defaultdict(list)
    for item in data["items"]:
        name = next((s for s in data["selection"]["focus"] if s in item["sections"]), None)
        section = name or ("development" if item.get("is_lead") else item["sections"][0])
        sections[section].append(item)
    def card(item):
        fact = item.get("summary") or item.get("source_context") or item.get("source_statement") or json.dumps(item.get("fact"), ensure_ascii=False)
        qualifiers = ", ".join(item.get("qualifiers", []))
        lines.extend([fact, "", f"*{item['draft_use']} · {qualifiers or item['type']}* · `{item['id']}`", ""])
        for r in item["evidence"]:
            src = data["sources"][r["source_id"]]
            label = src.get("publisher") or src["issuer"]
            locator = r.get("locator") or f"{r['field']} [{r['start']}, {r['end']})"
            lines.append(f"- {r['role']} · [{label}]({src['url']}) · {locator}")
        lines.append("")
    for name, items in sections.items():
        lines.extend(["## " + name.title(), ""])
        for item in items:
            card(item)
    if data["disagreements"]:
        lines.extend(["## Disagreements and revisions", ""])
        for d in data["disagreements"]:
            lines.extend([f"- {d['kind']} · " + ", ".join(d["claim_ids"]), ""])
        for item in data["disputed_or_revised_material"]:
            card(item)
    if data["other_held_material"]:
        lines.extend(["## Other material requiring review", ""])
        for item in data["other_held_material"]:
            card(item)
    return "\n".join(lines)


def log_html(event):
    """Shareable claim/source log. Keep licensed body text in the internal writer packet."""
    def cite(ref):
        src = event["sources"][ref["source_id"]]
        locator = ref.get("locator") or f'{ref["field"]} [{ref["start"]}, {ref["end"]})'
        label = src.get("publisher") or src["issuer"]
        url = escape(safe_url(src["url"]), quote=True)
        return f'<li><a href="{url}">{escape(label)}</a> · {escape(ref["role"])} · {escape(locator)}</li>'
    def label(i):
        if i.get("summary"):
            return i["summary"]
        if i.get("fact"):
            return " · ".join(str(i["fact"][k]) for k in ("geo","measure","period","basis","value","unit"))
        labels = [*i["sections"], *i["qualifiers"]]
        values = [q["raw"] for q in i.get("quantities", [])]
        return " · ".join(dict.fromkeys(labels + values))
    def detail(i):
        refs = "".join(cite(r) for r in i["evidence"])
        used = {r["source_id"] for r in i["evidence"]}
        for sid in i.get("examined_source_ids", []):
            if sid not in used:
                src = event["sources"][sid]
                refs += f'<li><a href="{escape(safe_url(src["url"]), quote=True)}">{escape(src["publisher"])}</a> · examined</li>'
        state = i.get("evidence_state",i.get("article_state"))
        basis = i.get("reasons",[]) or (["direct article evidence"] if state == "supported" else [])
        status = [s for s in (state,i.get("official_state"),*basis,i["draft_use"]) if s]
        return (f'<details id="c{i["id"]}"><summary>{escape(label(i))}</summary>'
                f'<p>{escape(" · ".join(status))}</p><ul>{refs}</ul><small>Claim {escape(i["id"])}</small></details>')
    conflicts = []
    for issue in event["disagreements"]:
        links = " · ".join(f'<a href="#c{escape(cid)}">Position {n}</a>' for n, cid in enumerate(issue["claim_ids"], 1))
        conflicts.append(f'<li>{escape(issue["kind"])} · {links}</li>')
    title = escape(event["title"])
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{title} | VoxNews sources</title><style>body{{max-width:52rem;margin:3rem auto;padding:0 1rem;'
            'font:16px/1.55 system-ui;color:#19322e;background:#fafbf8}h1{font:2.3rem Georgia,serif}a{color:#065e56}'
            'details{padding:.7rem 0;border-top:1px solid #cbd5d1}summary{cursor:pointer}small{overflow-wrap:anywhere}'
            '</style><main><small>VoxNews · Event source log</small>'
            f'<h1>{title}</h1><p>{escape(" · ".join(event["topics"]))}</p>'
            f'<p>Revision <small>{escape(event["revision"])}</small></p>'
            + ('<h2>Disagreements and revisions</h2><ul>'+"".join(conflicts)+'</ul>' if conflicts else '')
            + '<h2>Claim evidence</h2>'+ "".join(detail(i) for i in event["items"]) + '</main></html>')
