"""Render user_data/script.md with a journalist selected from UserInfo.md."""
import argparse
import hashlib
import json
import os
import re
import tempfile
import wave
from pathlib import Path

from md_to_speech import load_dotenv, markdown_to_text, split_long_text, synthesize_chunk

ROOT = Path(__file__).resolve().parent
MODEL = "eleven_multilingual_v2"
RATE = 24000


def choose_voice(profile, roster):
    profile = profile.casefold()
    words = set(re.findall(r"\w+", profile))
    def requested(value, field):
        return bool(re.search(rf"\b(?:{field}|voice|narrator)\s*[:=]\s*{value}\b|"
                              rf"\b{value}\s+(?:accent|voice|narrator|journalist)\b", profile))

    ranked = []
    for voice in roster:
        accent = requested(voice["accent"].casefold(), "accent")
        gender = requested(voice["gender"], "voice gender|narrator gender")
        matches = sorted(words.intersection(voice["keywords"]))
        ranked.append(((int(accent), int(gender), len(matches)), voice, matches))
    _, voice, matches = max(ranked, key=lambda entry: entry[0])
    return voice, matches


def generate_news_audio(directory, expected_script=None):
    load_dotenv(ROOT / ".env")
    raw = (directory / "script.md").read_bytes()
    script = raw.decode("utf-8-sig")
    if expected_script is not None and script.splitlines() != expected_script.splitlines():
        raise ValueError("The saved script has changed. Generate your briefing again.")
    profile = (directory / "UserInfo.md").read_text(encoding="utf-8-sig").strip()
    narration = markdown_to_text(script)
    if not profile or not narration:
        raise ValueError("UserInfo.md and script.md must both contain text.")
    roster = json.loads((ROOT / "journalist_voices.json").read_text(encoding="utf-8"))
    voice, matches = choose_voice(profile, roster)
    if not voice.get("voice_id"):
        raise ValueError(f"Run design_journalists.py to provision {voice['name']}.")
    output = directory / "news.wav"
    sidecar = directory / "news.manifest.json"
    metadata = {"script_sha256": hashlib.sha256(raw).hexdigest(),
                "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
                "narration_sha256": hashlib.sha256(narration.encode()).hexdigest(),
                "journalist": voice["name"], "voice_id": voice["voice_id"], "accent": voice["accent"],
                "matched_keywords": matches, "model": MODEL, "sample_rate": RATE}
    if sidecar.exists() and output.exists():
        saved = json.loads(sidecar.read_text(encoding="utf-8"))
        if (all(saved.get(k) == v for k, v in metadata.items()) and
                saved.get("audio_sha256") == hashlib.sha256(output.read_bytes()).hexdigest()):
            return output
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise ValueError("Set ELEVENLABS_API_KEY in .env.")
    with tempfile.TemporaryDirectory(dir=directory) as temp:
        staged = Path(temp) / "news.wav"
        with wave.open(str(staged), "wb") as audio:
            audio.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            for chunk in split_long_text(narration, 8000):
                if len(chunk) > 8000:
                    raise ValueError("Script contains an excessively long unbroken word.")
                pcm, _ = synthesize_chunk(chunk, key, voice["voice_id"], MODEL, f"pcm_{RATE}", 240, 1)
                if len(pcm) % 2 or pcm.startswith((b"ID3", b"RIFF")):
                    raise ValueError("Unexpected audio format from ElevenLabs.")
                audio.writeframes(pcm)
        with wave.open(str(staged)) as audio:
            metadata["duration_seconds"] = round(audio.getnframes() / RATE, 2)
        metadata["audio_sha256"] = hashlib.sha256(staged.read_bytes()).hexdigest()
        info = Path(temp) / sidecar.name
        info.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        staged.replace(output)
        info.replace(sidecar)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-data", type=Path, default=ROOT / "user_data")
    try:
        print(generate_news_audio(parser.parse_args().user_data))
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
