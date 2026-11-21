"""Create reusable MP3 segments from an immutable, validated daily edition."""

from datetime import datetime, timezone
import json
from hashlib import sha256
import os
from pathlib import Path
import re
from shutil import which
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from md_to_speech import DEFAULT_MODEL_ID, synthesize_chunk
from generate_script import validate_daily
from . import providers
from .official_releases import digest
from .verify import write_atomic


WINDOWS_SPEECH = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = $speech.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $env:CERTA_SPEECH_LANGUAGE
    } | Sort-Object { $_.VoiceInfo.Id }
    $voice = $voices | Select-Object -First 1
    if ($null -eq $voice) { exit 3 }
    if (!$env:CERTA_SPEECH_TEXT) {
        [Console]::WriteLine($voice.VoiceInfo.Id)
        exit
    }
    if ($voice.VoiceInfo.Id -ne $env:CERTA_SPEECH_VOICE) { exit 3 }
    $speech.SelectVoice($voice.VoiceInfo.Name)
    $speech.Rate = [int]$env:CERTA_SPEECH_RATE
    $speech.SetOutputToWaveFile($env:CERTA_SPEECH_WAV)
    $speech.Speak([IO.File]::ReadAllText($env:CERTA_SPEECH_TEXT))
} finally {
    $speech.Dispose()
}
"""
PORTABLE_ESPEAK = providers.ROOT / "output" / "tools" / "espeak-ng" / "payload" / "eSpeak NG"


def espeak_command():
    exe = PORTABLE_ESPEAK / "espeak-ng.exe"
    if sys.platform == "win32" and exe.is_file() and (PORTABLE_ESPEAK / "espeak-ng-data").is_dir():
        return [str(exe), f"--path={PORTABLE_ESPEAK}"]
    executable = which("espeak-ng")
    return [executable] if executable else []


def windows_speech(language, **paths):
    env = {**os.environ, "CERTA_SPEECH_LANGUAGE": language}
    env.update({"CERTA_SPEECH_" + key.upper(): str(value) for key, value in paths.items()})
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SPEECH],
        env=env, capture_output=True, text=True, timeout=60,
    )


def narration_mode():
    mode = providers.setting("CERTA_NARRATION", "auto").lower()
    if mode not in {"auto", "offline", "elevenlabs"}:
        raise ValueError("CERTA_NARRATION must be auto, offline, or elevenlabs.")
    return "elevenlabs" if providers.cloud_only() else mode


def speech_settings(language):
    mode = narration_mode()
    voice = (providers.setting("ELEVENLABS_VOICE_ID") or "").strip()
    if mode == "elevenlabs" or (
        mode == "auto" and voice not in {"", "your_voice_id_here"}
        and elevenlabs_key() and not providers.paid_requests_paused()
    ):
        if voice in {"", "your_voice_id_here"}:
            raise ValueError("Configure an ElevenLabs voice to enable cloud narration.")
        model = providers.setting("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID
        if language != "en" and model.startswith("eleven_monolingual"):
            raise ValueError("This briefing language requires a multilingual ElevenLabs model.")
        return {"provider": "elevenlabs", "voice": voice, "model": model, "language": language,
                "format": "mp3_44100_128"}

    if sys.platform == "win32" and which("powershell.exe"):
        result = windows_speech(language)
        if result.returncode == 0 and result.stdout.strip():
            return {"provider": "windows-speech", "voice": result.stdout.strip(),
                    "model": "System.Speech", "language": language, "rate": 0, "format": "mp3_44100_128",
                    "end_pause_seconds": 0.3}
    command = espeak_command()
    if command:
        voices = subprocess.run([*command, f"--voices={language}"], check=True, capture_output=True,
                                text=True, timeout=15).stdout.splitlines()
        if any(line.split()[1:2] == [language] for line in voices):
            version = sha256(Path(command[0]).read_bytes()).hexdigest()
            return {"provider": "espeak-ng", "voice": language, "model": version, "language": language,
                    "rate": 155, "format": "mp3_44100_128"}
    raise ValueError(f"No offline speech voice is installed for {language}. Install a Windows speech voice "
                     "for this language or eSpeak NG to generate audio.")


def elevenlabs_key():
    token = (providers.setting("ELEVENLABS_API_KEY") or "").strip()
    return token if token != "your_api_key_here" else ""


def synthesize_local(text, settings, work, mp3):
    script, wav = work / "speech.txt", work / "speech.wav"
    script.write_text(text, encoding="utf-8")
    if settings["provider"] == "windows-speech":
        result = windows_speech(settings["language"], text=script, wav=wav, voice=settings["voice"],
                                rate=settings["rate"])
        result.check_returncode()
    else:
        subprocess.run(
            [*espeak_command(), "-b", "1", "-v", settings["voice"], "-s", str(settings["rate"]),
             "-f", str(script), "-w", str(wav)],
            capture_output=True, check=True, timeout=60,
        )
    filters = []
    if "end_pause_seconds" in settings:
        # Windows adds a long tail to every file. Shorten it without altering the pauses inside a sentence.
        filters = ["-af", ("areverse,silenceremove=start_periods=1:start_duration=0.03:"
                           f"start_threshold=-55dB:start_silence={settings['end_pause_seconds']},areverse")]
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(wav), *filters,
         "-ar", "44100", "-ac", "1", "-b:a", "128k", str(mp3)],
        capture_output=True, check=True, timeout=30,
    )


def replay_saved(directory, briefing):
    edition = briefing["edition"]
    try:
        manifest = json.loads((directory / edition / "audio.json").read_text(encoding="utf-8"))
        if (manifest["edition"] != edition or manifest["status"] != "ready"
                or len(manifest["segments"]) != len(briefing["spoken_segments"])):
            return None
        provider = manifest.get("provider", "elevenlabs")  # Original manifests were exclusive to ElevenLabs.
        if (provider not in {"elevenlabs", "windows-speech", "espeak-ng"}
                or providers.cloud_only() and provider != "elevenlabs"
                or manifest.get("language", briefing["selection"]["language"]) != briefing["selection"]["language"]):
            return None
        seconds = 0
        for block, part in zip(briefing["spoken_segments"], manifest["segments"]):
            name = part["file"]
            if (any(part.get(key) != value for key, value in block.items())
                    or part.get("provider", provider) != provider
                    or not re.fullmatch(r"[a-f0-9]{64}\.mp3", name)
                    or not 0 < part["duration"] < 3600
                    or part["start_seconds"] != seconds
                    or part["sha256"] != sha256((directory / "audio" / name).read_bytes()).hexdigest()):
                return None
            seconds += part["duration"]
            part.update(cache_hit=True, provider=provider, end_seconds=seconds, url=f"/api/audio/{edition}/{name}")
        if manifest["duration"] == seconds:
            return {**manifest, "provider": provider}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    return None


def render(directory, draft, briefing, *, refresh=False):
    validate_daily(draft, briefing)
    mode = narration_mode()
    saved = replay_saved(directory, briefing)
    if saved and not refresh and (
            mode in {"auto", saved["provider"]} or (mode == "offline" and saved["provider"] != "elevenlabs")
    ):
        return saved
    try:
        if not which("ffprobe"):
            raise ValueError("Install FFmpeg with ffprobe on PATH to enable narration.")
        settings = speech_settings(briefing["selection"]["language"])
        if settings["provider"] != "elevenlabs" and not which("ffmpeg"):
            raise ValueError("Install FFmpeg on PATH to enable offline narration.")
        if saved and settings["provider"] == "elevenlabs" and (providers.paid_requests_paused() or not elevenlabs_key()):
            return saved
    except (ValueError, OSError, subprocess.SubprocessError):
        if saved:
            return saved
        raise
    cache = directory / "audio"
    cache.mkdir(parents=True, exist_ok=True)
    segments, seconds = [], 0
    for block in briefing["spoken_segments"]:
        key = digest([block["text"], settings])
        mp3, meta = cache / (key + ".mp3"), cache / (key + ".json")
        metadata = None
        if meta.exists() and mp3.exists():
            try:
                stored = json.loads(meta.read_text(encoding="utf-8"))
                if (all(stored.get(key) == value for key, value in settings.items())
                        and 0 < stored["duration"] < 3600
                        and stored.get("sha256") == sha256(mp3.read_bytes()).hexdigest()):
                    metadata = stored
            except (ValueError, AttributeError, KeyError, TypeError):
                pass
        reused = metadata is not None
        if not metadata:
            start = perf_counter()
            usage = {}
            request_id = None
            with TemporaryDirectory(dir=cache) as workspace:
                work = Path(workspace).resolve()
                temporary = work / "speech.mp3"
                if settings["provider"] == "elevenlabs":
                    api_key = elevenlabs_key()
                    if not api_key:
                        raise ValueError("Configure ElevenLabs credentials to generate audio.")
                    providers.require_paid_requests()
                    audio, request_id = synthesize_chunk(
                        block["text"], api_key, settings["voice"], settings["model"],
                        settings["format"], 60, 2, telemetry=usage,
                    )
                    temporary.write_bytes(audio)
                else:
                    synthesize_local(block["text"], settings, work, temporary)
                    audio = temporary.read_bytes()
                    usage["provider_character_cost"] = 0
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
        segments.append(
            {
                **block,
                **metadata,
                "cache_hit": reused,
                "file": key + ".mp3",
                "start_seconds": seconds,
                "end_seconds": seconds + metadata["duration"],
                "url": "/api/audio/" + briefing["edition"] + "/" + key + ".mp3",
            }
        )
        seconds += metadata["duration"]
    manifest = {"edition": briefing["edition"], "duration": seconds, "segments": segments,
                "status": "ready", **settings}
    write_atomic(directory / briefing["edition"] / "audio.json", json.dumps(manifest, ensure_ascii=False))
    return manifest
