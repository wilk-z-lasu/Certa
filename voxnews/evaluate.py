"""Evaluate a published run against labeled event pairs or trace a saved text edition."""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from generate_script import validate_daily
from .group_events import read_jsonl, timestamp
from .official_releases import digest
from .overview_reader import connect, get_event, Passages
from build_preai import approved_claim


def evaluate_pairs(events, reference):
    members, origins = {}, {}
    for location, event in read_jsonl(events):
        for source in event["sources"]:
            aid = source["article_id"]
            if aid in members:
                raise ValueError(f"{location}: duplicate story membership")
            members[aid] = (event["event_id"], event["status"])
            origins[aid] = source["reporting_origin_id"]
    results, counts = [], Counter()
    for row in reference["pairs"]:
        left, right, expected = row["left"], row["right"], row["same_event"]
        if type(expected) is not bool:
            raise ValueError("Reference labels must be booleans")
        if left not in members or right not in members:
            outcome = "outside_run"
        else:
            matched = members[left][0] == members[right][0] and members[left][1] != "needs_review"
            outcome = (
                ("true_positive" if expected else "false_positive")
                if matched
                else ("false_negative" if expected else "true_negative")
            )
        counts[outcome] += 1
        results.append(
            {**row, "result": outcome, "left_event": members.get(left), "right_event": members.get(right)}
        )
    tp = counts["true_positive"]
    return {
        "reference": reference["basis"],
        "stories": len(members),
        "reporting_origins": len(set(origins.values())),
        "counts": dict(counts),
        "precision": tp / (tp + counts["false_positive"]) if tp + counts["false_positive"] else None,
        "recall": tp / (tp + counts["false_negative"]) if tp + counts["false_negative"] else None,
        "pairs": results,
    }


def text_audit(path, draft, briefing):
    validate_daily(draft, briefing)
    if digest({k: v for k, v in draft.items() if k != "id"}) != draft["id"]:
        raise ValueError("Draft checksum mismatch")
    checks = []
    draft_events = {event["event_id"]: event for event in draft["events"]}
    cutoff = timestamp(draft["cutoff_exclusive"])
    with closing(connect(path)) as db:
        db.execute("BEGIN")
        for segment in briefing["segments"]:
            event = get_event(db, segment["event_id"], segment["revision"])
            expected_caveats = ["unresolved_reporting"] if event["disagreements"] else []
            if draft_events[segment["event_id"]].get("caveats", []) != expected_caveats:
                raise ValueError("Draft caveats differ from the immutable overview")
            if event["group_needs_review"] or any(
                timestamp(event["sources"][aid]["published_at"]) >= cutoff for aid in event["members"]
            ):
                raise ValueError("Unresolved grouping or future source")
            item = next((i for i in event["items"] if i["id"] == segment["claim_id"]), None)
            approved = approved_claim(item, event, draft["selection"]["language"], None) if item else None
            if not approved or any(approved[k] != segment[k] for k in ("text", "claim_id", "sources")):
                raise ValueError("Transcript differs from the immutable overview")
            reader = Passages(db)
            evidence = []
            for ref in approved["sources"]:
                source = event["sources"][ref["source_id"]]
                if ref["role"] == "supports":
                    passage = reader.text(ref, event["sources"])
                    if not passage.strip():
                        raise ValueError("Empty supporting passage")
                elif timestamp(source["available_at"]) >= cutoff:
                    raise ValueError("Official observation postdates the briefing")
                evidence.append(
                    {
                        k: v
                        for k, v in ref.items()
                        if k
                        in {
                            "source_id",
                            "url",
                            "label",
                            "role",
                            "locator",
                            "start",
                            "end",
                            "field",
                            "value",
                            "unit",
                        }
                    }
                )
            checks.append(
                {
                    "claim": segment["text"],
                    "event": event["event_id"],
                    "revision": event["revision"],
                    "claim_id": segment["claim_id"],
                    "fact": item.get("fact"),
                    "evidence": evidence,
                }
            )
    return {
        "scope": "Validated text and source provenance",
        "draft": draft["id"],
        "date": draft["date"],
        "checked": checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    group = sub.add_parser("grouping")
    group.add_argument("events", type=Path)
    group.add_argument("--reference", type=Path, default=Path("examples/manual-event-reference.json"))
    audit = sub.add_parser("transcript")
    audit.add_argument("--db", type=Path, default=Path("output/event-overviews.sqlite3"))
    choice = audit.add_mutually_exclusive_group(required=True)
    choice.add_argument("--edition", help="Saved listener edition ID")
    choice.add_argument("--example", type=Path, help="JSON object containing draft and briefing")
    audit.add_argument("--listeners", type=Path, default=Path("user_data/listeners.sqlite3"))
    args = parser.parse_args()
    try:
        if args.action == "grouping":
            result = evaluate_pairs(args.events, json.loads(args.reference.read_bytes()))
        else:
            if args.example:
                saved = json.loads(args.example.read_bytes())
            else:
                with closing(connect(args.listeners)) as users:
                    row = users.execute(
                        "SELECT draft,briefing FROM delivery WHERE edition=?", (args.edition,)
                    ).fetchone()
                if not row:
                    raise ValueError("Unknown briefing edition")
                saved = {"draft": json.loads(row[0]), "briefing": json.loads(row[1])}
            result = text_audit(args.db, saved["draft"], saved["briefing"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
