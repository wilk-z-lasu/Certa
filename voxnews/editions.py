"""As-of editorial selection and personalization over published catalogue snapshots."""

from contextlib import closing
from datetime import date, timedelta
import json

from build_preai import NoCoverage, REGIONS, approved_claim
from .topic_rules import TOPIC_LABELS
from .official_releases import digest
from .overview_reader import catalogue, connect, get_event
from .group_events import timestamp


def dates(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='daily_window'").fetchone():
        cutoffs = [r[0] for r in db.execute("SELECT cutoff FROM daily_window ORDER BY cutoff DESC")]
    else:
        meta = json.loads(db.execute("SELECT metadata FROM build_info WHERE id=1").fetchone()[0])
        cutoffs = [meta["report"]["cutoff_exclusive"]]
    published = {}
    for cutoff in cutoffs:
        day = (timestamp(cutoff) - timedelta(microseconds=1)).date().isoformat()
        published.setdefault(day, cutoff)
    return published


def published_events(db, cutoff):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='daily_event'").fetchone():
        rows = db.execute("SELECT event_id,revision,latest FROM daily_event WHERE cutoff=?", (cutoff,))
    else:
        rows = [(r["event_id"], r["revision"], r["latest"]) for r in catalogue(db)]
    for eid, revision, latest in rows:
        event = get_event(db, eid, revision)
        if not event["group_needs_review"] and timestamp(latest) < timestamp(cutoff):
            yield eid, revision, latest, event


def picker_options(path, day, region, language):
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        available = dates(db)
        day = day or next(iter(available), None)
        if day not in available:
            raise NoCoverage("No catalogue has been published for this date.")
        counts = {
            topic: {"id": topic, "label": label, "events": 0, "local": 0}
            for topic, label in TOPIC_LABELS.items()
        }
        for _, _, _, event in published_events(db, available[day]):
            claims = [i for i in event["items"] if approved_claim(i, event, language, None)]
            if claims:
                local = bool(region and any(approved_claim(i, event, language, region) for i in claims))
                for topic in event["topics"]:
                    counts[topic]["events"] += 1
                    counts[topic]["local"] += int(local)
    return {"topics": list(counts.values()), "regions": REGIONS, "date": day, "dates": list(available)}


def personal_draft(path, profile, day, history):
    day = date.fromisoformat(day)
    events = []
    prefs = set(profile["topics"])
    previous = history.get("by_event", {})
    region, lang = profile["region"], profile["language"]
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        cutoff = dates(db).get(day.isoformat())
        if not cutoff:
            raise NoCoverage("There is no published catalogue for this briefing date.")
        for eid, revision, latest, event in published_events(db, cutoff):
            topics = prefs.intersection(event["topics"])
            if not topics:
                continue
            claims = []
            for item in event["items"]:
                if item["id"] in previous.get(eid, ()):
                    continue
                claim = approved_claim(item, event, lang, None)
                if not claim:
                    continue
                claim["coverage_id"] = digest(item.get("fact") or [item["kind"], item["summary"].casefold()])
                if claim["coverage_id"] in history.get("coverage", ()) or claim[
                    "text"
                ].casefold() in history.get("wording", ()):
                    continue
                claim["local"] = bool(region and approved_claim(item, event, lang, region))
                claim["reported_on"] = (
                    max(
                        timestamp(event["sources"][s["source_id"]]["published_at"])
                        for s in claim["sources"]
                        if s["role"] == "supports"
                    )
                    .date()
                    .isoformat()
                )
                claim["evidence_state"] = item.get("evidence_state", item["article_state"])
                claims.append(claim)
            if not claims:
                continue
            hours = (timestamp(cutoff) - timestamp(latest)).total_seconds() / 3600
            breadth = len({event["sources"][s]["origin"] for s in event["members"]})
            official = any(s["role"] == "official_at_cutoff" for c in claims for s in c["sources"])
            recency = 3 / (1 + hours / 24)
            impact = int(official) + int(len(set(event["regions"]) - {"unknown"}) > 1)
            score = recency + min(2, breadth - 1) + impact
            affinity = max(profile["weights"].get(t, 0) for t in topics)
            local = any(c["local"] for c in claims)
            synopsis = {cid: i for i, cid in enumerate(event["synopsis_ids"])}
            claims.sort(key=lambda c: (not c["local"], synopsis.get(c["claim_id"], len(synopsis))))
            events.append(
                {
                    "event_id": eid,
                    "revision": revision,
                    "overview": {
                        "title": event["title"],
                        "limitations": event["limitations"],
                        "coverage": event.get("overview_coverage", {}),
                    },
                    "caveats": ["unresolved_reporting"] if event["disagreements"] else [],
                    "topics": event["topics"],
                    "claims": claims,
                    "section": "local" if local else "general",
                    "latest": latest,
                    "development": "update" if eid in previous else "new_to_listener",
                    "dated_context": timestamp(latest).date() < day,
                    "rank": round(score + affinity, 4),
                    "reason": {
                        "matched_topics": sorted(topics),
                        "topic_weight": affinity,
                        "hours_before_cutoff": round(hours, 1),
                        "reporting_origins": breadth,
                        "impact_points": impact,
                        "editorial_score": round(score, 4),
                    },
                }
            )
    events.sort(key=lambda e: (e["section"] == "local", e["rank"], e["latest"], e["event_id"]), reverse=True)
    seen, ordered, words = set(), [], 0
    budget = profile["minutes"] * 135
    depth_limit = {"headlines": 1, "standard": 3, "detailed": 8}[profile["depth"]]
    for event in events:
        chosen = []
        for claim in event["claims"]:
            n = len(claim["text"].split())
            key = claim["text"].casefold()
            if key in seen or (words and words + n > budget):
                continue
            chosen.append(claim)
            words += n
            seen.add(key)
            if len(chosen) == depth_limit:
                break
        if chosen:
            ordered.append({**event, "claims": chosen})
    if not ordered:
        raise NoCoverage("No new approved reporting matches this profile on this date.")
    draft = {
        "date": day.isoformat(),
        "cutoff_exclusive": cutoff,
        "profile_version": profile["version"],
        "selection": {k: profile[k] for k in ("topics", "region", "language", "depth", "minutes", "weights")},
        "events": ordered,
        "word_budget": budget,
        "selected_words": words,
        "coverage": {
            "sparse": words < budget * 0.65,
            "local_available": any(e["section"] == "local" for e in ordered),
            "estimated_seconds": round(words * 60 / 135),
        },
    }
    return {**draft, "id": digest(draft)}
