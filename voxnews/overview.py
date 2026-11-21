"""Build reusable event dossiers from verification, categories and licensed local feeds."""

from collections import Counter, defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from time import perf_counter
import zlib

from .event_candidates import fingerprint
from .group_events import read_categories, timestamp
from .geography import classify_regions
from .luna import canonical_json
from .official_releases import digest, safe_url
from .overview_material import SECTIONS, passage_material
from .trust_briefing import attributed_wording, spoken
from .verify import load_feeds


VERSION = "event-overview-8"
FIELDS = ("headline", "excerpt", "text_content")


def source_record(ref, articles, categories):
    aid = ref["article_id"]
    a = articles[aid]
    if (a["body_hash"] != ref["body_hash"] or a["permalink"] != ref["permalink"]
            or a["publisher"] != ref["publisher"] or a["language"] != ref["language"]
            or timestamp(a["date"]) != timestamp(ref["published_at"])):
        raise ValueError(f"stale verification source {aid}")
    cat = categories[aid]
    if cat["permalink"] != a["permalink"] or cat["language"] != a["language"]:
        raise ValueError(f"stale category handoff for {aid}")
    # Each source gets one short display title. Body text is resolved only inside a writer packet.
    words = a["headline"].split()
    return {"kind": "article", "article_id": aid, "publisher": a["publisher"], "author": a["author"],
            "url": a["permalink"], "language": a["language"], "published_at": a["date"], "origin": ref["origin"],
            "title": " ".join(words[:18]) + (" …" if len(words) > 18 else ""),
            "field_hashes": {field: fingerprint(a[field]) for field in FIELDS},
            "topics": cat["topics"], "regions": cat["regions"], "tag_review": cat.get("review_reasons", [])}


def checked_ref(ref, role, articles):
    aid, field, start, end = ref["article_id"], ref["field"], ref["start"], ref["end"]
    if field not in FIELDS or type(start) != int or type(end) != int or not 0 <= start < end <= len(articles[aid][field]):
        raise ValueError(f"invalid {role} passage for {aid}")
    return {"source_id": aid, "role": role, "field": field, "start": start, "end": end,
            "span_hash": digest(articles[aid][field][start:end])}


def import_claim(c, articles, sources, categories, cutoff, members):
    from .overview_material import describe
    log = []
    for role, refs in (("supports", c["support"]), ("contradicts", c["contradict"]),
                       ("examined", c.get("review", {}).get("evidence_refs", []))):
        for ref in refs:
            aid = ref["article_id"]
            if role in {"supports", "examined"} and aid not in members:
                raise ValueError(f"claim {c['id']} refers to a nonmember as {role}")
            source = source_record(ref, articles, categories)
            if aid in sources and sources[aid] != source:
                raise ValueError(f"inconsistent source revision for {aid}")
            sources[aid] = source
            log.append(checked_ref(ref, role, articles))
            if "context_span" in ref:
                start, end = ref["context_span"]
                log.append(checked_ref({**ref, "start": start, "end": end}, "context", articles))
    for role, cells in (("official_at_cutoff", c.get("official", [])), ("official_at_reporting", c.get("official_at_reporting", []))):
        for cell in cells:
            if timestamp(cell["available_at"]) >= cutoff:
                raise ValueError("official evidence postdates the verification cutoff")
            sid = "official:" + cell["version"]
            sources[sid] = {"kind": "official", **{k: cell[k] for k in
                            ("issuer", "release_id", "version", "url", "available_at", "vintage")}}
            safe_url(cell["url"])
            log.append({"source_id": sid, "role": role, **{k: cell[k] for k in ("locator", "value", "unit")}})
    if c["approved"] and (c["contradict"] or c["article_state"] != "supported"):
        raise ValueError("approved claim carries contradictory evidence")
    summary = spoken(c, "en") if c["approved"] else c.get("wording", "")
    claim_regions = defaultdict(set)
    if c["approved"]:
        wording_regions = set(classify_regions(c["wording"],"",[])[0]) if not c.get("fact") else set()
        for r in log:
            if r["role"] != "supports":
                continue
            aid = r["source_id"]
            if c.get("fact"):
                claim_regions[c["fact"]["geo"]].add(aid)
            else:
                passage = articles[aid][r["field"]][r["start"]:r["end"]]
                for region in wording_regions.intersection(classify_regions(passage,"",[])[0]):
                    claim_regions[region].add(aid)
    translations = c.get("translations", {})
    if c["approved"] and not c.get("fact"):
        translations = {lang: attributed_wording(c["kind"], c["support"][0]["publisher"], text, lang)
                        for lang, text in translations.items()}
    return {"id": c["id"], "type": "checked_claim", "kind": c["kind"], "language": "en", "summary": summary,
            "claim_regions":{region:sorted(ids) for region,ids in claim_regions.items()},
            "translations":translations, "evidence_state":c.get("evidence_state",c["article_state"]),
            "translation_failures": c.get("translation_failures", {}),
            "fact": c.get("fact"), "article_state": c["article_state"], "official_state": c["official_state"],
            "qualifiers": [] if c["kind"] in {"official_figure", "reported_fact"} else [c["kind"]],
            "sections": list(dict.fromkeys(["development", *describe(summary)["sections"],
                                             *(["figures"] if c.get("fact") else [])])),
            "evidence": list({canonical_json(r): r for r in log}.values()), "reasons": c["reasons"],
            "draft_use": "approved_wording" if c["approved"] else "review_only", "disagreements": []}


def research_disagreements(materials, comparisons, sources):
    by_id = {p["id"]: p for p in materials}
    issues, seen = [], set()
    for frame, sides in sorted(comparisons.items(), key=lambda pair: pair[0][0] != "accounting"):
        if len({value for _, value in sides}) < 2:
            continue
        ids = tuple(sorted({key for key, _ in sides}))
        if ids in seen:
            continue
        origins = {sources[r["source_id"]]["origin"] for k in ids for r in by_id[k]["evidence"]}
        articles = {r["source_id"] for k in ids for r in by_id[k]["evidence"]}
        if len(articles) < 2 or not any(
                r1["source_id"] != r2["source_id"] for i, (k1, v1) in enumerate(sides)
                for k2, v2 in sides[i+1:] if v1 != v2 for r1 in by_id[k1]["evidence"] for r2 in by_id[k2]["evidence"]):
            continue
        seen.add(ids)
        if len(origins) == 1:
            kind = "same_origin_variance"
        elif frame[0] == "accounting":
            kind = "conflicting_reported_values"
        else:
            # Similar descriptions without a common explicit observation time may be successive updates.
            kind = "possible_disagreement"
        issue_id = digest([kind, ids])
        issues.append({"id": issue_id, "kind": kind, "comparison": frame[0], "claim_ids": list(ids),
                       "positions": [{"claim_id": k, "comparison_value": value} for k, value in sides]})
        for key in ids:
            by_id[key]["disagreements"].append(issue_id)
            by_id[key]["draft_use"] = "review_only"
    return issues


def priority(item):
    if item["type"] == "checked_claim":
        return 100 if item["draft_use"] == "approved_wording" else 0
    return (14 * item["is_lead"] + 3 * min(2, len(item["quantities"])) + 2 * bool(item["dates"])
            + 2 * bool(item["named_actors"]) + min(4, len(item["sections"])))


def dossier(event, sources, articles, categories, cutoff):
    members = {s["article_id"] for s in event["sources"]}
    material, comparisons = passage_material(event["event_id"], event["sources"], articles)
    issues = research_disagreements(material, comparisons, sources)
    for item in material:
        if item["reported_challenge"] and not item["disagreements"]:
            issue_id = digest(["reported_challenge", item["id"]])
            issues.append({"id": issue_id, "kind": "reported_challenge", "comparison": "explicit_challenge_in_reporting",
                           "claim_ids": [item["id"]], "positions": []})
            item["disagreements"].append(issue_id)
            item["draft_use"] = "review_only"
    checked = [import_claim(c, articles, sources, categories, cutoff, members) for c in event["claims"]]
    for issue in (event.get("event_review") or {}).get("issues", []):
        issue_id = digest(["event_review", issue])
        issues.append({"id": issue_id, "kind": issue["reason"], "comparison": "event_wide_review",
                       "claim_ids": issue["claim_ids"], "positions": []})
        for claim in checked:
            if claim["id"] in issue["claim_ids"]:
                claim["disagreements"].append(issue_id)
    by_article = defaultdict(list)
    for item in material:
        for ref in item["evidence"]:
            by_article[ref["source_id"]].append((ref, item))
    for claim in checked:
        kind = None
        if claim["article_state"] == "disputed" or any(r["role"] == "contradicts" for r in claim["evidence"]):
            kind = "conflicting_reports"
        elif claim["official_state"] == "conflict":
            kind = "official_mismatch"
        elif claim["official_state"] in {"revised_since_reporting", "changed_since_reporting"}:
            kind = "official_revision"
        if kind and not claim["disagreements"]:
            issue_id = digest([kind, claim["id"]])
            claim["disagreements"].append(issue_id)
            issues.append({"id": issue_id, "kind": kind, "comparison": "upstream_verification",
                           "claim_ids": [claim["id"]], "positions": []})
        for ref in claim["evidence"]:
            if ref["role"] not in {"supports", "contradicts"}:
                continue
            for other, item in by_article.get(ref["source_id"], []):
                if other["field"] == ref["field"] and other["start"] < ref["end"] and other["end"] > ref["start"]:
                    ids = item.setdefault("checked_claim_ids", [])
                    if claim["id"] not in ids:
                        ids.append(claim["id"])
                    if claim["draft_use"] == "review_only" or item["disagreements"]:
                        item["draft_use"] = "review_only"
                        item["disagreements"] = sorted(set(item["disagreements"] + claim["disagreements"]))
                        if item["disagreements"]:
                            claim["disagreements"] = sorted(set(claim["disagreements"] + item["disagreements"]))
                            claim["draft_use"] = "review_only"
    items = checked + material
    if event["group_needs_review"]:
        for item in items:
            if item["draft_use"] != "omit":
                item["draft_use"] = "review_only"
    for item in items:
        item["priority"] = priority(item)
    ordered = sorted((i for i in items if i["draft_use"] not in {"omit","review_only"}), key=priority, reverse=True)
    sections = {k: [i["id"] for i in ordered if k in i["sections"]] for k in SECTIONS}
    # The event record precedes all listener-specific shortening.
    synopsis = list(dict.fromkeys(ids[0] for ids in sections.values() if ids))
    if event.get("overview_claim_ids"):
        synopsis = list(dict.fromkeys([*event["overview_claim_ids"], *synopsis]))
    approved = [i for i in checked if i["draft_use"] == "approved_wording"]
    coverage = {section: {"available_passages": sum(section in i["sections"] for i in material),
                          "approved_claim_ids": [i["id"] for i in approved if section in i["sections"]]}
                for section in SECTIONS}
    origin_count = len({sources[aid]["origin"] for aid in members})
    primary = min(members, key=lambda aid: (sources[aid]["language"] != "en", timestamp(sources[aid]["published_at"]), aid))
    scope = {field: {tag: sorted(aid for aid in members if tag in sources[aid][field])
                     for tag in sorted({v for aid in members for v in sources[aid][field]})}
             for field in ("topics", "regions")}
    reported_regions = sorted(scope["regions"])
    regional_support = defaultdict(set)
    for item in approved:
        for region, ids in item["claim_regions"].items():
            if region != "unknown":
                regional_support[region].update(ids)
    scope["regions"] = {region: sorted(ids) for region, ids in regional_support.items()}
    return {"event_id": event["event_id"], "verification_revision": event["revision"], "version": VERSION,
            "title": sources[primary]["title"], "title_source_id": primary,
            "topics": sorted({t for aid in members for t in sources[aid]["topics"]}),
            "regions": sorted(regional_support), "reported_regions": reported_regions,
            "languages": sorted({sources[aid]["language"] for aid in members}),
            "members": sorted(members), "origin_count": origin_count, "sources": sources, "scope_evidence": scope,
            "group_needs_review": event["group_needs_review"], "model_versions": event.get("model_versions", {}),
            "model_status":event["model_status"], "processing_failure":event.get("failure"),
            "event_review": event.get("event_review"),
            "reporting_chronology": sorted(members, key=lambda aid: (timestamp(sources[aid]["published_at"]), aid)),
            "synopsis_ids": synopsis, "sections": sections, "items": items, "disagreements": issues,
            "overview_coverage": coverage, "examined_passages": event.get("examined_passages", []),
            "limitations": (["one_reporting_origin"] if origin_count == 1 else [])
                           + (["no_approved_wording"] if not any(i["draft_use"] == "approved_wording" for i in items) else [])
                           + (["unresolved_grouping"] if event["group_needs_review"] else [])}


SCHEMA = """
CREATE TABLE IF NOT EXISTS overview_revision(revision TEXT PRIMARY KEY, event_id TEXT NOT NULL, dossier BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS overview_event_history ON overview_revision(event_id);
CREATE TABLE IF NOT EXISTS catalogue(event_id TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES overview_revision,
 title TEXT NOT NULL, topics TEXT NOT NULL, regions TEXT NOT NULL, latest TEXT NOT NULL, issues INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS article_location(article_id TEXT PRIMARY KEY, feed_file TEXT NOT NULL, offset INTEGER, size INTEGER);
CREATE TABLE IF NOT EXISTS build_info(id INTEGER PRIMARY KEY CHECK(id=1), metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overview_batch(key TEXT PRIMARY KEY, proposal TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preferred_overview(base TEXT PRIMARY KEY, revision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_window(cutoff TEXT PRIMARY KEY, window_start TEXT);
CREATE TABLE IF NOT EXISTS daily_event(cutoff TEXT, event_id TEXT, revision TEXT, latest TEXT,
    PRIMARY KEY(cutoff,event_id), FOREIGN KEY(revision) REFERENCES overview_revision(revision));
CREATE TABLE IF NOT EXISTS source_location_version(article_id TEXT, fields TEXT, url TEXT,
    directory TEXT, feed_file TEXT, offset INTEGER, size INTEGER, PRIMARY KEY(article_id,fields,url));
"""


def build(verified, directory, category_path, database):
    start_time = perf_counter()
    snapshot = json.loads(verified.read_text(encoding="utf-8"))
    if snapshot.get("schema") != 1:
        raise ValueError("unsupported verification snapshot")
    cutoff = timestamp(snapshot["cutoff_exclusive"])
    start = timestamp(snapshot["from"]) if snapshot.get("from") else None
    articles, _ = load_feeds(directory, start, cutoff, include_locations=True)
    categories = read_categories(category_path)
    seen, event_ids = set(), set()
    if database.resolve() in {verified.resolve(), category_path.resolve()} or directory.resolve() in database.resolve().parents:
        raise ValueError("choose a separate overview database outside the input feeds")
    database.parent.mkdir(parents=True, exist_ok=True)
    summary = Counter()
    topic_counts, states, issue_counts = Counter(), Counter(), Counter()
    with closing(sqlite3.connect(database, timeout=60)) as db:
        db.executescript(SCHEMA)
        with db:
            db.execute("DELETE FROM catalogue")
            for event in snapshot["events"]:
                if digest({k: v for k, v in event.items() if k != "revision"}) != event["revision"]:
                    raise ValueError("verification event revision mismatch")
                eid = event["event_id"]
                if eid in event_ids or not event["sources"]:
                    raise ValueError("duplicate or empty event")
                event_ids.add(eid)
                members = {}
                for ref in event["sources"]:
                    aid = ref["article_id"]
                    if aid in seen:
                        raise ValueError(f"duplicate event membership for {aid}")
                    seen.add(aid)
                    members[aid] = source_record(ref, articles, categories)
                # Include external contradicting sources in cache invalidation and validate their identity.
                external = {}
                for claim in event["claims"]:
                    for ref in claim["contradict"]:
                        if ref["article_id"] not in members:
                            external[ref["article_id"]] = source_record(ref, articles, categories)
                revision = digest([VERSION, event["revision"], members, external])
                old = db.execute("SELECT dossier FROM overview_revision WHERE revision=?", (revision,)).fetchone()
                if old:
                    overview = json.loads(zlib.decompress(old[0]))
                    summary["cache_hits"] += 1
                    enriched = db.execute("SELECT dossier FROM preferred_overview JOIN overview_revision USING(revision) WHERE base=?",
                                          (revision,)).fetchone()
                    if enriched:
                        overview = json.loads(zlib.decompress(enriched[0]))
                        revision = overview["revision"]
                else:
                    overview = dossier(event, dict(members), articles, categories, cutoff)
                    overview["revision"] = revision
                    db.execute("INSERT INTO overview_revision VALUES (?,?,?)", (
                        revision, eid, zlib.compress(canonical_json(overview).encode(), 3)))
                latest = max(timestamp(s["published_at"]) for s in members.values()).isoformat()
                db.execute("INSERT INTO catalogue VALUES (?,?,?,?,?,?,?)", (
                    eid, revision, overview["title"], canonical_json(overview["topics"]), canonical_json(overview["regions"]),
                    latest, len(overview["disagreements"])))
                summary.update(events=1, articles=len(members), material_items=len(overview["items"]),
                               events_with_material=int(bool(overview["items"])))
                topic_counts.update(overview["topics"])
                states.update(i["draft_use"] for i in overview["items"])
                issue_counts.update(i["kind"] for i in overview["disagreements"])
            if seen != set(articles):
                raise ValueError("verification membership differs from the source window")
            bound = cutoff.isoformat()
            db.execute("INSERT OR REPLACE INTO daily_window VALUES (?,?)", (bound, start.isoformat() if start else None))
            db.execute("DELETE FROM daily_event WHERE cutoff=?", (bound,))
            db.execute("INSERT INTO daily_event SELECT ?,event_id,revision,latest FROM catalogue", (bound,))
            source_root = os.path.relpath(directory.resolve(), database.resolve().parent)
            db.executemany("INSERT OR REPLACE INTO source_location_version VALUES (?,?,?,?,?,?,?)", (
                (aid, digest({k: fingerprint(a[k]) for k in FIELDS}), a["permalink"], source_root,
                 a["feed_file"], a["byte_offset"], a["byte_length"]) for aid, a in articles.items()))
            db.executemany("INSERT OR REPLACE INTO article_location VALUES (?,?,?,?)",
                           ((aid, a["feed_file"], a["byte_offset"], a["byte_length"]) for aid, a in articles.items()))
            report = {"version": VERSION, **summary, "cache_hits": summary["cache_hits"], "topics": dict(topic_counts),
                      "draft_uses": dict(states), "disagreements": dict(issue_counts),
                      "cutoff_exclusive": cutoff.isoformat(), "group_input": snapshot["summary"]["group_input"],
                      "overview_model_calls": 0, "overview_model_cost_usd": 0, "estimated_10x_model_cost_usd": 0,
                      "seconds": round(perf_counter()-start_time, 3)}
            try:
                feed_path = Path(os.path.relpath(directory.resolve(), database.resolve().parent)).as_posix()
            except ValueError:  # Windows cannot express a relative path between drives.
                feed_path = str(directory.resolve())
            db.execute("INSERT OR REPLACE INTO build_info VALUES (1,?)",
                       (canonical_json({"directory": feed_path, "report": report}),))
    return report


def main():
    import argparse
    import sys
    from .overview_reader import catalogue, connect, get_event, log_html, markdown, packet, source_directory, source_log
    from .topic_rules import TOPICS
    from .verify import write_atomic
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    builder = sub.add_parser("build")
    builder.add_argument("--verified", type=Path, default=Path("output/verification.json"))
    builder.add_argument("--input-dir", type=Path, default=Path("liquid-briefing-data"))
    builder.add_argument("--categories", type=Path, default=Path("output/categories.jsonl"))
    listing = sub.add_parser("list")
    listing.add_argument("--topic", choices=TOPICS)
    listing.add_argument("--region")
    listing.add_argument("--query", default="")
    listing.add_argument("--disputes", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("--event", required=True)
    show.add_argument("--revision")
    show.add_argument("--claim", help="display the full source log for a single claim")
    show.add_argument("--depth", choices=("brief","standard","technical","full"), default="full")
    show.add_argument("--focus", choices=SECTIONS, action="append", default=[])
    show.add_argument("--language", choices=("en","de","nl"), default="en")
    show.add_argument("--format", choices=("json","markdown","html"), default="json")
    synth = sub.add_parser("synthesize", help="optional enrichment using an explicitly selected Ollama model")
    which = synth.add_mutually_exclusive_group(required=True)
    which.add_argument("--event", action="append")
    which.add_argument("--all", action="store_true")
    synth.add_argument("--model", required=True, help="installed local Ollama tag, including version")
    web = sub.add_parser("serve")
    web.add_argument("--port", type=int, default=8173)
    export = sub.add_parser("export-demo", help="package event source logs and recorded briefings for offline playback")
    export.add_argument("--verified", type=Path, default=Path("output/verification.json"))
    export.add_argument("--briefing", type=Path, action="append", required=True, help="directory with script.json and its recorded WAV")
    export.add_argument("--output", type=Path, required=True, help="destination .zip")
    for p in (builder, listing, show, synth, web, export):
        p.add_argument("--db", type=Path, default=Path("output/event-overviews.sqlite3"))
    for p in (listing, show):
        p.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "serve":
            from .overview_web import serve
            serve(args.db,args.port)
            return
        if args.action == "build":
            print(json.dumps(build(args.verified,args.input_dir,args.categories,args.db), indent=2))
            return
        if args.action == "synthesize":
            from .overview_synthesis import LocalModel, enrich
            model = LocalModel(args.model)
            with closing(sqlite3.connect(args.db.resolve().as_uri()+"?mode=rw", uri=True, timeout=60)) as db:
                ids = args.event or [r["event_id"] for r in catalogue(db)]
                for eid in ids:
                    print(canonical_json(enrich(db, eid, model)), flush=True)
            return
        with closing(connect(args.db)) as db:
            if args.action == "export-demo":
                from .overview_demo import export_demo
                print(canonical_json(export_demo(db, args.verified, args.briefing, args.output)))
                return
            if args.action == "list":
                result = catalogue(db, topic=args.topic, region=args.region, query=args.query, disputes=args.disputes)
            else:
                e = get_event(db, args.event, args.revision)
                if args.claim:
                    item = next((i for i in e["items"] if i["id"] == args.claim), None)
                    if item is None:
                        raise ValueError("unknown claim in this event revision")
                    result = {"event_id": e["event_id"], "revision": e["revision"], "claim": item,
                              "source_log": source_log(e,item)}
                elif args.format == "html":
                    result = log_html(e)
                else:
                    result = packet(db,e,depth=args.depth,focus=args.focus,language=args.language)
                    if args.format == "markdown":
                        result = markdown(result)
            contents = result if isinstance(result,str) else json.dumps(result, indent=2, ensure_ascii=False)
            if args.output:
                source_root = source_directory(db)
                if args.output.resolve() == args.db.resolve() or source_root in args.output.resolve().parents:
                    raise ValueError("write exports outside the source feeds and overview database")
                write_atomic(args.output, contents)
            else:
                sys.stdout.buffer.write((contents+"\n").encode("utf-8"))
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"overview failed: {error}\n")


if __name__ == "__main__":
    main()
