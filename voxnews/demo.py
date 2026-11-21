"""Prepare an isolated demo using cloud models at every inference stage."""

import argparse
from contextlib import closing
from datetime import date
import json
import os
from pathlib import Path
import sqlite3

from . import providers

ROOT = Path(__file__).resolve().parents[1]


def configure(output=None):
    os.environ["VOXNEWS_CLOUD_ONLY"] = "1"
    os.environ["VOXNEWS_PROVIDER"] = "openai"
    output = Path(output or ROOT / "output" / "cloud-demo").resolve()
    os.environ["VOXNEWS_OVERVIEW_DB"] = str(output / "event-overviews.sqlite3")
    return output


def listener_directory():
    from .listeners import storage

    target = ROOT / "user_data" / "cloud-demo"
    old = ROOT / "user_data" / "listeners.sqlite3"
    # Carry over user settings; generated local editions and feedback stay in their original archive.
    if not (target / "listeners.sqlite3").exists() and old.is_file():
        with closing(sqlite3.connect(old.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            rows = source.execute("SELECT listener,version,settings,reason,created FROM profile").fetchall()
        with storage(target) as db:
            db.executemany("INSERT OR IGNORE INTO profile VALUES(?,?,?,?,?)", rows)
    return target


def status():
    from build_preai import database_path

    result = {"provider": "openai", "cloud_only": True, "key_configured": bool(providers.api_key()),
              "api_requests_paused": providers.requests_paused(),
              "models": {role: providers.model(role) for role in providers.HOSTED}, "ready": False}
    if not result["key_configured"]:
        result["message"] = "The cloud demo needs an OpenAI API key. Local models and offline fallback are disabled."
        return result
    path = database_path()
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                metadata = json.loads(db.execute("SELECT metadata FROM build_info WHERE id=1").fetchone()[0])
            processing = metadata.get("processing", {})
            result["ready"] = (all(processing.get(k) == "openai" for k in
                                   ("provider", "embedding_provider", "grouping_provider"))
                               and metadata["report"]["draft_uses"].get("approved_wording", 0) > 0)
        except (sqlite3.Error, ValueError, TypeError):
            pass
    result["message"] = ("Cloud API requests are paused to preserve credits. Cached overviews and evidence remain available."
                         if result["ready"] and result["api_requests_paused"] else
                         "Cloud models only. Reporting dates identify publication, while each figure names its data period."
                         if result["ready"] else "Preparing the cloud-generated news catalogue. Local-model results are excluded.")
    return result


def main():
    from md_to_speech import load_dotenv
    from .daily import prepare
    from .luna import ModelError

    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--lookback-days", type=int, default=7)
    p.add_argument("--model-events", type=int, default=40)
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args()
    output = configure(args.output_dir)
    try:
        result = prepare(ROOT / "liquid-briefing-data", output, args.date, args.lookback_days,
                         model_events=args.model_events)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, sqlite3.Error, ModelError) as error:
        p.exit(1, f"Cloud demo preparation failed: {error}\n")


if __name__ == "__main__":
    main()
