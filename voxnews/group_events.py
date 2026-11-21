"""Group categorized articles into events with local E5 and GPT-6 Luna."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import NamedTemporaryFile
from time import perf_counter

from .categorization import validate_article
from .categorize import reject_constant
from .event_candidates import Article, CandidateIndex, reporting_origins
from .event_embeddings import E5Encoder
from .event_groups import event_records, form_groups
from .luna import BATCH_SIZE, MODEL, Decision, LunaJudge, ModelError, usage_cost
from . import providers
from .topic_rules import TOPICS


UTC = timezone.utc
REGION = re.compile(r"[A-Z]{2}|global|unknown")


def timestamp(value, *, allow_date=False):
    if not isinstance(value, str):
        raise ValueError("expected an ISO 8601 timestamp")
    result = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    if allow_date and len(value) == 10:
        return result.replace(tzinfo=UTC)
    if result.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return result.astimezone(UTC)


def indexed_jsonl(path):
    with path.open("rb") as file:
        offset = 0
        for number, line in enumerate(file, 1):
            location = f"{path.name}:{number}"
            try:
                row = json.loads(line.decode("utf-8"), parse_constant=reject_constant)
                if not isinstance(row, dict):
                    raise ValueError("expected a JSON object")
            except (ValueError, RecursionError) as error:
                raise ValueError(f"{location}: {error}") from error
            yield location, row, offset, len(line)
            offset += len(line)


def read_jsonl(path):
    for location, row, _, _ in indexed_jsonl(path):
        yield location, row


def string_field(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def read_categories(path):
    categories = {}
    for location, row in read_jsonl(path):
        try:
            article_id = string_field(row, "article_id")
            if article_id in categories:
                raise ValueError(f"duplicate category record for {article_id!r}")
            topics, regions = row.get("topics"), row.get("regions")
            if not isinstance(topics, list) or not topics or any(topic not in TOPICS for topic in topics):
                raise ValueError("topics must contain supported topic IDs")
            if (
                not isinstance(regions, list) or not regions
                or any(not isinstance(region, str) or not REGION.fullmatch(region) for region in regions)
            ):
                raise ValueError("regions must contain country codes or scope labels")
            categories[article_id] = row
        except ValueError as error:
            raise ValueError(f"{location}: {error}") from error
    return categories


def load_articles(input_dir, category_path, start=None, before=None):
    categories = read_categories(category_path)
    paths = sorted(input_dir.glob("*.jsonl"))
    if not paths:
        raise ValueError(f"no JSONL feeds found in {input_dir}")
    seen, articles = set(), []
    for path in paths:
        for location, row in read_jsonl(path):
            try:
                validate_article(row)
                article_id = row["$id"]
                if article_id in seen:
                    raise ValueError(f"duplicate source ID {article_id!r}")
                seen.add(article_id)
                published = timestamp(row.get("date"))
                if (start and published < start) or (before and published >= before):
                    continue
                if article_id not in categories:
                    raise ValueError(f"missing category record for {article_id!r}")
                category = categories[article_id]
                if any(row[field] != category.get(field) for field in ("permalink", "language")):
                    raise ValueError(f"category metadata differs from source for {article_id!r}")
                for field in ("source", "text_content"):
                    if row.get(field) is not None and not isinstance(row[field], str):
                        raise ValueError(f"{field} must be a string when present")
                articles.append(Article.from_source(row, category, path.stem, published))
            except ValueError as error:
                raise ValueError(f"{location}: {error}") from error
    if extra_ids := categories.keys() - seen:
        raise ValueError(f"category record has no source article for {min(extra_ids)!r}")
    return sorted(articles, key=lambda article: (article.published, article.id))


def previous_events(path):
    if path is None:
        return []
    events, anchors, ids = [], set(), set()
    for location, row in read_jsonl(path):
        try:
            anchor, event_id = string_field(row, "anchor_article_id"), string_field(row, "event_id")
            if anchor in anchors or event_id in ids:
                raise ValueError("prior event anchors and IDs must be unique")
            anchors.add(anchor)
            ids.add(event_id)
            events.append(row)
        except ValueError as error:
            raise ValueError(f"{location}: {error}") from error
    return events


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def candidate_records(comparisons, origins, articles, reviews):
    for origin, members in origins.items():
        yield {
            "kind": "reporting_origin", "anchor_article_id": articles[origin].id,
            "article_ids": [articles[i].id for i in members],
            "review_article_ids": [articles[i].id for i in members if i in reviews],
        }
    for pair in comparisons.values():
        yield {
            "kind": "candidate_pair", "article_ids": [articles[i].id for i in pair.key],
            "similarity": pair.similarity,
        }


def offline_events(input_dir, categories, output, *, start, before, previous=None):
    articles = load_articles(input_dir, categories, start, before)
    index = CandidateIndex(articles, None)
    origins, origin_reviews = reporting_origins(articles)
    pairs = index.signature_pairs(origins)
    decisions = {
        pair.key: Decision("same_event", "matching_release" if feature == "reporting_period" else "matching_occurrence",
                           (feature, "timing"))
        for pair in pairs.values() if (feature := pair.matching_signature(articles))
    }
    groups, reviews, _ = form_groups(index, origins, pairs, decisions)
    records = list(event_records(groups, origins, reviews, origin_reviews, articles, decisions,
                                 previous_events(previous), "occurrence-rules", "occurrence-rules-1"))
    write_jsonl(output, records)
    return {"articles": len(articles), "reporting_origins": len(origins), "events": len(records),
            "event_status": dict(Counter(record["status"] for record in records)),
            "signature_matches": len(decisions), "model": "occurrence-rules", "luna_calls": 0}


def run(
    input_dir: Path, categories: Path, output: Path, *,
    encoder, judge, start=None, before=None, previous=None, candidates_only=False,
):
    input_root = input_dir.resolve()
    output_path = output.resolve()
    if input_root in output_path.parents or output_path == categories.resolve():
        raise ValueError("write event output outside the input feeds and category file")
    if start and before and start >= before:
        raise ValueError("--from must be earlier than --before")

    started = perf_counter()
    articles = load_articles(input_dir, categories, start, before)
    previous_rows = [] if candidates_only else previous_events(previous)
    vectors = encoder(articles) if articles else None
    embedded = perf_counter()
    index = CandidateIndex(articles, vectors)
    origins, origin_reviews = reporting_origins(articles, index)
    comparisons = index.shortlist(list(origins))
    signatures = index.signature_pairs(origins)
    feature_candidates = len(comparisons.keys() | signatures.keys())
    if not candidates_only and providers.local():
        comparisons = {k:p for k,p in comparisons.items() if p.local_candidate(articles)}
    comparisons.update(signatures)
    shortlisted = perf_counter()
    summary = {
        "articles": len(articles), "reporting_origins": len(origins),
        "duplicate_or_translation_articles": len(articles) - len(origins),
        "unconfirmed_translations": len(origin_reviews),
        "candidate_pairs": len(comparisons),
        "feature_candidates": feature_candidates,
        "uncached_initial_batches": (len(comparisons) + BATCH_SIZE - 1) // BATCH_SIZE,
        "embedding_and_load_seconds": round(embedded - started, 3),
        "shortlist_seconds": round(shortlisted - embedded, 3),
    }
    if candidates_only:
        write_jsonl(output, candidate_records(comparisons, origins, articles, origin_reviews))
    else:
        decisions = judge.judge(list(comparisons.values()), articles)
        groups, reviews, anchors_to_check = form_groups(index, origins, comparisons, decisions)
        anchor_pairs = 0
        # Recheck likely links to the anchor without allowing transitive joins.
        for _ in range(2):
            if not anchors_to_check:
                break
            anchor_pairs += len(anchors_to_check)
            decisions.update(judge.judge(list(anchors_to_check.values()), articles))
            comparisons.update(anchors_to_check)
            groups, reviews, anchors_to_check = form_groups(index, origins, comparisons, decisions)
        grouping_model = getattr(judge,"model",MODEL)
        unmetered = judge.stats["luna_calls"] - judge.stats.get("metered_calls", 0)
        stage_cost = None
        if providers.local() or judge.stats["luna_calls"] == 0:
            stage_cost = 0
        elif grouping_model == MODEL and not unmetered:
            stage_cost = usage_cost(judge.stats)
        records = list(event_records(groups, origins, reviews, origin_reviews, articles, decisions, previous_rows, grouping_model, getattr(judge,"prompt_version",None)))
        write_jsonl(output, records)
        summary.update({
            "events": len(records),
            "event_status": dict(Counter(record["status"] for record in records)),
            "decisions": dict(Counter(decision.label for decision in decisions.values())),
            "anchor_comparisons": anchor_pairs, "model": grouping_model, "model_revision": getattr(judge,"revision",grouping_model),
            **{key: judge.stats[key] for key in (
                "luna_calls", "invalid_local_decisions", "retries", "cache_hits", "input_tokens", "cached_input_tokens", "output_tokens",
                "signature_matches",
            )},
            "unmetered_calls": unmetered,
            "estimated_usage_cost_usd": None if stage_cost is None else round(stage_cost, 6),
            "estimated_10x_usage_cost_usd": None if stage_cost is None else round(10 * stage_cost, 6),
        })

    seconds = perf_counter() - started
    summary["seconds"] = round(seconds, 3)
    # At 10x volume over the same dates, the number of comparisons inside each
    # window can grow quadratically while encoding is linear.
    summary["estimated_10x_seconds"] = round(10 * seconds + 90 * (shortlisted - embedded), 3)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("liquid-briefing-data"))
    parser.add_argument("--categories", type=Path, default=Path("output/categories.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-dir", type=Path, default=Path("output/e5-small"))
    parser.add_argument("--cache", type=Path, default=Path("output/luna-decisions.sqlite3"))
    parser.add_argument("--previous", type=Path, help="prior event JSONL for stable IDs")
    parser.add_argument("--from", dest="start", help="earliest UTC date or timestamp, inclusive")
    parser.add_argument("--before", help="UTC date or timestamp cutoff, exclusive")
    parser.add_argument("--candidates-only", action="store_true", help="export local candidates and origins without the API")
    args = parser.parse_args()
    try:
        if not args.candidates_only and (
            args.cache.resolve() in {args.output.resolve(), args.categories.resolve()}
            or args.input_dir.resolve() in args.cache.resolve().parents
        ):
            raise ValueError("use a separate cache path outside the input feeds")
        summary = run(
            args.input_dir, args.categories, args.output, encoder=E5Encoder(args.embedding_dir),
            judge=LunaJudge(args.cache), previous=args.previous, candidates_only=args.candidates_only,
            start=timestamp(args.start, allow_date=True) if args.start else None,
            before=timestamp(args.before, allow_date=True) if args.before else None,
        )
    except (OSError, ModelError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"event grouping failed: {error}\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
