"""Verify event claims against original articles and as-of official observations."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile
from time import perf_counter

from . import claim_rules
from .categorization import validate_article
from .claim_models import ClaimModels, excerpt
from .event_candidates import fingerprint
from .group_events import indexed_jsonl, read_jsonl, timestamp
from .luna import MODEL, ModelError, canonical_json
from .official_releases import DEFAULT_PACK, ReleaseIndex, digest, number, safe_url, validate_dimensions


RULE_VERSION = "macro-2"
KEY_FIELDS = ("geo", "measure", "period", "basis")
NUMERIC = re.compile(r"\d|[%£$€]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                     r"\w+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
                     r"billion|trillion|percent|half|double[ds]?|triple[ds]?)\b", re.I)
ADVICE = re.compile(r"\b(?:(?:you|investors?|traders?) should\b|we recommend\b|(?:buy|sell|invest) now\b|"
                    r"(?:time|opportunity) to (?:buy|sell|invest)\b|(?:buy|sell|hold) (?:this|these|the) (?:stock|share|bond))", re.I)


def write_atomic(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            out.write(contents)
        temp.replace(path)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def load_feeds(directory, start, before, *, include_locations=False):
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        raise ValueError("no input feeds")
    ids, articles = set(), {}
    for path in paths:
        for location, row, offset, size in indexed_jsonl(path):
            try:
                validate_article(row)
                aid = row["$id"]
                if aid in ids:
                    raise ValueError("duplicate article ID")
                ids.add(aid)
                published = timestamp(row["date"])
                if published >= before or (start and published < start):
                    continue
                safe_url(row["permalink"])
                body = row.get("text_content") or ""
                if not isinstance(body, str):
                    raise ValueError("invalid article body")
                articles[aid] = {"$id": aid, "date": row["date"], "permalink": row["permalink"],
                                 "headline": row.get("headline") or "", "language": row["language"],
                                 "publisher": (row.get("publication") or {}).get("name") or path.stem,
                                 "text_content": body, "body_hash": fingerprint(body)}
                if include_locations:
                    articles[aid].update(excerpt=row.get("excerpt") or "", author=row.get("source") or "",
                                         feed_file=path.name, byte_offset=offset, byte_length=size)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"{location}: {error}") from error
    return articles, ids


def membership(articles, ids, events, origins):
    groups, seen = {}, set()
    if not events and not origins:
        for aid, article in articles.items():
            origin = article["body_hash"] if article["text_content"] else aid
            groups.setdefault("origin_" + origin, ([], False))[0].append((aid, origin))
        return groups
    for location, row in read_jsonl(events or origins):
        if origins:
            if row.get("kind") == "candidate_pair":
                continue
            if row.get("kind") != "reporting_origin":
                raise ValueError(f"{location}: expected reporting origins")
            origin = "origin_" + fingerprint(row["anchor_article_id"])[:24]
            event = origin
            members = [(aid, origin) for aid in row["article_ids"]]
            uncertain = bool(set(row["review_article_ids"]) & articles.keys())
        else:
            event = row["event_id"]
            if row["status"] not in {"grouped", "singleton", "needs_review"}:
                raise ValueError(f"{location}: invalid event status")
            members = [(s["article_id"], s["reporting_origin_id"]) for s in row["sources"]]
            uncertain = row["status"] == "needs_review"
        if not isinstance(event, str) or not event or event in groups or not members:
            raise ValueError(f"{location}: missing or duplicate event")
        eligible = []
        for aid, origin in members:
            if aid not in ids or aid in seen or not isinstance(origin, str) or not origin:
                raise ValueError(f"{location}: unknown or duplicate member or missing origin")
            seen.add(aid)
            if aid in articles:
                eligible.append((aid, origin))
        if eligible:
            if events and len(eligible) != len(members):
                raise ValueError(f"{location}: mixed-date event; regenerate groups for this briefing window")
            groups[event] = (eligible, uncertain)
    missing = articles.keys() - seen
    if missing:
        raise ValueError(f"event input missing {len(missing)} eligible articles; align the date windows")
    return groups


def evidence(article, origin, span):
    return {"article_id": article["$id"], "origin": origin, "permalink": article["permalink"],
            "publisher": article["publisher"], "language": article["language"], "published_at": article["date"],
            "body_hash": article["body_hash"], **span}


def rule_rows(db, article, counts):
    key = digest([RULE_VERSION, article["body_hash"], article["date"][:10], timestamp(article["date"]).date().isoformat()])
    cached = db.execute("SELECT result FROM claim_rules WHERE key=?", (key,)).fetchone()
    if cached:
        counts["rule_cache_hits"] += 1
        return json.loads(cached[0])
    rows = claim_rules.extract(article, timestamp(article["date"]))
    db.execute("INSERT OR IGNORE INTO claim_rules VALUES (?,?)", (key, canonical_json(rows)))
    return rows


def fact_claim(event, dims, value, official, refs, method):
    identifier = digest([event, dims, value])
    cells = official.lookup(dims)
    status = "missing"
    contemporary = []
    if cells:
        status = "matched" if all(c["value"] == value for c in cells) else "conflict"
        for published in sorted({r["published_at"] for r in refs}):
            contemporary.extend(official.lookup(dims, timestamp(published)))
        if any(c["vintage"] in {"flash", "preliminary"} for c in cells):
            status = "preliminary_only"
        elif not contemporary:
            status = "no_contemporary_release"
        elif status == "conflict" and any(c["value"] == value for c in contemporary):
            status = "revised_since_reporting"
        elif status == "matched" and not any(c["value"] == value and c["vintage"] not in
                                              {"flash", "preliminary"} for c in contemporary):
            status = "changed_since_reporting"
    return {"id": identifier, "fact": {**dict(zip(KEY_FIELDS, dims)), "unit": "%", "value": value},
            "kind": "official_figure", "method": method, "article_state": "supported",
            "support": refs, "contradict": [], "official_state": status, "official": cells,
            "official_at_reporting": list({digest(c): c for c in contemporary}.values()),
            "approved": status == "matched", "reasons": [] if status == "matched" else ["official_" + status]}


def distinct(refs):
    return list({(r["article_id"], r["field"], r["start"], r["end"]): r for r in refs}.values())


def contains_percent(quote, value):
    tokens = re.findall(r"(?<!\w)[-+−]?\d+(?:[.,]\d+)?(?=\s*(?:%|percent\b|procent\b|prozent\b))",
                        quote, flags=re.I)
    return any(number(t.replace(",", ".").replace("−", "-")) == value for t in tokens)


def rule_event(event, members, uncertain, articles, db, official, counts):
    by_fact = defaultdict(list)
    sources = []
    for aid, origin in sorted(members):
        article = articles[aid]
        sources.append(evidence(article, origin, {}))
        for dims, value, span in rule_rows(db, article, counts):
            by_fact[tuple(dims), value].append(evidence(article, origin, span))
    claims = [fact_claim(event, dims, value, official, refs, "rules") for (dims, value), refs in by_fact.items()]
    return {"event_id": event, "group_needs_review": uncertain, "sources": sources, "claims": claims,
            "model_status": "not_requested"}


def model_claims(event, articles, official, models):
    hints = {r["article_id"]: r for c in reversed(event["claims"]) for r in c["support"]}
    packet, refs = [], []
    # Keep separate reporting origins ahead of translations in the excerpt budget.
    sources = sorted(event["sources"], key=lambda s: (s["origin"], s["language"] != "en", s["article_id"]))
    by_origin = defaultdict(list)
    for source in sources:
        by_origin[source["origin"]].append(source)
    ordered = [members[0] for members in by_origin.values()] + [s for members in by_origin.values() for s in members[1:]]
    for source in ordered[:6]:
        aid = source["article_id"]
        quote = excerpt(articles[aid], hints.get(aid))
        if quote:
            packet.append({"id": len(packet), "language": source["language"], "date": source["published_at"][:10],
                           "quote": quote.pop("quote")})
            refs.append({**source, **quote})
    if not packet:
        return
    event["model_versions"] = models.versions
    candidates = models.call("extract", {"excerpts": packet})["claims"]
    existing = {claim["id"]: claim for claim in event["claims"]}
    # Rule mismatches must reach the reviewer even if Luna misses them.
    for c in event["claims"]:
        if not c["approved"] or event["triage"] in {"mixed_coverage", "article_conflict", "audit"}:
            indexes = [i for i, ref in enumerate(refs) if any(ref["article_id"] == r["article_id"] for r in c["support"])]
            if indexes:
                candidates.append({"kind": "official_figure", "refs": indexes, "wording": "", **c["fact"]})
    for candidate in candidates:
        cited = [refs[i] for i in candidate["refs"]]
        kind = candidate["kind"]
        wording = candidate["wording"].strip()
        dims = [candidate[k] for k in KEY_FIELDS]
        if kind == "official_figure":
            try:
                validate_dimensions(*dims)
                value = number(candidate["value"])
                # A model cannot supply a new number by pointing to an unrelated figure.
                anchored = any(contains_percent(packet[i]["quote"], value) for i in candidate["refs"])
                c = fact_claim(event["event_id"], dims, value, official, cited, "small_model")
            except ValueError:
                anchored = False
                c = None
        else:
            words = re.findall(r"\w+", wording.lower())
            copied = any(" ".join(words[j:j+6]) in " ".join(re.findall(r"\w+", packet[i]["quote"].lower()))
                         for i in candidate["refs"] for j in range(len(words) - 5))
            anchored = (kind == "reported_fact" and bool(words) and not NUMERIC.search(wording)
                        and not ADVICE.search(wording) and not copied)
            c = None
        if c is None:
            c = {"id": digest([event["event_id"], kind, wording]), "kind": kind, "wording": wording,
                 "method": "small_model", "support": cited, "contradict": [], "article_state": "unsupported",
                 "official_state": "missing" if kind == "official_figure" else "not_applicable",
                 "official": [], "approved": False, "reasons": []}
        prior = existing.get(c["id"])
        if (prior and prior["approved"] and prior["method"] == "rules"
                and event["triage"] not in {"mixed_coverage", "article_conflict", "audit"}):
            continue
        if prior and "review" in prior:
            continue
        if prior:
            c = prior
        else:
            event["claims"].append(c)
            existing[c["id"]] = c
        c["approved"] = False
        if kind not in {"reported_fact", "official_figure"} or not anchored:
            c["article_state"] = "unsupported" if not prior else c["article_state"]
            c["reasons"].append("nonfactual_or_unanchored")
            continue
        review = models.call("review", {"excerpts": packet, "claim": c.get("fact", wording),
                                        "official": c["official"]})
        c["review"] = {**review, "evidence_refs": refs}
        c["article_state"] = review["decision"]
        c["support"] = distinct(([r for r in c["support"]] if prior else []) + [refs[i] for i in review["support"]])
        c["contradict"] = [refs[i] for i in review["contradict"]]
        c["approved"] = (review["decision"] == "supported" and bool(c["support"])
                         and c["official_state"] in {"matched", "not_applicable"})
        if c["approved"] and "fact" in c:
            checked = [refs[i] for i in review["support"] if contains_percent(packet[i]["quote"], value)]
            if not checked or not fact_claim(event["event_id"], dims, value, official, checked, "review")["approved"]:
                c["approved"], c["article_state"] = False, "unsupported"
                c["reasons"].append("review_references_do_not_anchor_figure")
        if not c["approved"]:
            c["reasons"].append(review["reason"])
    event["model_status"] = "reviewed"


def apply_conflicts(events):
    observations = defaultdict(list)
    for event in events:
        for c in event["claims"]:
            if (c.get("fact") and c["article_state"] in {"supported", "disputed"}
                    and c["official_state"] not in {"revised_since_reporting", "no_contemporary_release",
                                                    "preliminary_only", "changed_since_reporting"}):
                observations[tuple(c["fact"][k] for k in KEY_FIELDS)].append(c)
            if event["group_needs_review"]:
                c["approved"] = False
                c["reasons"].append("unresolved_event_grouping")
    for claims in observations.values():
        if len({c["fact"]["value"] for c in claims}) < 2:
            continue
        for c in claims:
            competing = [r for other in claims if other["fact"]["value"] != c["fact"]["value"] for r in other["support"]]
            c["article_state"], c["approved"] = "disputed", False
            c["contradict"] = distinct(c["contradict"] + competing)
            c["reasons"].append("articles_disagree")


def verify(directory, before, db, *, packs=(DEFAULT_PACK,), start=None, events=None, origins=None,
           models=None, model_events=0, audit_every=0):
    if start and start >= before:
        raise ValueError("start must be earlier than cutoff")
    if model_events < 0 or audit_every < 0 or (model_events and models is None):
        raise ValueError("a positive model budget requires configured models")
    timer = perf_counter()
    official = ReleaseIndex(packs, before)
    articles, ids = load_feeds(directory, start, before)
    groups = membership(articles, ids, events, origins)
    loaded = perf_counter()
    counts = Counter()
    db.execute("CREATE TABLE IF NOT EXISTS claim_rules (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
    with db:
        records = [rule_event(key, members, uncertain, articles, db, official, counts)
                   for key, (members, uncertain) in groups.items()]
    # Triage ranks work before the model budget is spent. It does not establish support.
    apply_conflicts(records)
    order = ["uncovered", "macro_headline", "mixed_coverage", "audit", "official_missing",
             "official_conflict", "article_conflict"]
    for event in records:
        claims = event["claims"]
        states = {c["official_state"] for c in claims}
        if any(c["article_state"] == "disputed" for c in claims):
            triage = "article_conflict"
        elif "conflict" in states:
            triage = "official_conflict"
        elif states - {"matched"}:
            triage = "official_missing"
        elif claims and audit_every and int(digest(event["event_id"])[:12], 16) % audit_every == 0:
            triage = "audit"
        elif claims and {s["origin"] for s in event["sources"]} - {r["origin"] for c in claims for r in c["support"]}:
            triage = "mixed_coverage"
        elif claims:
            triage = "exact_match"
        elif any(re.search(r"inflat|\bCPI\b|\bHICP\b|bank rate|rate decision|zinsentscheid|rentebesluit",
                           articles[s["article_id"]]["headline"], re.I) for s in event["sources"]):
            triage = "macro_headline"
        else:
            triage = "uncovered"
        event["triage"] = triage
    def priority(event):
        return order.index(event["triage"]), max(timestamp(s["published_at"]) for s in event["sources"]), event["event_id"]
    pending = [e for e in records if e["triage"] in order]
    triaged = perf_counter()
    for event in sorted(pending, key=priority, reverse=True)[:model_events]:
        model_claims(event, articles, official, models)
    reviewed = perf_counter()
    apply_conflicts(records)
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS verified_event "
                   "(event_id TEXT, revision TEXT, result TEXT NOT NULL, PRIMARY KEY(event_id, revision))")
        for event in records:
            for claim in event["claims"]:
                claim["reasons"] = sorted(set(claim["reasons"]))
                claim["supporting_origins"] = sorted({r["origin"] for r in claim["support"]})
            event["rule_version"] = RULE_VERSION
            event["revision"] = digest(event)
            db.execute("INSERT OR IGNORE INTO verified_event VALUES (?,?,?)",
                       (event["event_id"], event["revision"], canonical_json(event)))
    claims = [c for e in records for c in e["claims"]]
    usage = models.report() if models else {}
    amounts = [v["usage_cost_usd"] for v in usage.values()]
    cost = sum(amounts) if None not in amounts else None
    summary = {
        "articles_in_feeds": len(ids), "articles_in_window": len(articles), "events": len(records),
        "reporting_origins": len({s["origin"] for e in records for s in e["sources"]}),
        "group_input": "events" if events else "reporting_origins" if origins else "exact_copies_only",
        "claims": len(claims), "approved": sum(c["approved"] for c in claims),
        "events_without_extracted_claims": sum(not e["claims"] for e in records),
        "rule_cache_hits": counts["rule_cache_hits"], "eligible_model_events": len(pending),
        "model_events_processed": sum(e["model_status"] == "reviewed" for e in records),
        "triage": dict(Counter(e["triage"] for e in records)),
        "official_status": dict(Counter(c["official_state"] for c in claims)),
        "article_status": dict(Counter(c["article_state"] for c in claims)),
        "languages": dict(Counter(a["language"] for a in articles.values())), "model_usage": usage,
        "verification_model_cost_usd": cost, "estimated_10x_model_cost_usd": None if cost is None else cost * 10,
        "projection_assumption": "10x new event revisions, same routing, prices and cache-hit mix; verification only.",
        "stage_seconds": {"load": round(loaded-timer, 3), "rules_and_triage": round(triaged-loaded, 3),
                          "model_routing_and_review": round(reviewed-triaged, 3),
                          "conflicts_and_storage": round(perf_counter()-reviewed, 3)},
        "wall_seconds": round(perf_counter() - timer, 3),
    }
    return {"schema": 1, "rules": RULE_VERSION, "cutoff_exclusive": before.isoformat(),
            "from": start.isoformat() if start else None, "official_versions": official.versions,
            "summary": summary, "events": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("liquid-briefing-data"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--events", type=Path)
    group.add_argument("--origins", type=Path, help="group_events --candidates-only output for offline runs")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--before", required=True, help="exclusive UTC date or timestamp")
    parser.add_argument("--pack", type=Path, action="append", help="repeat to combine official release packs")
    parser.add_argument("--output", type=Path, default=Path("output/verification.json"))
    parser.add_argument("--cache", type=Path, default=Path("output/claim-cache.sqlite3"))
    parser.add_argument("--model-events", type=int, default=0, help="maximum unresolved events to send for extraction")
    parser.add_argument("--small-model", default=MODEL)
    parser.add_argument("--audit-every", type=int, default=0, help="queue a reproducible 1-in-N sample of exact matches")
    parser.add_argument("--review-model", help="stronger review model ID")
    parser.add_argument("--prices", type=Path, help="JSON mapping model to USD per million input/cached/output tokens")
    args = parser.parse_args()
    try:
        packs = args.pack or [DEFAULT_PACK]
        inputs = {p.resolve() for p in [args.events, args.origins, args.prices, *packs] if p}
        destinations = [args.output.resolve(), args.cache.resolve()]
        if (len(set(destinations)) != 2 or inputs.intersection(destinations)
                or any(args.input_dir.resolve() in p.parents for p in destinations)):
            raise ValueError("use separate output and cache files outside inputs")
        if args.model_events and not args.review_model:
            raise ValueError("supply --review-model when enabling model calls")
        prices = json.loads(args.prices.read_text(encoding="utf-8")) if args.prices else {}
        for rates in prices.values():
            if set(rates) != {"input", "cached", "output"} or not all(
                    type(p) in (float, int) and math.isfinite(p) and p >= 0 for p in rates.values()):
                raise ValueError("invalid model price schedule")
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.cache)) as db:
            models = ClaimModels(db, args.small_model, args.review_model, prices=prices) if args.model_events else None
            result = verify(args.input_dir, timestamp(args.before, allow_date=True), db, packs=packs,
                            start=timestamp(args.start, allow_date=True) if args.start else None,
                            events=args.events, origins=args.origins, models=models, model_events=args.model_events,
                            audit_every=args.audit_every)
        write_atomic(args.output, canonical_json(result) + "\n")
        print(json.dumps(result["summary"], indent=2))
    except (OSError, ModelError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f"claim verification failed: {error}\n")


if __name__ == "__main__":
    main()
