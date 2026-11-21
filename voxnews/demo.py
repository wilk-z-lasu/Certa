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
    providers.load_environment(cloud_demo=True)
    os.environ["VOXNEWS_PROVIDER"] = "openai"
    output = Path(output or ROOT / "output" / "cloud-demo").resolve()
    os.environ["VOXNEWS_OVERVIEW_DB"] = str(output / "event-overviews.sqlite3")
    return output


def status():
    from build_preai import database_path

    result = {"provider": "openai", "cloud_only": True, "key_configured": bool(providers.api_key()),
              "api_requests_paused": providers.requests_paused(),
              "models": {role: providers.model(role) for role in providers.HOSTED}, "ready": False}
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
    if not result["ready"]:
        result["message"] = "Restore the prepared cloud catalogue or run the cloud demo preparation on this machine."
    elif not result["key_configured"] or result["api_requests_paused"]:
        result["message"] = "Cached cloud news and evidence are available. New briefings require a configured key and enabled OpenAI requests."
    else:
        result["message"] = "The cloud demo is ready to generate briefings."
    return result


def main():
    from .daily import prepare
    from .luna import ModelError

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
