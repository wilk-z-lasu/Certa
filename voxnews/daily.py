"""Prepare and publish the source-to-event pipeline for a historical briefing day."""

import argparse
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter

from md_to_speech import load_dotenv
from . import providers
from .claim_models import ClaimModels
from .category_review import CategoryReview
from .event_embeddings import E5Encoder
from .group_events import run as group_events
from .luna import LunaJudge, ModelError, canonical_json
from .overview import build
from .source_store import export_import, import_feeds
from .verify import verify, write_atomic


def prepare(
    directory, out, day, lookback, *, offline=False, embedding_dir=None, model_events=None, previous=None
):
    started = perf_counter()
    if not 1 <= lookback <= 366:
        raise ValueError("lookback must be between 1 and 366 days")
    if model_events is not None and model_events < 1:
        raise ValueError("model-events must be positive in model mode; use --offline for rules only")
    store = out / "sources.sqlite3"
    out.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out / "claim-cache.sqlite3", timeout=60)) as classification_db:
        reviewer = None if offline else CategoryReview(classification_db)
        imported = import_feeds(directory, store, reviewer)
        classification = {"model": reviewer.name, **reviewer.usage} if reviewer else {"calls": 0}
    source = out / "imports" / imported["edition"]
    export_import(store, imported["edition"], source)
    import_seconds = perf_counter() - started
    feeds, categories = source / "feeds", source / "categories.jsonl"
    cutoff = datetime.combine(day + timedelta(days=1), time.min, timezone.utc)
    start = cutoff - timedelta(days=lookback)
    run_dir = out / "days" / day.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    # Stage outputs are private to each attempt until validation and publication succeed.
    if not offline and previous is None:
        prior = sorted(p for p in (out / "days").glob("*/events.jsonl") if p.parent.name <= day.isoformat())
        previous = prior[-1] if prior else None
    with (
        TemporaryDirectory(dir=run_dir) as tmp,
        closing(sqlite3.connect(out / "claim-cache.sqlite3", timeout=60)) as db,
    ):
        stage = Path(tmp)
        events, models, grouping = None, None, None
        if not offline:
            events = stage / "events.jsonl"
            grouping = group_events(
                feeds,
                categories,
                events,
                start=start,
                before=cutoff,
                encoder=E5Encoder(embedding_dir or out / "e5-small"),
                judge=LunaJudge(out / "luna-decisions.sqlite3"),
                previous=previous,
            )
            models = ClaimModels(db, providers.model("extraction"), providers.model("review"))
        snapshot = verify(
            feeds,
            cutoff,
            db,
            start=start,
            events=events,
            models=models,
            model_events=0 if offline else (model_events or imported["articles"]),
            model_overviews=not offline,
            isolate_failures=not offline,
        )
        verified = stage / "verification.json"
        write_atomic(verified, canonical_json(snapshot))
        publication = build(verified, feeds, categories, out / "event-overviews.sqlite3")
        if events:
            events.replace(run_dir / "events.jsonl")
        verified.replace(run_dir / "verification.json")
        report = {
            "date": day.isoformat(),
            "lookback_days": lookback,
            "source_import": imported,
            "mode": "offline" if offline else ("ollama" if providers.local() else "openai"),
            "model_event_budget": 0 if offline else (model_events or imported["articles"]),
            "classification": classification,
            "import_classify_export_seconds": round(import_seconds, 3),
            "total_seconds": round(perf_counter() - started, 3),
            "grouping": grouping,
            "verification": snapshot["summary"],
            "publication": publication,
        }
        write_atomic(run_dir / "report.json", canonical_json(report))
        return report


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", type=date.fromisoformat, required=True)
    p.add_argument("--lookback-days", type=int, default=7)
    p.add_argument("--input-dir", type=Path, default=Path("liquid-briefing-data"))
    p.add_argument("--output-dir", type=Path, default=Path("output"))
    p.add_argument("--embedding-dir", type=Path)
    p.add_argument("--model-events", type=int)
    p.add_argument("--previous", type=Path, help="Earlier grouped events for stable IDs")
    p.add_argument("--offline", action="store_true", help="Use exact-copy grouping and official-figure rules")
    args = p.parse_args()
    try:
        print(
            json.dumps(
                prepare(
                    args.input_dir,
                    args.output_dir,
                    args.date,
                    args.lookback_days,
                    offline=args.offline,
                    embedding_dir=args.embedding_dir,
                    model_events=args.model_events,
                    previous=args.previous,
                ),
                indent=2,
            )
        )
    except (OSError, ValueError, sqlite3.Error, ModelError) as exc:
        p.exit(1, f"Daily preparation failed: {exc}\n")


if __name__ == "__main__":
    main()
