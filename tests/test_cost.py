from contextlib import closing
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

import generate_script
import md_to_speech
from certa import providers
from certa.cost import inference, receipt_report, report
from certa.usage import preparation_attempt, provider_response, writer_attempt


class CostAccountingTests(unittest.TestCase):
    prices = {"writer": {"input": 5, "cached": 1, "output": 10}}

    def test_writer_uses_provider_cached_input_detail(self):
        usage = {"model": "writer", "calls": 1, "input_tokens": 1000, "output_tokens": 50,
                 "input_tokens_details": {"cached_tokens": 900}}
        record = inference(usage, "openai", self.prices)
        self.assertEqual(record["cached_input_tokens"], 900)
        self.assertAlmostEqual(record["estimated_provider_usd"], .0019)

    def test_interrupted_paid_attempt_and_cached_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            def response(*args, **kwargs):
                return closing(BytesIO(b'{"usage":{"input_tokens":100,"output_tokens":10}}'))
            with self.assertRaises(TimeoutError), preparation_attempt(root, "openai", 7):
                provider_response(None, response, stage="review", model="writer", timeout=5)
                def lost_receipt(*args, **kwargs):
                    raise TimeoutError()
                provider_response(None, lost_receipt, stage="review", model="writer", timeout=5)
            with preparation_attempt(root, "openai", 7):
                pass
            result = receipt_report(root / "usage.sqlite3", self.prices)
            self.assertEqual([a["status"] for a in result["attempts"]], ["failed", "completed"])
            self.assertEqual(result["hosted_requests"][0]["calls"], 2)
            self.assertEqual(result["hosted_requests"][0]["unmetered_calls"], 1)
            self.assertIsNone(result["estimated_shared_provider_usd"])

    def test_local_speech_and_machine_cost_are_separate(self):
        run = {"date": "2026-11-19", "source_import": {"articles": 1740}, "mode": "offline",
               "grouping": None, "total_seconds": 360, "verification": {"articles_in_window": 1740,
               "events": 100, "model_events_processed": 0, "model_usage": {}}}
        audio = [{"duration": 60, "segments": [{"characters": 200, "provider": "windows-speech",
                                                "latency_seconds": 36}]}]
        cost = report(run, audio=audio, machine_rate=1)
        self.assertEqual(cost["total_provider_usd"], 0)
        self.assertAlmostEqual(cost["machine_scenario"]["total_usd"], .11)
        self.assertAlmostEqual(cost["machine_scenario"]["ten_times_new_articles_same_listeners_usd"], 1.01)
        audio[0]["segments"][0]["provider"] = "elevenlabs"
        self.assertIsNone(report(run, audio=audio)["total_provider_usd"])

    def test_daily_writer_records_usage_before_validating_the_reply(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with (
                patch.dict(os.environ, {"CERTA_PROVIDER": "openai", "CERTA_CLOUD_ONLY": "0",
                                        "CERTA_API_REQUESTS_PAUSED": "0", "CERTA_COMPOSITION_MODEL": "writer"}),
                patch.object(generate_script, "urlopen",
                             return_value=closing(BytesIO(b'{"status":"incomplete","usage":{"input_tokens":100,"output_tokens":10}}'))),
                self.assertRaises(generate_script.ScriptError),
                writer_attempt(directory, "2026-11-19"),
            ):
                generate_script.request_script({"events": []}, {}, "test-key")
            ledger = directory / "usage" / "days" / "2026-11-19" / "usage.sqlite3"
            receipt = receipt_report(ledger, self.prices, scope="writer")
            self.assertEqual(receipt["attempts"][0]["status"], "failed")
            self.assertEqual(receipt["hosted_requests"][0]["stage"], "writing")
            self.assertAlmostEqual(receipt["estimated_writer_provider_usd"], .0006)

    def test_paid_speech_pause_applies_to_ollama_and_to_retries(self):
        with patch.dict(os.environ, {"CERTA_PROVIDER": "ollama", "CERTA_CLOUD_ONLY": "0",
                                    "CERTA_API_REQUESTS_PAUSED": "1"}):
            providers.require_requests()
            with patch.object(md_to_speech.urllib.request, "urlopen") as send:
                with self.assertRaisesRegex(ValueError, "paused"):
                    md_to_speech.synthesize_chunk("test", "key", "voice", "model", "mp3", 1, 1)
                send.assert_not_called()
            os.environ["CERTA_API_REQUESTS_PAUSED"] = "0"

            def pause_after_failure(*args, **kwargs):
                os.environ["CERTA_API_REQUESTS_PAUSED"] = "1"
                raise URLError("simulated failure")

            with (patch.object(md_to_speech.urllib.request, "urlopen", side_effect=pause_after_failure) as send,
                  patch.object(md_to_speech.time, "sleep"), self.assertRaisesRegex(ValueError, "paused")):
                md_to_speech.synthesize_chunk("test", "key", "voice", "model", "mp3", 1, 1)
            send.assert_called_once()
