"""Select approved claims from the current editorial catalogue for a listener."""
import json
import os
from contextlib import closing
from pathlib import Path

from voxnews.geography import COUNTRIES
from voxnews import providers
from voxnews.official_releases import safe_url
from voxnews.overview_reader import catalogue, connect, get_event
from voxnews.topic_rules import TOPICS, TOPIC_LABELS
from voxnews.trust_briefing import DISCLOSURE, spoken_figure
from voxnews.verify import write_atomic


ROOT = Path(__file__).resolve().parent
REGIONS = sorted({*COUNTRIES, "EA"})


class NoCoverage(ValueError):
    """No approved claims match these preferences."""


def database_path():
    default = ROOT / "output" / ("cloud-demo" if providers.cloud_only() else "") / "event-overviews.sqlite3"
    return Path(os.environ.get("VOXNEWS_OVERVIEW_DB") or default)


def preferences(topics, region=None, language="en"):
    if not isinstance(topics, list) or not topics or any(t not in TOPICS for t in topics):
        raise ValueError("Choose at least one listed topic.")
    if region is not None and region not in REGIONS:
        raise ValueError("Choose a listed region or all regions.")
    if not isinstance(language, str) or language not in DISCLOSURE:
        raise ValueError("Choose English, German or Dutch.")
    return {"topics": list(dict.fromkeys(topics)), "region": region, "language": language}


def approved_claim(item, event, language, region):
    if providers.cloud_only() and not providers.cloud_event(event):
        return None
    if (item["type"] != "checked_claim" or item["draft_use"] != "approved_wording"
            or item["article_state"] != "supported" or item["disagreements"]):
        return None
    fact = item.get("fact")
    if fact:
        if region and fact["geo"] != region:
            return None
        wording = spoken_figure(fact, language, version=item.get("wording_version", 1))
    else:
        if region and region not in item.get("claim_regions",{}):
            return None
        wording = item["summary"] if language == item["language"] else item.get("translations",{}).get(language)
        if not wording:
            return None
    sources = []
    for ref in item["evidence"]:
        if ref["role"] not in {"supports", "official_at_cutoff"}:
            continue
        source = event["sources"][ref["source_id"]]
        sources.append({**ref, "url": safe_url(source["url"]),
                        "label": source.get("publisher") or source["issuer"]})
    if not any(s["role"] == "supports" for s in sources):
        return None
    return {"claim_id": item["id"], "text": wording, "sources": sources,
            "kind": item["kind"], "qualifiers": item.get("qualifiers", []), "facets": item.get("sections", [])}


def eligible_events(path, language="en", region=None, topics=()):
    """Read a consistent set of latest revisions and yield each matching event once."""
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        for row in catalogue(db):
            if topics and not set(topics).intersection(row["topics"]):
                continue
            event = get_event(db, row["event_id"], row["revision"])
            if event["group_needs_review"]:
                continue
            claims = [claim for item in event["items"]
                      if (claim := approved_claim(item, event, language, region))]
            if claims:
                yield {"event_id": row["event_id"], "revision": row["revision"],
                       "processing": event.get("processing", {}), "model_status": event.get("model_status"),
                       "model_versions": event.get("model_versions", {}),
                       "topics": row["topics"], "claims": claims,
                       "caveats": ["unresolved_reporting"] if event["disagreements"] else []}


def category_options(path, region=None, language="en"):
    preferences(list(TOPICS), region, language)
    counts = dict.fromkeys(TOPICS, 0)
    for event in eligible_events(path, language, region):
        for topic in event["topics"]:
            counts[topic] += 1
    return {"topics": [{"id": t, "label": TOPIC_LABELS[t], "events": counts[t]} for t in TOPICS],
            "regions": REGIONS}


def make_draft(path, selection):
    events = []
    seen = set()
    for event in eligible_events(path, selection["language"], selection["region"], selection["topics"]):
        unique = []
        for claim in event["claims"]:
            if claim["text"] not in seen:
                unique.append(claim)
                seen.add(claim["text"])
        if unique:
            events.append({**event, "claims": unique})
        if len(events) >= 12:
            break
    if not events:
        raise NoCoverage("No approved reporting matches these topics, region and language.")
    return {"selection": selection, "events": events}


def build_preai(directory, path=None):
    saved = directory / "listener_preferences.json"
    if saved.is_file():
        selection = preferences(**json.loads(saved.read_text(encoding="utf-8")))
    else:
        # The old CLI read one topic per line. Only canonical IDs resolve in the catalogue.
        legacy = directory / "user_liked_categories"
        topics = legacy.read_text(encoding="utf-8").splitlines() if legacy.is_file() else []
        if not topics or any(t not in TOPICS for t in topics):
            raise ValueError("Choose topics in the listener app to save your catalogue preferences.")
        selection = preferences(topics)
    draft = make_draft(path or database_path(), selection)
    write_atomic(directory / "preAI.json", json.dumps(draft, ensure_ascii=False, indent=2))
    return draft


if __name__ == "__main__":
    build_preai(ROOT / "user_data")
