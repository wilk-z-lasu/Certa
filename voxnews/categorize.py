"""Categorize a directory of JSONL article feeds and write a local handoff."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from time import perf_counter

from .categorization import categorize_article
from .topic_rules import TOPICS


def reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def run(input_dir: Path, output: Path) -> dict:
    """Write classifications only after validating and processing every feed."""
    if input_dir.resolve() in output.resolve().parents:
        raise ValueError("output must be outside the directory containing the source feeds")
    feed_paths = sorted(input_dir.glob("*.jsonl"))
    if not feed_paths:
        raise ValueError(f"no JSONL feeds found in {input_dir}")

    started = perf_counter()
    source_rows = {}
    feeds = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            for feed in feed_paths:
                topics = Counter(dict.fromkeys(TOPICS, 0))
                totals = Counter(articles=0, needs_review=0, unknown_region=0, multiple_topics=0)
                with feed.open("rb") as source:
                    for line_number, line in enumerate(source, start=1):
                        location = f"{feed.name}:{line_number}"
                        try:
                            article = json.loads(line.decode("utf-8"), parse_constant=reject_constant)
                            record = categorize_article(article)
                        except (ValueError, RecursionError) as error:
                            raise ValueError(f"{location}: {error}") from error

                        article_id = record["article_id"]
                        if article_id in source_rows:
                            raise ValueError(f"{location}: duplicate article ID {article_id!r}, first seen at {source_rows[article_id]}")
                        source_rows[article_id] = location
                        temporary.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                        topics.update(record["topics"])
                        totals["articles"] += 1
                        totals["needs_review"] += record["needs_review"]
                        totals["unknown_region"] += record["regions"] == ["unknown"]
                        totals["multiple_topics"] += len(record["topics"]) > 1

                feeds[feed.name] = {**totals, "topic_counts": dict(topics)}
        temporary_path.replace(output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    seconds = perf_counter() - started
    return {"articles": len(source_rows), "seconds": round(seconds, 3), "estimated_seconds_10x": round(seconds * 10, 3), "feeds": feeds}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("liquid-briefing-data"), help="directory containing the JSONL feeds")
    parser.add_argument("--output", type=Path, required=True, help="path for the local JSONL results")
    args = parser.parse_args()
    try:
        summary = run(args.input_dir, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"categorization failed: {error}\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
