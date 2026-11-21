"""Create reusable MP3 segments from an immutable, validated daily edition."""

from datetime import datetime, timezone
import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from time import perf_counter

from md_to_speech import DEFAULT_MODEL_ID, ENV_FILE, load_dotenv, synthesize_chunk
from generate_script import validate_daily
from .official_releases import digest
from .verify import write_atomic


def render(directory, draft, briefing):
    validate_daily(draft, briefing)
    load_dotenv(ENV_FILE)
    voice, model = os.getenv("ELEVENLABS_VOICE_ID"), os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID
    if not voice or voice == "your_voice_id_here":
        raise ValueError("Configure an ElevenLabs voice to enable narration.")
    cache = directory / "audio"
    cache.mkdir(parents=True, exist_ok=True)
    segments, seconds = [], 0
    for block in briefing["spoken_segments"]:
        settings = {"voice": voice, "model": model, "format": "mp3_44100_128"}
        key = digest([block["text"], settings])
        mp3, meta = cache / (key + ".mp3"), cache / (key + ".json")
        metadata = None
        if meta.exists() and mp3.exists():
            try:
                stored = json.loads(meta.read_text())
                if stored.get("sha256") == sha256(mp3.read_bytes()).hexdigest():
                    metadata = stored
            except (ValueError, AttributeError):
                pass
        reused = metadata is not None
        if not metadata:
            api_key = os.getenv("ELEVENLABS_API_KEY")
            if not api_key or api_key == "your_api_key_here":
                raise ValueError("Configure ElevenLabs credentials to generate audio.")
            start = perf_counter()
            usage = {}
            audio, request_id = synthesize_chunk(
                block["text"], api_key, voice, model, settings["format"], 60, 2, telemetry=usage
            )
            with NamedTemporaryFile(dir=cache, suffix=".mp3", delete=False) as f:
                temporary = Path(f.name)
                f.write(audio)
            try:
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "csv=p=0",
                        str(temporary),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                duration = float(probe.stdout)
                if not 0 < duration < 3600:
                    raise ValueError("Invalid audio segment duration.")
                metadata = {
                    **settings,
                    **usage,
                    "sha256": sha256(audio).hexdigest(),
                    "duration": duration,
                    "characters": len(block["text"]),
                    "request_id": request_id,
                    "created": datetime.now(timezone.utc).isoformat(),
                    "latency_seconds": perf_counter() - start,
                }
                temporary.replace(mp3)
                write_atomic(meta, json.dumps(metadata))
            finally:
                temporary.unlink(missing_ok=True)
        segments.append(
            {
                **block,
                **metadata,
                "cache_hit": reused,
                "file": key + ".mp3",
                "start_seconds": seconds,
                "url": "/api/audio/" + briefing["edition"] + "/" + key + ".mp3",
            }
        )
        seconds += metadata["duration"]
    manifest = {"edition": briefing["edition"], "duration": seconds, "segments": segments, "status": "ready"}
    write_atomic(directory / briefing["edition"] / "audio.json", json.dumps(manifest, ensure_ascii=False))
    return manifest
