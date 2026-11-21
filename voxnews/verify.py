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

from . import claim_rules, providers
from .categorization import validate_article
from .claim_models import ClaimModels, excerpt
from .event_candidates import fingerprint
from .group_events import indexed_jsonl, read_jsonl, timestamp
from .luna import MODEL, ModelError, RequestsPaused, canonical_json
from .official_releases import DEFAULT_PACK, ReleaseIndex, digest, number, safe_url, validate_dimensions
from .number_validation import source_numbers_support, translation_numbers_match


RULE_VERSION = "macro-2"
VERIFICATION_VERSION = "event-check-7"
KEY_FIELDS = ("geo", "measure", "period", "basis")
NUMERIC = re.compile(r"\d|[%£$€]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                     r"\w+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
                     r"billion|trillion|percent|half|double[ds]?|triple[ds]?)\b", re.I)
ADVICE = re.compile(r"\b(?:(?:you|investors?|traders?) should\b|we recommend\b|(?:buy|sell|invest) now\b|"
                    r"(?:time|opportunity) to (?:buy|sell|invest)\b|(?:buy|sell|hold) (?:this|these|the) (?:stock|share|bond)|"
                    r"(?:recommend|suggest|advis)\w*\s+(?:(?:that\s+)?(?:investors?|you)\s+|that\s+)?"
                    r"(?:should\s+)?(?:buy\w*|sell\w*|invest\w*|hold\w*))", re.I)


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


DEICTIC = re.compile(r"\b(?:the user|the reader|you|we|our|yesterday|today|tomorrow|this morning|last night)\b",re.I)
DIRECTIONS = [
    re.compile(r"\b(?:rose|ris(?:e|en|ing)|increas\w*|higher|jump\w*|accelerat\w*|gained|surged|climbed)\b",re.I),
    re.compile(r"\b(?:fell|fall\w*|drop\w*|decreas\w*|lower|slid|declin\w*|sunk|sank|down|into the red)\b",re.I),
]
SCOPE_CUES = [
    (r"\btrade services\b", r"\btrade services\b"),
    (r"\benter(?:ed|ing|s)?\b", r"\benter(?:ed|ing|s)?\b|\b(?:walk\w*|went|stepped|moved|came)\s+into\b"),
    (r"\bpick(?:ed|ing|s)? up\b", r"\bpick(?:ed|ing|s)? up\b|\b(?:took|taking|lifted|lifting)\b"),
    (r"\b(?:will|would) (?:remain|stay)\b",
     r"\b(?:will|would|may|might|could) (?:remain|stay)\b|\b(?:expect|forecast|predict)\w*.{0,60}\b(?:remain|stay)\b"),
    (r"\b(?:because|caus\w*|driven by|due to|result(?:ing|ed) in|prompt\w*|leading to)\b",
     r"\b(?:because|caus\w*|driven by|due to|result(?:ing|ed) in|prompt\w*|leading to)\b"),
    (r"\b(?:annual\w*|year[- ]on[- ]year|yoy)\b",
     r"\b(?:annual\w*|year[- ]on[- ]year|yoy|same period last year)\b"),
    (r"\b(?:monthly|month[- ]on[- ]month|mom)\b", r"\b(?:monthly|month[- ]on[- ]month|mom)\b"),
]
SCOPE_CUES = [(re.compile(a, re.I), re.compile(b, re.I)) for a, b in SCOPE_CUES]
PARTIAL = re.compile(r"\b(?:part of|in part|partly|partially|some of|among the)\b", re.I)
INTENT = re.compile(r"\b(?:scrambl\w* to|plans? to|aim\w* to|seek\w* to|trying to|attempt\w* to|working to)\b", re.I)
PROMOTIONAL = re.compile(r"\b(?:follow .{0,120}(?:channel|telegram)|subscribe|sign up|click here)\b", re.I)
REPORTED_OPINION = re.compile(r"\b(?:speaking to|he said|she said|according to)\b", re.I)
OPINION_ATTRIBUTION = re.compile(r"\b(?:said|according to|expects|forecasts|projects|analysts?|predicts)\b", re.I)
OBSERVED_DATA_CLAIM = re.compile(r"\b(?:CPI|PPI|consumer price index|producer price index)\b.{0,50}\b(?:data|reading|figures)\b", re.I)
OBSERVATION = re.compile(r"\b(?:data|figures|reading|release|print|report|observed|recorded|measured|registered)\b", re.I)
FORECAST_CUE = re.compile(r"\b(?:expect\w*|forecast\w*|predict\w*|project\w*|plans?|planned|may|might|could|would|will)\b", re.I)
FORECAST_ATTRIBUTION = re.compile(r"\b(?:expects?|forecasts?|predicts?|projects?|plans?|analysts?|said|says|warned|according to)\b", re.I)
QUALIFIED_KINDS = {
    "allegation": re.compile(r"\b(?:alleg\w*|accus\w*|claims?|deni(?:ed|es)|(?:filing|lawsuit|complaint) (?:says|states))\b", re.I),
    "analysis": re.compile(r"\b(?:argu\w*|believ\w*|suggest\w*|implies|in .{0,60}view|according to analysts|analysts? (?:say|said))\b", re.I),
}


def qualified_wording(kind, wording):
    if kind == "reported_fact":
        return True
    if kind == "forecast":
        return bool(FORECAST_CUE.search(wording) and FORECAST_ATTRIBUTION.search(wording))
    return bool(kind in QUALIFIED_KINDS and QUALIFIED_KINDS[kind].search(wording))


def relation_anchors(wording, quote):
    # An estimate excluding expenses does not establish when those expenses will be needed.
    if (re.search(r"\b(?:before|exclud\w*|not including)\s+.{0,30}\b(?:care|taxes|fees|costs|expenses)\b", quote, re.I)
            and re.search(r"\b(?:before|prior to)\s+.{0,45}\b(?:needs?|begins?|starts?|becomes? due)\b", wording, re.I)):
        return False
    for added, opposite in (("her", "his"), ("his", "her"), ("she", "he"), ("he", "she")):
        if (re.search(r"\b" + added + r"\b", wording, re.I)
                and not re.search(r"\b" + added + r"\b", quote, re.I)
                and re.search(r"\b" + opposite + r"\b", quote, re.I)):
            return False
    recipient = re.match(r"([A-Z][\w&.'’–-]*(?:\s+[A-Z][\w&.'’–-]*){0,3})\s+"
                         r"(?:secured|received|won|obtained|was awarded)\b", wording)
    if recipient and re.search(r"\b(?:awards?|contracts?|funding|payments?|donations?|grants?)\s+from\s+(?:the\s+)?"
                               + re.escape(recipient[1]) + r"\b", quote, re.I):
        return False
    return True


def named_anchors(wording, quote):
    def normalize(text):
        return re.sub(r"\b(?:[A-Z]\.){2,}", lambda m: m[0].replace(".", ""), text)
    names = {w.casefold() for w in re.findall(r"\b[A-Z][A-Za-z0-9]*\b", normalize(wording))}
    names -= {"the", "a", "an", "in", "at", "both"}
    tokens = set(re.findall(r"\w+", normalize(quote).casefold()))
    for abbreviation, words in {"us": {"united", "states"}, "uk": {"united", "kingdom"},
                                "eu": {"european", "union"}}.items():
        if words <= tokens:
            tokens.add(abbreviation)
    if {"britain", "british"}.intersection(tokens):
        tokens.add("uk")
    return names <= tokens


def prose_anchors(wording, excerpts):
    """Prevent common actor/time shifts and invented movements before publication."""
    if DEICTIC.search(wording):
        return False
    # Lexical direction checks apply to English evidence. Translation entailment is reviewed separately.
    if excerpts and all(r["language"] == "en" for r in excerpts):
        return any(
            not PROMOTIONAL.search(r["quote"])
            and relation_anchors(wording, r["quote"])
            and named_anchors(wording, r["quote"])
            and {w.casefold().replace("’", "'") for w in re.findall(r"\b[A-Z][\w]*['’]s\b", wording)} <= {
                w.casefold().replace("’", "'") for w in re.findall(r"\b[A-Z][\w]*['’]s\b", r["quote"])}
            and all(not pattern.search(wording) or pattern.search(r["quote"]) for pattern in DIRECTIONS)
            and all(not claim.search(wording) or source.search(r["quote"]) for claim, source in SCOPE_CUES)
            and (not PARTIAL.search(r["quote"]) or PARTIAL.search(wording))
            and (not INTENT.search(r["quote"]) or INTENT.search(wording))
            and (not (REPORTED_OPINION.search(r["quote"]) and claim_rules.FORECAST.search(r["quote"]))
                 or OPINION_ATTRIBUTION.search(wording))
            and (not re.search(r"\b(?:we|our)\b", r["quote"], re.I) or OPINION_ATTRIBUTION.search(wording))
            and (not OBSERVED_DATA_CLAIM.search(wording) or OBSERVATION.search(r["quote"]))
            for r in excerpts)
    return True


def reported_number_anchors(wording, excerpts, *, forecast=False):
    """Keep literal quantities and units together in one supporting passage."""
    # Keep a second outcome as its own claim, with its own measure and evidence.
    if re.search(r"\band (?:marking|bringing|taking|putting|resulting)\b", wording, re.I):
        return False
    # Official-series observations must use the structured official comparison path.
    if not forecast and NUMERIC.search(wording) and re.search(r"\b(?:CPIH?|HICP|inflation|bank lending|bank rate|deposit facility rate)\b", wording, re.I):
        return False
    return any(source_numbers_support(wording, p["quote"], p.get("language", "en")) for p in excerpts)


def figure_anchors(quote, fact, published):
    """The same number in a different release or comparison is not supporting evidence."""
    geo = {name for name,code in claim_rules.GEO.items() if code == fact["geo"]}
    geo.update({"GB":{"boe","bank of england"}, "EA":{"ecb","euro area"}}.get(fact["geo"],set()))
    measures = {
        "CPI":r"(?<!core )\bcpi\b|consumer price index", "core CPI":r"\bcore (?:cpi|consumer price)",
        "CPIH":r"\bcpih\b", "HICP":r"\b(?:hicp|hvpi)\b|harmonis(?:ed|ierten) consumer",
        "bank lending":r"\b(?:bank lending|kreditvergabe)\b", "Bank Rate":r"\bbank rate\b",
        "deposit facility rate":r"\bdeposit facility rate\b"}
    for sentence in claim_rules.SENTENCE.findall(quote):
        if (not contains_percent(sentence,fact["value"]) or claim_rules.FORECAST.search(sentence)
                or not re.search(measures[fact["measure"]],sentence,re.I)
                or not any(re.search(r"\b"+re.escape(term)+r"\b",sentence,re.I) for term in geo)):
            continue
        if fact["basis"] != "level" and claim_rules.basis_of(*re.findall(claim_rules.BASIS,sentence,re.I)) != fact["basis"]:
            continue
        period = fact["period"]
        if period in sentence:
            return True
        for match in re.finditer(r"\b(?P<month>"+claim_rules.MONTH_NAMES+r")\b(?:\s+(?P<year>20\d\d))?",sentence,re.I):
            if fact["basis"] != "level" and claim_rules.period_of(match,published) == period:
                return True
        if fact["basis"] == "level":
            bank = claim_rules.BANK.fullmatch(sentence.strip(" .\n"))
            if bank and claim_rules.period_of(bank,published,day=True) == period:
                return True
    return False


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


def event_evidence_batches(event, articles):
    """Sample the full event by editorial facet before making bounded model requests."""
    from .overview_material import SECTIONS, passage_material

    material, _ = passage_material(event["event_id"], event["sources"], articles)
    eligible = [item for item in material if item["draft_use"] != "omit"]
    selected, seen = [], set()

    def take(item):
        for ref in item["evidence"]:
            aid = ref["source_id"]
            span = ref.get("context_span", [ref["start"], ref["end"]])
            key = (aid, ref["field"], *span)
            if key not in seen:
                selected.append((aid, {"field": ref["field"], "start": span[0], "end": span[1]}, item["sections"]))
                seen.add(key)
                break

    # Every reporting origin contributes its lead. Translations remain in the dossier.
    origins = set()
    for source in sorted(event["sources"], key=lambda s: (s["language"] != "en", s["article_id"])):
        if source["origin"] in origins:
            continue
        lead = next((i for i in eligible if i["is_lead"] and any(
            r["source_id"] == source["article_id"] for r in i["evidence"])), None)
        if lead:
            take(lead)
            origins.add(source["origin"])
    # Read the entire indexed source, including detail beyond the opening excerpt.
    for section in SECTIONS:
        pool = [i for i in eligible if section in i["sections"]]
        pool.sort(key=lambda i: (i["language"] != "en", not i["is_lead"],
                                 -len(i["named_actors"]), -len(i["dates"]), i["id"]))
        for item in pool[:2]:
            take(item)
    for start in range(0, len(selected), 3):
        yield selected[start:start + 3]


def model_claims(event, articles, official, models):
    coverage = []
    for batch in event_evidence_batches(event, articles):
        packet, refs = [], []
        for aid, hint, sections in batch:
            source = next(s for s in event["sources"] if s["article_id"] == aid)
            quote = excerpt(articles[aid], hint)
            if quote:
                packet.append({"id": len(packet), "language": source["language"],
                               "date": source["published_at"][:10], "sections": sections,
                               "quote": quote.pop("quote")})
                refs.append({**source, **quote})
        if packet:
            key = digest([models.versions["extract"], models.versions["review"], packet])
            split = bool(models.db.execute("SELECT 1 FROM claim_batch_split WHERE key=?", (key,)).fetchone())
            if not split:
                try:
                    review_packet(event, packet, refs, official, models)
                except ModelError:
                    if len(packet) == 1:
                        raise
                    models.usage["extract"]["batch_retries"] += 1
                    split = True
            if split:
                for passage, ref in zip(packet, refs):
                    review_packet(event, [{**passage, "id": 0}], [ref], official, models)
                with models.db:
                    models.db.execute("INSERT OR IGNORE INTO claim_batch_split VALUES(?)", (key,))
            coverage.extend({"article_id": r["article_id"], "field": r["field"],
                             "start": r["start"], "end": r["end"], "sections": p["sections"]}
                            for p, r in zip(packet, refs))
    event["examined_passages"] = coverage
    event["model_status"] = "reviewed"


def review_packet(event, packet, refs, official, models):
    """Review candidates against the exact bounded passages used to extract them."""
    event["model_versions"] = models.versions
    candidates = models.call("extract", {"excerpts": packet})["claims"]
    existing = {claim["id"]: claim for claim in event["claims"]}
    # Rule mismatches must reach the reviewer even if Luna misses them.
    for c in list(event["claims"]):
        if not c.get("fact"):
            continue
        if not c["approved"] or event["triage"] in {"mixed_coverage", "article_conflict", "audit"}:
            indexes = [i for i, ref in enumerate(refs) if any(
                ref["article_id"] == r["article_id"] and ref["field"] == r["field"]
                and ref["start"] < r["end"] and ref["end"] > r["start"] for r in c["support"])]
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
                c = fact_claim(event["event_id"], dims, value, official, cited, "model")
            except ValueError:
                anchored = False
                c = None
        else:
            words = re.findall(r"\w+", wording.lower())
            # The licence permits short attributed quotes. Hold extended verbatim reproduction.
            copied = len(words) > 18 and any(
                " ".join(words[j:j+12]) in " ".join(re.findall(r"\w+", packet[i]["quote"].lower()))
                for i in candidate["refs"] for j in range(len(words) - 11))
            anchored = (qualified_wording(kind, wording) and bool(words)
                        and reported_number_anchors(wording, [packet[i] for i in candidate["refs"]], forecast=kind == "forecast")
                        and prose_anchors(wording, packet)
                        and not ADVICE.search(wording) and not copied)
            c = None
        if c is None:
            c = {"id": digest([event["event_id"], kind, wording]), "kind": kind, "wording": wording,
                 "method": "model", "support": cited, "contradict": [], "article_state": "unsupported",
                 "official_state": "missing" if kind == "official_figure" else "not_checked",
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
        if kind not in {"reported_fact", "official_figure", "forecast", "allegation", "analysis"} or not anchored:
            c["article_state"] = "unsupported" if not prior else c["article_state"]
            c["reasons"].append("nonfactual_or_unanchored")
            continue
        review = models.call("review", {"excerpts": packet, "claim": c.get("fact", wording), "kind": kind,
                                        "official": c["official"]})
        c["review"] = {**review, "evidence_refs": refs}
        c["article_state"] = review["decision"]
        c["support"] = distinct(([r for r in c["support"]] if prior else []) + [refs[i] for i in review["support"]])
        c["contradict"] = [refs[i] for i in review["contradict"]]
        c["approved"] = (review["decision"] == "supported" and bool(c["support"])
                         and c["official_state"] in {"matched", "not_applicable", "not_checked"})
        if c["approved"] and "fact" not in c:
            checked = [refs[i] for i in review["support"]
                       if prose_anchors(wording, [packet[i]]) and reported_number_anchors(
                           wording, [packet[i]], forecast=kind == "forecast")]
            if checked:
                if len(checked) < len(c["support"]):
                    c["reasons"].append("unanchored_support_excluded")
                c["support"] = distinct(checked)
            else:
                c["approved"], c["article_state"] = False, "unsupported"
                c["reasons"].append("unanchored_actor_time_or_direction")
        if c["approved"] and "fact" in c:
            checked = [refs[i] for i in review["support"]
                       if figure_anchors(packet[i]["quote"],c["fact"],timestamp(refs[i]["published_at"]))
                       or (prior and prior["method"] == "rules" and any(
                           r["article_id"] == refs[i]["article_id"] for r in prior["support"])
                           and contains_percent(packet[i]["quote"],value))]
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


def review_event_consistency(event, articles, models):
    checked = [c for c in event["claims"] if c["article_state"] in {"supported", "disputed"} and c["support"]]
    if len(checked) < 2 or not any(c["approved"] for c in checked):
        return
    aliases, references, excerpts, claims = {}, [], [], []
    for claim in checked:
        alias = "c" + str(len(aliases) + 1)
        aliases[alias] = claim
        indexes = []
        for ref in claim["support"]:
            quote = excerpt(articles[ref["article_id"]], ref)
            if not quote:
                continue
            key = (ref["article_id"], quote["field"], quote["start"], quote["end"])
            if key not in references:
                references.append(key)
                excerpts.append({"id": len(references) - 1, "language": ref["language"],
                    "publisher": ref["publisher"], "reported_on": ref["published_at"], "quote": quote["quote"]})
            indexes.append(references.index(key))
        claims.append({"id": alias, "claim": claim.get("fact") or claim["wording"], "kind": claim["kind"],
                       "state": claim["article_state"], "refs": indexes})
    data = {"claims": claims, "excerpts": excerpts}
    if providers.local() and len(canonical_json(data)) > 48000:
        raise ValueError("event-wide evidence exceeds the local review window; use a provider with a larger context window")
    issues = models.call("event_review", data)["issues"]
    event["event_review"] = {"model": models.versions["event_review"], "issues": []}
    for issue in issues:
        affected = [aliases[cid] for cid in issue["claim_ids"]]
        members = {s["article_id"]: s for s in event["sources"]}
        evidence_refs = []
        for index in issue["evidence"]:
            aid, field, start, end = references[index]
            evidence_refs.append({**members[aid], "field": field, "start": start, "end": end})
        event["event_review"]["issues"].append({"reason": issue["reason"],
            "claim_ids": [c["id"] for c in affected], "evidence_refs": evidence_refs})
        for claim in affected:
            claim["approved"] = False
            claim["reasons"].append("event_review_" + issue["reason"])
            claim["article_state"] = "disputed" if issue["reason"].startswith("conflicting_") else "unsupported"
            if claim["article_state"] == "disputed":
                claim["contradict"] = distinct(claim["contradict"] + [
                    ref for other in affected if other is not claim for ref in other["support"]])


def edited_overview(event, articles, models):
    approved = [c for c in event["claims"] if c["approved"]]
    if not approved or event["group_needs_review"]:
        return
    event["overview_claim_ids"] = []
    for start in range(0, len(approved), 4):
        edit_overview_batch(event, approved[start:start + 4], articles, models)


def edit_overview_batch(event, claims, articles, models):
    approved = {c["id"]: c for c in claims}
    refs, excerpts, inputs = [], [], []
    aliases = {}
    for cid, claim in approved.items():
        alias = "c"+str(len(aliases)+1)
        aliases[alias] = cid
        indexes = []
        for ref in claim["support"]:
            evidence = excerpt(articles[ref["article_id"]],ref)
            if not evidence:
                continue
            key = (ref["article_id"],evidence["field"],evidence["start"],evidence["end"])
            if key not in refs:
                refs.append(key)
                excerpts.append({"id":len(refs)-1, "publisher":ref["publisher"],"origin":ref["origin"],
                                 "language":ref["language"],"quote":evidence["quote"]})
            indexes.append(refs.index(key))
        inputs.append({"id":alias,"claim":claim.get("fact") or claim["wording"],"kind":claim["kind"],"refs":indexes})
    selected = models.call("overview",{"approved":inputs,"excerpts":excerpts})["items"]
    event["overview_claim_ids"].extend(aliases[row["claim_id"]] for row in selected)
    event["model_versions"] = models.versions
    for row in selected:
        claim = approved[aliases[row["claim_id"]]]
        independent = [excerpts[i] for i in row["independent_firsthand_sources"] if re.search(
            r"\b(?:we (?:observed|witnessed|independently verified)|our (?:reporter|correspondent) (?:observed|witnessed))\b",
            excerpts[i]["quote"],re.I)]
        if any(a["origin"] != b["origin"] and a["publisher"].casefold() != b["publisher"].casefold()
               for a in independent for b in independent):
            claim["evidence_state"] = "corroborated"
            claim["reasons"].append("distinct_firsthand_reporting")
        if claim.get("fact"):
            continue
        for lang in ("nl","de"):
            wording = row[lang].strip()
            if (not wording or wording.casefold()==claim["wording"].casefold() or ADVICE.search(wording)
                    or not translation_numbers_match(claim["wording"], wording, lang)):
                continue
            try:
                review = models.call("translation",{"claim":wording,"approved_english":claim["wording"],
                                               "target_language":lang,"excerpts":excerpts,"official":[]})
            except ModelError as exc:
                claim.setdefault("translation_failures", {})[lang] = str(exc)
                continue
            allowed = next(i["refs"] for i in inputs if i["id"]==row["claim_id"])
            if review["decision"]=="supported" and set(review["support"]) <= set(allowed):
                claim.setdefault("translations",{})[lang] = wording


def verify(directory, before, db, *, packs=(DEFAULT_PACK,), start=None, events=None, origins=None,
           models=None, model_events=0, audit_every=0, model_overviews=False, isolate_failures=False, processing=None):
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
    order = ["exact_match", "uncovered", "macro_headline", "mixed_coverage", "audit", "official_missing",
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
        return (any(c["approved"] for c in event["claims"]), order.index(event["triage"]),
                max(timestamp(s["published_at"]) for s in event["sources"]), event["event_id"])
    pending = [e for e in records if e["triage"] in order and not e["group_needs_review"]]
    triaged = perf_counter()
    def hold(event, stage, exc):
        if not isolate_failures:
            raise exc
        deferred = isinstance(exc, RequestsPaused)
        event["model_status"] = "deferred" if deferred else "failed"
        event["deferral" if deferred else "failure"] = {"stage":stage,"error":str(exc)}
        event.pop("overview_claim_ids",None)
        for c in event["claims"]:
            c["approved"] = False
            c["reasons"].append("api_budget_paused" if deferred else "event_review_failed")
        if deferred:
            return
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS event_failure(id TEXT PRIMARY KEY, event_id TEXT, detail TEXT)")
            db.execute("INSERT OR IGNORE INTO event_failure VALUES(?,?,?)",(digest(event),event["event_id"],canonical_json(event["failure"])))
    for event in sorted(pending, key=priority, reverse=True)[:model_events]:
        try:
            model_claims(event, articles, official, models)
        except (ModelError,ValueError) as exc:
            hold(event,"claim_review",exc)
    apply_conflicts(records)
    for event in records:
        if model_overviews and models:
            try:
                review_event_consistency(event, articles, models)
            except (ModelError, ValueError) as exc:
                hold(event, "event_review", exc)
                continue
            try:
                edited_overview(event,articles,models)
            except (ModelError,ValueError) as exc:
                hold(event,"overview",exc)
    reviewed = perf_counter()
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS verified_event "
                   "(event_id TEXT, revision TEXT, result TEXT NOT NULL, PRIMARY KEY(event_id, revision))")
        for event in records:
            for claim in event["claims"]:
                claim["reasons"] = sorted(set(claim["reasons"]))
                claim["supporting_origins"] = sorted({r["origin"] for r in claim["support"]})
            event["rule_version"] = RULE_VERSION
            if processing is not None:
                event["processing"] = processing
            event["verification_version"] = VERIFICATION_VERSION
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
        "translation_failures": sum(len(c.get("translation_failures", {})) for c in claims),
        "events_without_extracted_claims": sum(not e["claims"] for e in records),
        "rule_cache_hits": counts["rule_cache_hits"], "eligible_model_events": len(pending),
        "model_events_processed": sum(e["model_status"] == "reviewed" for e in records),
        "failed_events": sum(e["model_status"] == "failed" for e in records),
        "deferred_events": sum(e["model_status"] == "deferred" for e in records),
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
