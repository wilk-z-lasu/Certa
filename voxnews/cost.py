"""Separate shared preparation costs from per-listener writing and optional speech."""

import argparse
import json
import math
from pathlib import Path


def inference(usage, mode, prices):
    inputs = usage.get("input_tokens", 0)
    cached = usage.get("cached_tokens", usage.get("cached_input_tokens", 0))
    outputs = usage.get("output_tokens", 0)
    calls = usage.get("calls", usage.get("luna_calls", 0))
    rates = prices.get(usage.get("model"))
    cost = None
    if calls == 0 or mode in {"offline", "ollama"}:
        cost = 0
    elif rates and not usage.get("unmetered_calls") and (inputs or outputs):
        cost = (
            (inputs - cached) * rates["input"] + cached * rates["cached"] + outputs * rates["output"]
        ) / 1_000_000
    return {
        "model": usage.get("model"),
        "calls": calls,
        "cache_hits": usage.get("cache_hits", 0),
        "retries": usage.get("retries", 0) + usage.get("batch_retries", 0),
        "input_tokens": inputs,
        "cached_input_tokens": cached,
        "output_tokens": outputs,
        "seconds": usage.get("seconds"),
        "estimated_provider_usd": cost,
    }


def total(values):
    return None if any(value is None for value in values) else sum(values)


def report(run, briefings=(), prices=None, rates_date=None, audio=(), speech_rate=None):
    prices = prices or {}
    for name, rates in prices.items():
        if set(rates) != {"cached", "input", "output"} or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rates.values()
        ):
            raise ValueError(f"Invalid per-million rates for {name}")
    if speech_rate is not None and (not math.isfinite(speech_rate) or speech_rate < 0):
        raise ValueError("Invalid speech rate per thousand billable characters")
    mode = run["mode"]
    stages = {
        "classification": inference(run.get("classification", {}), mode, prices),
        "grouping": inference(run["grouping"] or {}, mode, prices),
    }
    if (run.get("grouping") or {}).get("embedding_usage"):
        embedding = run["grouping"]["embedding_usage"]
        stages["embedding"] = inference(embedding, "offline" if embedding.get("provider") == "local" else mode, prices)
    for name, usage in run["verification"]["model_usage"].items():
        stages[name] = inference(usage, mode, prices)
    writers = []
    for b in briefings:
        usage = b.get("usage") or {}
        hosted = b.get("provider") or ("offline" if not b.get("model") else "unknown")
        writers.append(
            inference(
                {
                    **usage,
                    "model": b.get("model"),
                    "calls": int(bool(b.get("model"))),
                    "seconds": b.get("elapsed_seconds"),
                },
                hosted,
                prices,
            )
        )
    speech = []
    for manifest in audio:
        parts = manifest["segments"]
        misses = [s for s in parts if not s.get("cache_hit")]
        credits = [s.get("provider_character_cost") for s in misses]
        billable = total(credits)
        amount = (
            billable * speech_rate / 1000
            if billable is not None and speech_rate is not None
            else (0 if not misses else None)
        )
        speech.append(
            {
                "duration_seconds": manifest["duration"],
                "cache_hits": len(parts) - len(misses),
                "new_segments": len(misses),
                "new_text_characters": sum(s["characters"] for s in misses),
                "provider_character_cost": billable,
                "estimated_provider_usd": amount,
            }
        )
    shared = total([v["estimated_provider_usd"] for v in stages.values()])
    listeners = total([v["estimated_provider_usd"] for v in writers + speech])
    return {
        "date": run["date"],
        "mode": mode,
        "rates_as_of": rates_date,
        "imported_stories": run["source_import"]["articles"],
        "window_articles": run["verification"]["articles_in_window"],
        "events": run["verification"]["events"],
        "model_event_budget": run.get("model_event_budget"),
        "model_events_reviewed": run["verification"]["model_events_processed"],
        "event_failures": run["verification"].get("failed_events", 0),
        "preparation_seconds": run.get("total_seconds"),
        "shared": stages,
        "writing": writers,
        "speech": speech,
        "shared_provider_usd": shared,
        "listener_provider_usd": listeners,
        "projection_usd": {
            "ten_times_new_articles_same_listeners": total(
                [None if shared is None else 10 * shared, listeners]
            ),
            "same_articles_ten_times_listeners": total(
                [shared, None if listeners is None else 10 * listeners]
            ),
        },
        "assumptions": "Same model routing, revisions per article, cache mix and listener mix. Local model API fees are zero. "
        "Hardware, electricity and fixed subscriptions are excluded. Speech is included only for supplied manifests.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--briefing", action="append", type=Path, default=[])
    p.add_argument("--audio-manifest", action="append", type=Path, default=[])
    p.add_argument("--prices", type=Path)
    p.add_argument("--rates-date")
    p.add_argument("--speech-usd-per-1000-credits", type=float)
    args = p.parse_args()
    try:
        if (args.prices or args.speech_usd_per_1000_credits is not None) and not args.rates_date:
            raise ValueError("Provide the pricing date with --rates-date")
        bs = [json.loads(path.read_bytes()) for path in args.briefing]
        print(
            json.dumps(
                report(
                    json.loads(args.run.read_bytes()),
                    [b.get("briefing", b) for b in bs],
                    json.loads(args.prices.read_bytes()) if args.prices else {},
                    args.rates_date,
                    [json.loads(path.read_bytes()) for path in args.audio_manifest],
                    args.speech_usd_per_1000_credits,
                ),
                indent=2,
            )
        )
    except (ValueError, KeyError, OSError) as exc:
        p.exit(1, f"Cost report failed: {exc}\n")


if __name__ == "__main__":
    main()
