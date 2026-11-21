import os
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from certa import narration


class NarrationRoutingTest(unittest.TestCase):
    def settings(self, env, language="en", voice="VOICE-ID"):
        with (patch.dict(os.environ, env, clear=True),
              patch.object(narration.providers, "environment_files", return_value=()),
              patch.object(narration.sys, "platform", "win32"),
              patch.object(narration, "espeak_command", return_value=[]),
              patch.object(narration, "which", side_effect=lambda name: name if name == "powershell.exe" else None),
              patch.object(narration, "windows_speech", return_value=SimpleNamespace(
                  returncode=0 if voice else 3, stdout=voice)) as speech):
            result = narration.speech_settings(language)
            return result, speech

    def test_no_credentials_uses_language_matched_offline_speech(self):
        result, speech = self.settings({}, "nl")
        self.assertEqual(result["provider"], "windows-speech")
        self.assertEqual(result["language"], "nl")
        speech.assert_called_once_with("nl")

    def test_missing_voice_does_not_substitute_another_language(self):
        with self.assertRaisesRegex(ValueError, "No offline speech voice is installed for de"):
            self.settings({"CERTA_NARRATION": "offline"}, "de", voice="")

    def test_paused_uses_offline_even_with_credentials_and_local_writer(self):
        result, _ = self.settings({"ELEVENLABS_API_KEY": "mock", "ELEVENLABS_VOICE_ID": "mock",
                                   "CERTA_PROVIDER": "ollama", "CERTA_API_REQUESTS_PAUSED": "1"})
        self.assertEqual(result["provider"], "windows-speech")

    def test_cloud_only_never_resolves_a_local_voice(self):
        result, speech = self.settings({"ELEVENLABS_VOICE_ID": "mock", "CERTA_CLOUD_ONLY": "1",
                                        "CERTA_NARRATION": "offline"})
        self.assertEqual(result["provider"], "elevenlabs")
        speech.assert_not_called()

    def test_saved_audio_replays_without_tools_and_preserves_original_receipt(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            edition, name = "a" * 64, "b" * 64 + ".mp3"
            for subdir in ("audio", edition):
                (directory / subdir).mkdir()
            audio = directory / "audio" / name
            audio.write_bytes(b"stored speech")
            block = {"kind": "claim", "claim_id": "checked", "text": "Test claim."}
            briefing = {"edition": edition, "selection": {"language": "en"}, "spoken_segments": [block]}
            manifest = {"edition": edition, "status": "ready", "provider": "windows-speech", "duration": 2.5,
                        "segments": [{**block, "start_seconds": 0, "duration": 2.5, "file": name,
                                      "cache_hit": False, "sha256": sha256(audio.read_bytes()).hexdigest()}]}
            receipt = directory / edition / "audio.json"
            receipt.write_text(json.dumps(manifest), encoding="utf-8")
            with (patch.object(narration, "validate_daily") as validate,
                  patch.object(narration, "narration_mode", return_value="auto"),
                  patch.object(narration.providers, "cloud_only", return_value=False),
                  patch.object(narration, "which", return_value=None) as tools):
                result = narration.render(directory, {}, briefing)
                validate.assert_called_once_with({}, briefing)
                tools.assert_not_called()
                self.assertTrue(result["segments"][0]["cache_hit"])
                self.assertEqual(result["segments"][0]["end_seconds"], 2.5)
                self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), manifest)
                modified = {**briefing, "spoken_segments": [{**block, "text": "Different wording."}]}
                self.assertIsNone(narration.replay_saved(directory, modified))
                audio.write_bytes(b"damaged")
                with self.assertRaisesRegex(ValueError, "Install FFmpeg"):
                    narration.render(directory, {}, briefing)

    def test_cloud_refresh_reuses_recording_while_paid_calls_are_paused(self):
        saved = {"provider": "elevenlabs", "segments": [{"cache_hit": True}]}
        with (patch.object(narration, "validate_daily"),
              patch.object(narration, "narration_mode", return_value="elevenlabs"),
              patch.object(narration, "replay_saved", return_value=saved),
              patch.object(narration, "which", return_value="ffprobe"),
              patch.object(narration, "speech_settings", return_value={"provider": "elevenlabs"}),
              patch.object(narration.providers, "paid_requests_paused", return_value=True),
              patch.object(narration, "synthesize_chunk") as speech):
            self.assertEqual(narration.render(Path("."), {}, {"selection": {"language": "en"}}, refresh=True), saved)
            speech.assert_not_called()


if __name__ == "__main__":
    unittest.main()
