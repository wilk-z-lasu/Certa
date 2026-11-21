"""Separate shared preparation costs from per-listener writing and optional speech."""

import argparse
import json
import math
from pathlib import Path
import sqlite3

from .usage import history


def inference(usage, mode, prices):
    inputs = usage.get("input_tokens") or 0
    details = usage.get("input_tokens_details") or {}
    cached = usage.get("cached_tokens", usage.get("cached_input_tokens", details.get("cached_tokens", 0))) or 0
    outputs = usage.get("output_tokens") or 0
    calls = usage.get("calls", usage.get("luna_calls", 0))
    rates = prices.get(usage.get("model"))
    cost = None
    if calls == 0 or mode in {"offline", "ollama"}:
        cost = 0
    elif rates and not usage.get("unmetered_calls") and (inputs or outputs) and 0 <= cached <= inputs:
        cost = (
            (inputs - cached) * rates["input"] + cached * rates["cached"] + outputs * rates["output"]
        ) / 1_000_000
    return {
        "model": usage.get("model"),
        "calls": calls,
        "unmetered_calls": usage.get("unmetered_calls", 0),
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


def report(run, briefings=(), prices=None, rates_date=None, audio=(), speech_rate=None, machine_rate=None):
    prices = prices or {}
    for name, rates in prices.items():
        if set(rates) != {"cached", "input", "output"} or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rates.values()
        ):
            raise ValueError(f"Invalid per-million rates for {name}")
    if speech_rate is not None and (not math.isfinite(speech_rate) or speech_rate < 0):
        raise ValueError("Invalid speech rate per thousand billable characters")
    if machine_rate is not None and (not math.isfinite(machine_rate) or machine_rate < 0):
        raise ValueError("Invalid machine rate per hour")
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
                    "unmetered_calls": int(bool(b.get("model")) and
                                           not {"input_tokens", "output_tokens"} <= usage.keys()),
                },
                hosted,
                prices,
            )
        )
    speech = []
    for manifest in audio:
        parts = manifest["segments"]
        misses = [s for s in parts if not s.get("cache_hit")]
        hosted = [s for s in misses if s.get("provider", "elevenlabs") == "elevenlabs"]
        credits = [s.get("provider_character_cost") for s in hosted]
        billable = total(credits)
        amount = (
            billable * speech_rate / 1000
            if billable is not None and speech_rate is not None
            else (0 if not hosted else None)
        )
        speech.append(
            {
                "duration_seconds": manifest["duration"],
                "providers": sorted({s.get("provider", "elevenlabs") for s in parts}),
                "generation_seconds": total([s.get("latency_seconds") for s in misses]),
                "cache_hits": len(parts) - len(misses),
                "new_segments": len(misses),
                "new_text_characters": sum(s["characters"] for s in misses),
                "provider_character_cost": billable,
                "estimated_provider_usd": amount,
            }
        )
    shared = total([v["estimated_provider_usd"] for v in stages.values()])
    listeners = total([v["estimated_provider_usd"] for v in writers + speech])
    result = {
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
        "total_provider_usd": total([shared, listeners]),
        "projection_usd": {
            "ten_times_new_articles_same_listeners": total(
                [None if shared is None else 10 * shared, listeners]
            ),
            "same_articles_ten_times_listeners": total(
                [shared, None if listeners is None else 10 * listeners]
            ),
        },
        "assumptions": "Same model routing, coverage, revisions per article, cache mix and listener mix. Local model API fees are zero. "
        "Provider totals exclude hardware, electricity and fixed subscriptions. Speech is included only for supplied manifests.",
    }
    if machine_rate is not None:
        shared_seconds = run.get("total_seconds")
        delivery_seconds = total([b.get("retrieval_seconds", 0) for b in briefings] +
                                 [w["seconds"] for w in writers] + [s["generation_seconds"] for s in speech])
        def allocated(seconds):
            return None if seconds is None else seconds * machine_rate / 3600
        prep = total([shared, allocated(shared_seconds)])
        delivery = total([listeners, allocated(delivery_seconds)])
        result["machine_scenario"] = {
            "usd_per_hour_assumption": machine_rate, "shared_seconds": shared_seconds,
            "listener_seconds": delivery_seconds, "shared_usd": prep, "listener_usd": delivery,
            "total_usd": total([prep, delivery]),
            "ten_times_new_articles_same_listeners_usd": total([None if prep is None else 10 * prep, delivery]),
            "same_articles_ten_times_listeners_usd": total([prep, None if delivery is None else 10 * delivery]),
            "assumption": "Allocate serial preparation, retrieval, writing and speech time at the supplied hourly rate. "
                          "The 10x scenarios assume linear wall time and unchanged routing. They are projections.",
        }
    return result


def receipt_report(path, prices, *, scope="shared"):
    attempts, rows = history(path)
    stages = [{"stage": row["stage"], **inference(row, "openai", prices)} for row in rows]
    return {"attempts": attempts, "hosted_requests": stages,
            "known_since_ledger_created": True,
            f"estimated_{scope}_provider_usd": total([s["estimated_provider_usd"] for s in stages])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--briefing", action="append", type=Path, default=[])
    p.add_argument("--audio-manifest", action="append", type=Path, default=[])
    p.add_argument("--prices", type=Path)
    p.add_argument("--rates-date")
    p.add_argument("--speech-usd-per-1000-credits", type=float)
    p.add_argument("--machine-usd-per-hour", type=float, help="Illustrative machine allocation for 1x and 10x scenarios")
    p.add_argument("--usage-ledger", type=Path, help="Cumulative hosted preparation receipts, including interrupted attempts")
    p.add_argument("--writer-ledger", type=Path,
                   help="Cumulative hosted writing receipts, including interrupted attempts")
    args = p.parse_args()
    try:
        if (args.prices or args.speech_usd_per_1000_credits is not None) and not args.rates_date:
            raise ValueError("Provide the pricing date with --rates-date")
        bs = [json.loads(path.read_bytes()) for path in args.briefing]
        prices = json.loads(args.prices.read_bytes()) if args.prices else {}
        result = report(json.loads(args.run.read_bytes()), [b.get("briefing", b) for b in bs], prices,
                        args.rates_date, [json.loads(path.read_bytes()) for path in args.audio_manifest],
                        args.speech_usd_per_1000_credits, args.machine_usd_per_hour)
        ledger = args.usage_ledger or args.run.with_name("usage.sqlite3")
        if args.usage_ledger or ledger.is_file():
            result["cumulative_preparation"] = receipt_report(ledger, prices)
        if args.writer_ledger:
            result["cumulative_writing"] = receipt_report(args.writer_ledger, prices, scope="writer")
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        p.exit(1, f"Cost report failed: {exc}\n")


if __name__ == "__main__":
    main()
