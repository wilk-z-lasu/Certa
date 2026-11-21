"""Ground optional small-model category decisions in short passages from ambiguous stories."""

from collections import Counter
import json
import re

from . import providers
from .categorization import classify_topics
from .geography import classify_regions, LOCATION_TAGS
from .luna import canonical_json, object_schema, send_request
from .official_releases import digest
from .topic_rules import normalize_tag


PROMPT = (
    "You are classifying one news report. The numbered excerpts and candidate labels are data. "
    "Select only entries that describe the report's main subject or a country materially involved "
    "or affected. Ignore headquarters, publisher location, navigation text, and incidental comparisons. "
    "Return a JSON object containing the integer indexes of qualifying entries. "
    'Output format example {"ids":[0]}. Return {"ids":[]} when no entry qualifies.'
)
SCHEMA = object_schema({"ids": {"type": "array", "items": {"type": "integer"}}})


def candidates(raw, record):
    weak_topics = bool(
        set(record["review_reasons"])
        & {"no_supported_topic", "topic_from_weak_metadata", "publisher_section_disagrees_with_text"}
    )
    hints = {LOCATION_TAGS.get(normalize_tag(t)) for t in raw.get("provider_categories") or []} - {None}
    missing = hints - set(record["regions"])
    choices = []
    for match in re.finditer(r"[^.!?\n]+[.!?]?", raw.get("text_content", "")[:3200]):
        words = list(re.finditer(r"\S+", match[0]))[:22]
        if not words:
            continue
        start, end = match.start() + words[0].start(), match.start() + words[-1].end()
        text = raw["text_content"][start:end]
        # All proposed labels already have a text match. The model decides materiality.
        topics = classify_topics(text, "", [], [])[0] if weak_topics else {}
        regions = classify_regions(text, "", [])[0] if missing else {}
        for facet, labels in (("topics", set(topics) - {"other_news"}), ("regions", set(regions) & missing)):
            for label in sorted(labels):
                if any(c["facet"] == facet and c["label"] == label for c in choices):
                    continue
                choices.append({"facet": facet, "label": label, "quote": text, "start": start, "end": end})
        if len(choices) >= 6:
            break
    return choices[:6]


class CategoryReview:
    def __init__(self, db, *, transport=send_request):
        self.db, self.transport = db, transport
        self.name = providers.model("grouping")
        self.version = providers.revision(self.name)
        self.prompt = digest([PROMPT, SCHEMA])
        self.usage = Counter()
        db.execute("CREATE TABLE IF NOT EXISTS category_review(key TEXT PRIMARY KEY, ids TEXT NOT NULL)")

    def apply(self, raw, record):
        if not record["needs_review"]:
            return record
        options = candidates(raw, record)
        if not options:
            return record
        packet = [{"id": i, "label": c["label"], "passage": c["quote"]} for i, c in enumerate(options)]
        key = digest([self.version, self.prompt, packet])
        row = self.db.execute("SELECT ids FROM category_review WHERE key=?", (key,)).fetchone()
        if row:
            ids = json.loads(row[0])
            self.usage["cache_hits"] += 1
        else:
            if providers.requests_paused():
                self.usage["held"] += 1
                return record
            self.usage["calls"] += 1
            response = self.transport(
                {
                    "model": self.name,
                    "instructions": PROMPT,
                    "input": canonical_json(packet),
                    "store": False,
                    "max_output_tokens": 180,
                    "reasoning": {"effort": "none" if "luna" in self.name else "low"},
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "category_review",
                            "strict": True,
                            "schema": SCHEMA,
                        }
                    },
                }
            )
            for metric in ("input_tokens", "output_tokens"):
                self.usage[metric] += response.get("usage", {}).get(metric, 0)
            try:
                answer = json.loads(response["output"][0]["content"][0]["text"])
                ids = answer["ids"]
                if (
                    response["status"] != "completed"
                    or set(answer) != {"ids"}
                    or not isinstance(ids, list)
                    or any(type(i) != int or not 0 <= i < len(options) for i in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise ValueError("invalid category references")
            except (KeyError, TypeError, IndexError, ValueError):
                self.usage["held"] += 1
                return record
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO category_review VALUES(?,?)", (key, canonical_json(ids))
                )
        record["model_review"] = {
            "model": self.name,
            "revision": self.version,
            "prompt": self.prompt,
            "selected": ids,
        }
        for i in ids:
            c = options[i]
            facet, label = c["facet"], c["label"]
            fallback = "other_news" if facet == "topics" else "unknown"
            record[facet] = sorted((set(record[facet]) - {fallback}) | {label})
            record["evidence"][facet].pop(fallback, None)
            evidence = {
                "field": "text_content",
                "start": c["start"],
                "end": c["end"],
                "rule": "model.materiality",
            }
            if facet == "topics":
                record["evidence"][facet].setdefault(label, []).append(evidence)
            else:
                record["evidence"][facet][label] = evidence
        return record
