"""Exercise the listener routes against a catalogue built by the editorial pipeline."""
from contextlib import closing
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import app
from build_preai import build_preai, make_draft
from generate_script import request_script, ScriptError
from certa.categorize import run as categorize
from certa.group_events import timestamp, write_jsonl
from certa.overview import build
from certa.verify import verify


class ListenerIntegrationTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "overview.sqlite3"
        self.listener = self.root / "user_data"
        self.listener.mkdir()
        (self.listener / "UserInfo.md").write_text("Two minutes of markets news.", encoding="utf-8")
        for context in (patch.object(app, "DIRECTORY", self.listener),
                        patch.dict(os.environ, {"CERTA_OVERVIEW_DB": str(self.db)}),
                        patch("generate_script.api_key", return_value=None)):
            context.start()
            self.addCleanup(context.stop)
        self.feeds = self.root / "feeds"
        self.rows = []
        for aid, title, body in [
            ("uk", "Exchange rates and UK inflation", "UK annual CPI was 3.6% in October 2026."),
            ("nl", "Dutch inflation", "Dutch annual CPI was 3.7% in October 2026."),
            ("tech", "Software outage", "The service went offline early on Monday.")]:
            self.rows.append({"$id": aid, "text_content": body, "excerpt": body, "headline": title,
                              "language": "en", "permalink": "https://example.com/" + aid,
                              "date": "2026-11-19T12:00:00Z", "publication": {"name": "Example News"}})
        self.seed()

    def seed(self):
        write_jsonl(self.feeds / "news.jsonl", self.rows)
        cats = self.root / "categories.jsonl"
        categorize(self.feeds, cats)
        with closing(sqlite3.connect(":memory:")) as db:
            snapshot = verify(self.feeds, timestamp("2026-11-20", allow_date=True), db)
        verified = self.root / "verification.json"
        verified.write_text(json.dumps(snapshot), encoding="utf-8")
        build(verified, self.feeds, cats, self.db)

    def call(self, path, payload=None):
        handler = object.__new__(app.Picker)
        handler.path = path
        handler.headers = Mock()
        handler.reply = Mock()
        handler.log_error = Mock()
        if payload is None:
            handler.do_GET()
        else:
            data = json.dumps(payload).encode()
            handler.rfile = BytesIO(data)
            handler.headers.get.return_value = str(len(data))
            handler.headers.get_content_type.return_value = "application/json"
            handler.do_POST()
        status, body, *kind = handler.reply.call_args.args
        return status, json.loads(body) if kind == ["application/json"] else body

    def test_page_contains_filtered_topics_before_javascript_runs(self):
        class TopicInputs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.topics = {}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("name") == "topic":
                    self.topics[attrs["value"]] = attrs

        for query, selected in [
            ("", set()),
            ("?region=GB&language=nl&topic=currencies&topic=technology_ai", {"currencies"}),
            ("?region=DE&language=nl&topic=currencies", set()),
        ]:
            with self.subTest(query=query):
                status, page = self.call("/picker" + query)
                self.assertEqual(status, 200)
                parser = TopicInputs()
                parser.feed(page)
                _, catalogue = self.call("/categories" + query)
                expected = {t["id"]: t["events"] for t in catalogue["topics"]}
                self.assertEqual(set(parser.topics), set(expected))
                for topic, attrs in parser.topics.items():
                    self.assertEqual("disabled" in attrs, expected[topic] == 0)
                    self.assertEqual("checked" in attrs, topic in selected)
                self.assertEqual("No approved reporting for this area" in page, not any(expected.values()))
        self.db.unlink()
        self.assertEqual(self.call("/")[0], 503)

    def test_picker_to_draft_to_model_to_transcript(self):
        status, options = self.call("/categories?region=GB")
        self.assertEqual(status, 200)
        counts = {t["id"]: t["events"] for t in options["topics"]}
        self.assertEqual(counts["economy_central_banks"], 1)
        self.assertEqual(counts["technology_ai"], 0)
        self.assertEqual(counts["currencies"], 1)
        selection = {"topics": ["economy_central_banks", "currencies"], "language": "nl", "region": "GB"}
        def pick_claim(draft, profile, key):
            self.assertIn("Two minutes", profile)
            self.assertEqual(len(draft["events"]), 1)
            return [draft["events"][0]["claims"][0]["claim_id"]]
        with patch("generate_script.api_key", return_value="test"), patch("generate_script.request_script", side_effect=pick_claim):
            status, result = self.call("/save", selection)
        self.assertEqual(status, 200)
        self.assertEqual(result["composition"], "model_selection")
        self.assertIn("3,6", result["script"])
        self.assertNotIn("3,7", result["script"])
        self.assertEqual(len(result["segments"]), 1)
        segment = result["segments"][0]
        self.assertTrue(segment["revision"])
        self.assertTrue(segment["event_id"])
        self.assertIn("https://example.com/uk", {s["url"] for s in segment["sources"]})
        self.assertEqual({s["role"] for s in segment["sources"]}, {"supports", "official_at_cutoff"})
        saved = self.listener / "briefings" / result["edition"]
        self.assertEqual(json.loads((saved / "briefing.json").read_text())["segments"], result["segments"])
        self.assertEqual(build_preai(self.listener)["selection"], selection)
        status, other = self.call("/save", {"topics": ["economy_central_banks"], "language": "nl", "region": "NL"})
        self.assertEqual(status, 200)
        self.assertIn("3,7", other["script"])
        self.assertEqual((saved / "script.md").read_text(), result["script"])

    def test_elevenlabs_narration_uses_saved_edition(self):
        status, result = self.call("/save", {"topics": ["economy_central_banks"], "language": "nl", "region": "GB"})
        self.assertEqual(status, 200)
        handler = object.__new__(app.Picker)
        handler.path = "/narrate"
        data = json.dumps({"edition": result["edition"], "script": result["script"]}).encode()
        handler.rfile, handler.wfile = BytesIO(data), BytesIO()
        handler.headers = Mock()
        handler.headers.get.return_value = str(len(data))
        handler.headers.get_content_type.return_value = "application/json"
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test", "ELEVENLABS_VOICE_ID": "test"}), \
             patch("md_to_speech.synthesize_chunk", return_value=(bytes(4800), "test-request")) as tts:
            handler.do_POST()
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(tts.call_args.args[0], result["script"].strip())
        self.assertTrue(handler.wfile.getvalue().startswith(b"RIFF"))

    def test_empty_and_invalid_submissions_never_reach_writer(self):
        with patch("app.compose_draft") as writer:
            for payload, status in [({"topics": ["Cloud Computing and AI"]}, 400), ({"topics": []}, 400),
                                    ({"topics": ["crypto"], "region": "invalid"}, 400),
                                    ({"topics": ["technology_ai"]}, 422),
                                    ({"topics": ["economy_central_banks"], "region": "DE"}, 422)]:
                self.assertEqual(self.call("/save", payload)[0], status)
            writer.assert_not_called()
        self.db.unlink()
        self.assertEqual(self.call("/categories")[0], 503)
        self.assertFalse(self.db.exists())

    def test_disputed_claim_and_invalid_writer_selection_are_held(self):
        self.rows.append({**self.rows[0], "$id": "conflict", "permalink": "https://example.com/conflict",
                          "text_content": "UK annual CPI was 3.7% in October 2026."})
        self.seed()
        self.assertEqual(self.call("/save", {"topics": ["economy_central_banks"], "region": "GB"})[0], 422)
        with patch("generate_script.api_key", return_value="test"), patch("generate_script.request_script", return_value=["invented"]):
            self.assertEqual(self.call("/save", {"topics": ["economy_central_banks"], "region": "NL"})[0], 422)
        self.assertFalse((self.listener / "script.md").exists())

    def test_writer_packet_exposes_only_selectable_claim_aliases(self):
        draft = make_draft(self.db, {"topics": ["economy_central_banks"], "region": "GB", "language": "en"})
        original = draft["events"][0]["claims"][0]["claim_id"]
        draft["id"] = "private-draft-hash"
        draft["events"][0]["overview"] = {"title": "Inflation", "coverage": {
            "background": {"available_passages": 3, "approved_claim_ids": [original, "not-selected"]}}}
        with patch("generate_script.urlopen") as transport:
            reply = transport.return_value.__enter__.return_value
            def output(ids):
                return json.dumps({"status": "completed", "usage": {"input_tokens": 30, "output_tokens": 5},
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"claim_ids": ids})}]}]}).encode()
            reply.read.return_value = output(["c1"])
            self.assertEqual(request_script(draft, {}, "test")["claim_ids"], [original])
            payload = json.loads(transport.call_args.args[0].data)
            self.assertEqual(payload["text"]["format"]["schema"]["properties"]["claim_ids"]["items"]["enum"], ["c1"])
            self.assertNotIn(original, payload["input"])
            self.assertNotIn("not-selected", payload["input"])
            self.assertNotIn("private-draft-hash", payload["input"])
            reply.read.return_value = output(["c2"])
            with self.assertRaises(ScriptError):
                request_script(draft, {}, "test")


if __name__ == "__main__":
    unittest.main()
