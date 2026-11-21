"""Replay normal daily narration over HTTP and check the recorded claim sources."""

import argparse
from contextlib import closing
from decimal import Decimal
from hashlib import sha256
from http.cookiejar import CookieJar
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from build_preai import database_path
from .group_events import timestamp
from .overview_reader import Passages, connect, get_event
from .verify import write_atomic

OFFICIAL = Path(__file__).with_name("official") / "observations.jsonl"


def audit(base, output, database, day=None):
    client = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        with client.open(Request(base + path, data, {"Content-Type": "application/json"}), timeout=180) as res:
            payload = res.read()
            return json.loads(payload) if res.headers.get_content_type() == "application/json" else payload

    releases = {obj["url"]: obj for obj in map(json.loads, OFFICIAL.read_text(encoding="utf-8").splitlines())}
    wild = get("/api/people", {"name": "Wildcard Speaker Check", "settings": {
        "topics": ["crypto", "technology_ai"], "language": "en",
        "minutes": 1, "depth": "headlines", "weights": {"crypto": 2},
    }})
    for name, persona in (("macro", "macro"), ("technology", "technology"), ("wildcard", wild["id"])):
        query = "?" + urlencode({"persona": persona})
        profile = get("/api/profile" + query)
        request = {"date": day or profile["dates"][0], "version": profile["profile"]["version"]}
        briefing = get("/api/briefing" + query, request)
        if get("/api/briefing" + query, request) != briefing:
            raise ValueError("Saved edition changed on reopen")
        payload = {"edition": briefing["edition"]}
        manifest = get("/api/narration" + query, payload)
        if manifest["provider"] not in {"windows-speech", "espeak-ng"}:
            raise ValueError("Audit requires an offline narration provider")
        reused = get("/api/narration" + query, payload)
        if not all(block["cache_hit"] for block in reused["segments"]):
            raise ValueError("Narration segments were not served from cache on replay")
        checks = []
        folder = output / name
        folder.mkdir(parents=True, exist_ok=True)
        with closing(connect(database)) as db:
            passages = Passages(db)
            for index, block in enumerate(manifest["segments"]):
                audio = get(block["url"])
                if sha256(audio).hexdigest() != block["sha256"]:
                    raise ValueError(f"Audio hash failed for {name}, segment {index}")
                (folder / f"{index:02d}.mp3").write_bytes(audio)
                if not block.get("claim_id"):
                    continue
                claim = block["claim_id"]
                path = "/evidence/" + block["event_id"] + "/" + block["revision"] + "?" + urlencode({"claim": claim})
                if f'id="c{claim}" open'.encode() not in get(path):
                    raise ValueError(f"Claim evidence link failed for {claim}")
                event = get_event(db, block["event_id"], block["revision"])
                checked = []
                for ref in block["sources"]:
                    if "span_hash" in ref:
                        passages.text(ref, event["sources"])
                        checked.append({"url": ref["url"], "field": ref["field"], "start": ref["start"],
                                        "end": ref["end"], "span_hash": ref["span_hash"]})
                    if ref.get("role") == "official_at_cutoff" and ref["url"] in releases:
                        release = releases[ref["url"]]
                        if (timestamp(release["available_at"]) >= timestamp(briefing["cutoff_exclusive"]) or not any(
                                Decimal(cell[4]) == Decimal(ref["value"]) and cell[5] == ref["locator"]
                                for cell in release["cells"]
                        )):
                            raise ValueError(f"Official row differs for {claim}")
                        checked.append({"url": ref["url"], "value": ref["value"], "locator": ref["locator"]})
                checks.append({"claim": claim, "text": block["text"], "start_seconds": block["start_seconds"],
                               "end_seconds": block["end_seconds"], "evidence_url": path + "#c" + claim,
                               "checked_sources": checked})
        concat = folder / "segments.ffconcat"
        write_atomic(concat, "".join(f"file '{index:02d}.mp3'\n" for index in range(len(manifest["segments"]))))
        wav = folder / "briefing.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "1",
                        "-i", str(concat), str(wav)], check=True, timeout=60)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(wav)], check=True, timeout=30,
                               capture_output=True, text=True)
        duration = float(probe.stdout)
        if abs(duration - manifest["duration"]) > 0.1:
            raise ValueError(f"Recorded playback duration differs from the manifest for {name}")
        words = sum(len(block["text"].split()) for block in manifest["segments"])
        quality = {"wav_duration": duration, "spoken_words_per_minute": round(60 * words / duration),
                   "segments_render_seconds": sum(b["latency_seconds"] for b in manifest["segments"] if not b["cache_hit"])}
        for key, value in (("briefing", briefing), ("manifest", manifest), ("claim-audit", checks), ("quality", quality)):
            write_atomic(folder / (key + ".json"), json.dumps(value, indent=2, ensure_ascii=False))
        print(f'{name} · {briefing["date"]} · {manifest["provider"]} · '
              f'{len(checks)} claims · {duration:.2f} s · {quality["spoken_words_per_minute"]} words/min · {folder}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8430")
    parser.add_argument("--database", type=Path, default=database_path())
    parser.add_argument("--output", type=Path, default=Path("output/audio-audit"))
    parser.add_argument("--date", help="Published briefing date; defaults to the latest")
    args = parser.parse_args()
    audit(args.url.rstrip("/"), args.output, args.database, args.date)


if __name__ == "__main__":
    main()
