#!/usr/bin/env python3
"""Convert a Markdown document to speech using the ElevenLabs Text to Speech API."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_CHUNK_SIZE = 4500
API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
ENV_FILE = Path(__file__).resolve().with_name(".env")
NEWS_SAMPLE_RATE = 24000


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding existing environment values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def markdown_to_text(markdown: str) -> str:
    """Remove common Markdown syntax while keeping its readable text and link labels."""
    text = markdown.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    # YAML front matter is metadata, not narration.
    text = re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", "", text, count=1, flags=re.DOTALL)
    # Code and math blocks are usually not useful when read aloud.
    text = re.sub(r"```[^\n]*\n.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"~~~[^\n]*\n.*?~~~", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)

    # Keep image alt text and link labels, but do not speak raw URLs.
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"^\s*\[[^\]]+\]:\s+\S+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<((?:https?://|mailto:)[^>]+)>", "", text)

    # Strip HTML tags but keep their text; decode entities such as &amp;.
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)

    # Remove heading, quote, and list markers. Keep checkbox labels.
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>+\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-+*]\s+\[[ xX]\]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-+*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*(?:[-*_]\s*){3,}$", "", text, flags=re.MULTILINE)
    # A table's pipe separators are visual formatting; the cell text is useful.
    text = re.sub(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", "", text, flags=re.MULTILINE)
    text = text.replace("|", ", ")

    # Keep inline-code contents; remove Markdown emphasis and footnote markers.
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    text = re.sub(r"(?<!\\)(?:\*\*|__)(.+?)(?:\*\*|__)", r"\1", text)
    text = re.sub(r"(?<!\\)(?:\*|_)([^\n]+?)(?:\*|_)", r"\1", text)
    text = text.replace("\\*", "*").replace("\\_", "_")

    # Avoid reading leftover bare web addresses aloud.
    text = re.sub(r"https?://\S+", "", text)
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def split_long_text(text: str, max_chars: int) -> list[str]:
    """Split at paragraph/sentence/word boundaries without dropping any text."""
    if max_chars < 100:
        raise ValueError("--chunk-size must be at least 100 characters")
    chunks: list[str] = []
    current = ""

    def add_piece(piece: str) -> None:
        nonlocal current
        piece = piece.strip()
        if not piece:
            return
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            return
        if current:
            chunks.append(current)
            current = ""
        if len(piece) <= max_chars:
            current = piece
            return
        # Handle unusually long paragraphs by splitting on sentence boundaries,
        # then at whitespace as a final fallback.
        sentences = re.split(r"(?<=[.!?])\s+", piece)
        for sentence in sentences:
            if len(sentence) <= max_chars:
                candidate = f"{current} {sentence}".strip() if current else sentence
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    if current:
                        chunks.append(current)
                    current = sentence
                continue
            words = sentence.split()
            for word in words:
                if len(word) > max_chars:
                    if current:
                        chunks.append(current)
                    parts = [word[i:i + max_chars] for i in range(0, len(word), max_chars)]
                    chunks.extend(parts[:-1])
                    current = parts[-1]
                    continue
                candidate = f"{current} {word}".strip() if current else word
                if len(candidate) > max_chars:
                    if current:
                        chunks.append(current)
                    current = word
                else:
                    current = candidate

    for paragraph in re.split(r"\n\s*\n", text):
        add_piece(paragraph)
    if current:
        chunks.append(current)
    return chunks


def synthesize_chunk(
    text: str,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    timeout: float,
    retries: int,
    telemetry: dict | None = None,
) -> tuple[bytes, str | None]:
    url = f"{API_BASE}/{urllib.parse.quote(voice_id, safe='')}?{urllib.parse.urlencode({'output_format': output_format})}"
    body = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    for attempt in range(retries + 1):
        if telemetry is not None:
            telemetry["retries"] = attempt
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                audio = response.read()
                request_id = response.headers.get("request-id") or response.headers.get("xi-request-id")
                if telemetry is not None:
                    billed = response.headers.get("character-cost")
                    telemetry["provider_character_cost"] = int(billed) if billed and billed.isdecimal() else None
                if not audio:
                    raise RuntimeError("ElevenLabs returned an empty audio response")
                return audio, request_id
        except urllib.error.HTTPError as exc:
            details = exc.read(1000).decode("utf-8", errors="replace").strip()
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = min(15.0, max(0.0, float(retry_after))) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(delay)
                continue
            suffix = f": {details}" if details else ""
            raise RuntimeError(f"ElevenLabs API returned HTTP {exc.code}{suffix}") from None
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Could not reach ElevenLabs: {exc.reason}") from None
    raise RuntimeError("Speech generation failed after retries")


def generate_news_audio(directory: Path, expected_script: str | None = None) -> Path:
    """Render the saved briefing with the configured ElevenLabs voice."""
    load_dotenv(ENV_FILE)
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if not voice_id or voice_id == "your_voice_id_here":
        raise ValueError("Set ELEVENLABS_VOICE_ID in .env.")
    model_id = os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID

    source = directory / "script.md"
    raw = source.read_bytes()
    script = raw.decode("utf-8-sig")
    if expected_script is not None and script.splitlines() != expected_script.splitlines():
        raise ValueError("The saved script has changed. Generate your briefing again.")
    narration = markdown_to_text(script)
    if not narration:
        raise ValueError("script.md must contain text to narrate.")

    output = directory / "news.wav"
    sidecar = output.with_suffix(".manifest.json")
    metadata = {
        "source_file": str(source.resolve()),
        "script_sha256": hashlib.sha256(raw).hexdigest(),
        "narration_sha256": hashlib.sha256(narration.encode("utf-8")).hexdigest(),
        "voice_id": voice_id,
        "model": model_id,
        "sample_rate": NEWS_SAMPLE_RATE,
        "spoken_characters": len(narration),
    }
    if sidecar.is_file() and output.is_file():
        try:
            saved = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            saved = None
        if isinstance(saved, dict) and all(saved.get(key) == value for key, value in metadata.items()):
            if saved.get("audio_sha256") == hashlib.sha256(output.read_bytes()).hexdigest():
                return output

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        raise ValueError("Set ELEVENLABS_API_KEY in .env.")
    chunks = split_long_text(narration, DEFAULT_CHUNK_SIZE)
    request_ids = []
    with tempfile.TemporaryDirectory(dir=directory) as temp:
        staged = Path(temp) / output.name
        with wave.open(str(staged), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(NEWS_SAMPLE_RATE)
            for chunk in chunks:
                pcm, request_id = synthesize_chunk(
                    chunk, api_key, voice_id, model_id, f"pcm_{NEWS_SAMPLE_RATE}", 240, 1,
                )
                if len(pcm) % 2 or pcm.startswith((b"ID3", b"RIFF")):
                    raise RuntimeError("Unexpected audio format from ElevenLabs.")
                audio.writeframes(pcm)
                request_ids.append(request_id)
            duration = round(audio.getnframes() / NEWS_SAMPLE_RATE, 2)

        metadata.update({
            "duration_seconds": duration,
            "audio_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
            "request_ids": request_ids,
        })
        info = Path(temp) / sidecar.name
        info.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        staged.replace(output)
        info.replace(sidecar)
    return output


def main() -> int:
    load_dotenv(ENV_FILE)

    parser = argparse.ArgumentParser(
        description="Turn a Markdown file into an MP3 using ElevenLabs Text to Speech."
    )
    parser.add_argument("input", type=Path, help="Markdown file to narrate")
    parser.add_argument("-o", "--output", type=Path, help="Output MP3 (default: input name with .mp3)")
    parser.add_argument("--voice-id", default=os.getenv("ELEVENLABS_VOICE_ID"), help="ElevenLabs voice ID")
    parser.add_argument("--model-id", default=os.getenv("ELEVENLABS_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Characters per API request (default: 4500)")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries for temporary network/API errors")
    parser.add_argument("--keep-segments", action="store_true", help="Save separate MP3s instead of joining them")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.is_file():
        parser.error(f"input file does not exist: {source}")
    if args.chunk_size < 100:
        parser.error("--chunk-size must be at least 100 characters")
    if args.timeout <= 0 or args.retries < 0:
        parser.error("--timeout must be positive and --retries cannot be negative")

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        parser.error("set ELEVENLABS_API_KEY in the environment or in a .env file")
    if not args.voice_id or args.voice_id == "your_voice_id_here":
        parser.error("set ELEVENLABS_VOICE_ID or pass --voice-id")

    output = (args.output or source.with_suffix(".mp3")).expanduser().resolve()
    if output.suffix.lower() != ".mp3":
        parser.error("output filename must end in .mp3")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        original = source.read_bytes()
        markdown = original.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        parser.error(f"could not read UTF-8 Markdown input: {exc}")
    spoken_text = markdown_to_text(markdown)
    if not spoken_text:
        parser.error("the Markdown file has no readable text after formatting is removed")
    chunks = split_long_text(spoken_text, args.chunk_size)
    ffmpeg = shutil.which("ffmpeg")
    if len(chunks) > 1 and not args.keep_segments and not ffmpeg:
        parser.error("this document needs multiple audio segments; install FFmpeg or use --keep-segments")

    source_hash = hashlib.sha256(original).hexdigest()
    text_hash = hashlib.sha256(spoken_text.encode("utf-8")).hexdigest()
    generated_at = datetime.now(timezone.utc).isoformat()
    request_ids: list[str | None] = []
    manifest: dict[str, Any] = {
        "source_file": str(source),
        "source_sha256": source_hash,
        "spoken_text_sha256": text_hash,
        "generated_at_utc": generated_at,
        "provider": "ElevenLabs",
        "voice_id": args.voice_id,
        "model_id": args.model_id,
        "output_format": args.output_format,
        "spoken_characters": len(spoken_text),
        "chunk_count": len(chunks),
        "request_ids": request_ids,
    }

    try:
        if len(chunks) == 1 or args.keep_segments:
            if args.keep_segments and len(chunks) > 1:
                outputs = [output.with_name(f"{output.stem}.part-{i:03d}.mp3") for i in range(1, len(chunks) + 1)]
            else:
                outputs = [output]
            for index, (chunk, chunk_output) in enumerate(zip(chunks, outputs), start=1):
                print(f"Generating audio segment {index}/{len(chunks)}...")
                audio, request_id = synthesize_chunk(
                    chunk, api_key, args.voice_id, args.model_id, args.output_format,
                    args.timeout, args.retries,
                )
                chunk_output.write_bytes(audio)
                request_ids.append(request_id)
            manifest["audio_files"] = [str(path) for path in outputs]
            manifest_path = output.with_suffix(".manifest.json")
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Saved {len(outputs)} audio file(s). Metadata: {manifest_path}")
            if args.keep_segments and len(chunks) > 1:
                print("Play the numbered part files in order.")
            return 0

        with tempfile.TemporaryDirectory(prefix="md-to-speech-") as temp_name:
            temp_dir = Path(temp_name)
            concat_lines: list[str] = []
            for index, chunk in enumerate(chunks, start=1):
                print(f"Generating audio segment {index}/{len(chunks)}...")
                audio, request_id = synthesize_chunk(
                    chunk, api_key, args.voice_id, args.model_id, args.output_format,
                    args.timeout, args.retries,
                )
                request_ids.append(request_id)
                segment_name = f"part-{index:03d}.mp3"
                (temp_dir / segment_name).write_bytes(audio)
                concat_lines.append(f"file '{segment_name}'")
            concat_file = temp_dir / "segments.txt"
            concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
            merged_temp = output.with_name(f"{output.stem}.tmp.mp3")
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(merged_temp)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                merged_temp.unlink(missing_ok=True)
                detail = result.stderr.strip()[-1200:]
                raise RuntimeError(f"FFmpeg could not join audio segments: {detail}")
            os.replace(merged_temp, output)
            manifest["audio_files"] = [str(output)]
            manifest_path = output.with_suffix(".manifest.json")
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Saved {output}\nMetadata: {manifest_path}")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
