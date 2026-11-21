from contextlib import closing
from copy import deepcopy
from datetime import date
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from build_preai import NoCoverage
from generate_script import compose_draft, ScriptError, validate_daily
from certa.daily import prepare
from certa.delivery import compose_day
from certa.daily_web import identity, respond
from certa.editions import personal_draft
from certa.group_events import write_jsonl
from certa.listeners import Conflict, check_in, delivered, previous_claims, record_delivery, revise, storage
from certa.overview_reader import connect, get_event, Passages
from certa.source_store import import_feeds


class BrowserIdentityTest(unittest.TestCase):
    def test_previous_cookie_keeps_the_same_listener_after_the_rename(self):
        token = "ab" * 32
        old = SimpleNamespace(headers={"Cookie": f"voxlistener={token}"})
        new = SimpleNamespace(headers={"Cookie": f"certa_listener={token}"})
        self.assertEqual(identity(old), identity(new))
        self.assertTrue(old.listener_cookie.startswith(f"certa_listener={token};"))
        self.assertTrue(old.expire_legacy_listener)
        both = SimpleNamespace(headers={"Cookie": f"certa_listener={token}; voxlistener={'ef' * 32}"})
        self.assertEqual(identity(both), identity(new))
        self.assertFalse(hasattr(both, "listener_cookie"))


class DailyBackendTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.feeds = self.root / "feeds"
        self.out = self.root / "out"
        self.catalogue = self.out / "event-overviews.sqlite3"
        rows = []
        for id, when, title, body in [
            (
                "early",
                "17",
                "Bank of England decision",
                "The Bank of England held Bank Rate at 4% on November 5.",
            ),
            ("later", "19", "UK inflation and exchange rates", "UK annual CPI was 3.6% in October 2026."),
            ("nl", "19", "Dutch inflation", "Dutch annual CPI was 3.7% in October 2026."),
        ]:
            rows.append(
                {
                    "$id": id,
                    "date": f"2026-11-{when}T12:00:00Z",
                    "language": "en",
                    "headline": title,
                    "text_content": body,
                    "excerpt": body,
                    "permalink": "https://example.org/" + id,
                    "publication": {"name": "News"},
                }
            )
        self.rows = rows
        write_jsonl(self.feeds / "news.jsonl", rows)
        self.reports = [
            prepare(self.feeds, self.out, date(2026, 11, day), 7, offline=True) for day in (18, 19)
        ]
        key = patch("generate_script.api_key", return_value=None)
        key.start()
        self.addCleanup(key.stop)

    def profile(self, db, listener, region=None):
        return revise(
            db,
            listener,
            {
                "topics": ["economy_central_banks"],
                "region": region,
                "language": "nl",
                "minutes": 2,
                "depth": "standard",
            },
            "explicit settings",
        )

    def edition(self, db, listener, profile, day):
        draft = personal_draft(self.catalogue, profile, day, previous_claims(db, listener, day))
        briefing = compose_draft(draft, profile)
        return draft, record_delivery(db, listener, draft, briefing)

    def test_source_revisions_cutoff_and_draft_validation(self):
        self.assertEqual([r["source_import"]["new_versions"] for r in self.reports], [3, 0])
        with storage(self.root / "listeners") as db:
            profile = self.profile(db, "one", "GB")
            draft, first = self.edition(db, "one", profile, "2026-11-18")
            self.assertNotIn("3,6", first["script"])
            self.assertEqual(first["validation"], "passed")
            with self.assertRaises(NoCoverage):
                personal_draft(self.catalogue, profile, "2026-11-15", {})
            copy = deepcopy(first)
            copy["segments"][0]["text"] += " 99%"
            with self.assertRaises(ScriptError):
                validate_daily(draft, copy)
            self.rows[0]["text_content"] += " A correction was published."
            write_jsonl(self.feeds / "news.jsonl", self.rows)
            changed = prepare(self.feeds, self.out, date(2026, 11, 19), 7, offline=True)
            self.assertEqual(changed["source_import"]["new_versions"], 1)
            with closing(connect(self.catalogue)) as ed:
                c = first["segments"][0]
                event = get_event(ed, c["event_id"], c["revision"])
                self.assertTrue(Passages(ed).text(c["sources"][0], event["sources"]))

    def test_replay_keeps_first_attempt_and_migrates_an_older_report(self):
        day = date(2026, 11, 19)
        directory = self.out / "days" / day.isoformat()
        original = self.reports[-1]
        old_path = directory / "attempts" / (original["attempt_id"] + ".json")
        original_bytes = old_path.read_bytes()
        (directory / "report.json").write_text('{"old":true}', encoding="utf-8")
        replay = prepare(self.feeds, self.out, day, 7, offline=True)
        self.assertEqual(old_path.read_bytes(), original_bytes)
        self.assertEqual(json.loads(next((directory / "attempts").glob("legacy-*.json")).read_bytes()), {"old": True})
        self.assertEqual(json.loads((directory / "report.json").read_bytes())["attempt_id"], replay["attempt_id"])
        self.assertNotEqual(replay["attempt_id"], original["attempt_id"])

    def test_two_day_feedback_is_scoped_idempotent_and_reversible(self):
        with storage(self.root / "listeners") as db:
            profile = self.profile(db, "one", "GB")
            _, day1 = self.edition(db, "one", profile, "2026-11-18")
            feedback = {"more": ["currencies"], "length": "less", "depth": "less", "useful": "yes"}
            changed = check_in(db, "one", day1["edition"], feedback)
            self.assertEqual((changed["version"], changed["minutes"], changed["depth"]), (2, 1, "headlines"))
            self.assertEqual(check_in(db, "one", day1["edition"], feedback), changed)
            draft, day2 = self.edition(db, "one", changed, "2026-11-19")
            self.assertEqual(draft["events"][0]["section"], "local")
            self.assertIn("3,6", day2["script"])
            self.assertTrue(
                set(s["claim_id"] for s in day1["segments"]).isdisjoint(
                    s["claim_id"] for s in day2["segments"]
                )
            )
            self.assertEqual(delivered(db, "one", "2026-11-18"), day1)
            other = self.profile(db, "two", "NL")
            otherdraft, _ = self.edition(db, "two", other, "2026-11-19")
            self.assertNotEqual(draft["events"][0]["event_id"], otherdraft["events"][0]["event_id"])
            with self.assertRaises(ValueError):
                check_in(db, "two", day1["edition"], feedback)
            undone = check_in(db, "one", day1["edition"], {}, undo=True)
            self.assertEqual(undone["topics"], profile["topics"])
            self.assertEqual(check_in(db, "one", day1["edition"], {}, undo=True), undone)
            self.assertEqual(check_in(db, "one", day2["edition"], {"skip": True}), undone)

    def test_import_is_atomic_on_bad_record(self):
        store = self.out / "sources.sqlite3"
        write_jsonl(self.feeds / "news.jsonl", [*self.rows, self.rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            import_feeds(self.feeds, store)
        with closing(sqlite3.connect(store)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM story_version").fetchone()[0], 3)

    def test_cloud_only_never_replays_a_saved_local_or_offline_edition(self):
        directory=self.root/"cloud-history"
        with storage(directory) as db:
            profile=self.profile(db,"one","GB")
            self.edition(db,"one",profile,"2026-11-19")
        with patch.dict("os.environ",{"CERTA_CLOUD_ONLY":"1","CERTA_PROVIDER":"openai"}):
            with self.assertRaisesRegex(Conflict,"isolated cloud demo"):
                compose_day(directory,"one","2026-11-19")

    def test_event_uncertainty_caveat_cannot_be_removed_from_final_text(self):
        from generate_script import UNRESOLVED
        with storage(self.root / "caveat-listener") as db:
            profile = self.profile(db, "one", "GB")
        draft = personal_draft(self.catalogue, profile, "2026-11-19", {})
        draft["events"][0]["caveats"] = ["unresolved_reporting"]
        briefing = compose_draft(draft, profile)
        warning = UNRESOLVED[profile["language"]]
        self.assertEqual(briefing["script"].count(warning), 1)
        altered = deepcopy(briefing)
        altered["script"] = altered["script"].replace(warning, "")
        with self.assertRaises(ScriptError):
            validate_daily(draft, altered)

    def test_composition_lease_reuse_and_profile_change_during_generation(self):
        directory = self.root / "listeners"
        with storage(directory) as db:
            profile = self.profile(db, "one", "GB")

        def compose_with_competing_request(draft, settings):
            with self.assertRaises(Conflict):
                compose_day(directory, "one", "2026-11-19")
            return compose_draft(draft, settings)

        with patch("certa.delivery.database_path", return_value=self.catalogue):
            with patch("certa.delivery.compose_draft", side_effect=compose_with_competing_request) as writer:
                first = compose_day(directory, "one", "2026-11-19", profile["version"])
                self.assertEqual(compose_day(directory, "one", "2026-11-19"), first)
                self.assertEqual(writer.call_count, 1)

            def change_profile(draft, settings):
                with storage(directory) as db:
                    revise(db, "one", {**profile, "minutes": 5}, "explicit settings")
                return compose_draft(draft, settings)

            with patch("certa.delivery.compose_draft", side_effect=change_profile):
                with self.assertRaisesRegex(Conflict, "changed during composition"):
                    compose_day(directory, "one", "2026-11-18", profile["version"])
        with storage(directory) as db:
            self.assertIsNone(delivered(db, "one", "2026-11-18"))
            self.assertEqual(db.execute("SELECT count(*) FROM composition_job").fetchone()[0], 0)

    def test_daily_http_setup_briefing_feedback_and_listener_isolation(self):
        directory = self.root / "http-listeners"
        cookie = ""

        def request(path, payload=None, *, isolated=False):
            nonlocal cookie
            headers = Message()
            if cookie and not isolated:
                headers["Cookie"] = cookie
            encoded = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(encoded))
            handler = SimpleNamespace(path=path, headers=headers, rfile=BytesIO(encoded),
                                      reply=Mock(), send_error=Mock(), log_error=Mock())
            respond(handler, directory, post=payload is not None)
            if hasattr(handler, "listener_cookie") and not isolated:
                cookie = handler.listener_cookie.split(";", 1)[0]
            status, body, *kind = handler.reply.call_args.args
            return status, json.loads(body) if kind == ["application/json"] else body

        with patch("certa.daily_web.database_path", return_value=self.catalogue), \
                patch("certa.delivery.database_path", return_value=self.catalogue):
            status, initial = request("/api/profile")
            self.assertEqual(status, 200)
            self.assertIsNone(initial["profile"])
            status, profile = request("/api/profile", {"topics": ["economy_central_banks"],
                "language": "en", "region": "GB", "minutes": 2, "depth": "standard"})
            self.assertEqual(status, 200)
            status, first = request("/api/briefing", {"date": "2026-11-18", "version": profile["version"]})
            self.assertEqual(status, 200)
            self.assertEqual(first["validation"], "passed")
            claim = first["segments"][0]
            status, evidence = request(f'/evidence/{claim["event_id"]}/{claim["revision"]}?claim={claim["claim_id"]}')
            self.assertEqual(status, 200)
            self.assertIn(f'<details id="c{claim["claim_id"]}" open>', evidence)
            self.assertIn("<blockquote>", evidence)
            status, changed = request("/api/feedback", {"edition": first["edition"],
                "answers": {"length": "less", "more": ["currencies"]}})
            self.assertEqual((status, changed["version"], changed["minutes"]), (200, 2, 1))
            status, second = request("/api/briefing", {"date": "2026-11-19", "version": changed["version"]})
            self.assertEqual(status, 200)
            self.assertEqual(second["profile_version"], changed["version"])
            self.assertNotEqual(first["segments"], second["segments"])
            self.assertEqual(request("/api/briefing", {"date": "2026-11-18"})[1], first)
            self.assertEqual(request("/api/profile", isolated=True)[1]["profile"], None)
            self.assertEqual(request("/api/feedback", {"edition": first["edition"],
                "answers": {"skip": True}}, isolated=True)[0], 400)

            _, presets = request("/api/people")
            self.assertEqual([p["name"] for p in presets], ["Maya", "Ellis", "Noor", "Jonas"])
            for key, lang, region in (("noor", "nl", "NL"), ("jonas", "de", "DE")):
                _, state = request("/api/profile?persona=" + key)
                self.assertEqual((state["profile"]["language"], state["profile"]["region"]), (lang, region))
            _, tech = request("/api/profile?persona=technology")
            _, macro = request("/api/profile?persona=macro")
            self.assertNotEqual(tech["profile"]["topics"], macro["profile"]["topics"])
            self.assertNotEqual(tech["profile"]["depth"], macro["profile"]["depth"])
            status, wildcard = request("/api/people", {
                "name": "Wildcard", "settings": {**macro["profile"], "minutes": 4, "region": "GB"},
            })
            self.assertEqual(status, 200)
            query = "?persona=" + wildcard["id"]
            self.assertEqual(request("/api/people")[1][-1]["name"], "Wildcard")
            self.assertEqual(request("/api/people", isolated=True)[1], presets)
            self.assertEqual(request("/api/profile" + query, isolated=True)[0], 400)
            _, wildcard_profile = request("/api/profile" + query)
            self.assertEqual(wildcard_profile["profile"]["minutes"], 4)
            status, wildcard_edition = request("/api/briefing" + query, {"date": "2026-11-18"})
            self.assertEqual(status, 200)
            self.assertNotEqual(wildcard_edition["edition"], first["edition"])
            self.assertEqual(request("/api/feedback", {"edition": wildcard_edition["edition"],
                "answers": {"skip": True}})[0], 400)
            self.assertEqual(request("/api/feedback" + query, {"edition": wildcard_edition["edition"],
                "answers": {"length": "more"}})[1]["minutes"], 5)
            self.assertEqual(request("/api/profile?persona=macro")[1]["profile"]["minutes"], 8)
            self.assertEqual(request("/api/profile" + query)[1]["delivered"], ["2026-11-18"])
            self.assertEqual(request("/api/profile?persona=macro")[1]["delivered"], [])
            remove = "/api/people/remove"
            self.assertEqual(request(remove, {"id": wildcard["id"]}, isolated=True)[0], 400)
            self.assertEqual(request(remove, {"id": wildcard["id"]})[0], 200)
            self.assertEqual(request("/api/profile" + query)[0], 400)
            self.assertEqual(request("/api/people")[1], presets)
            for preset in presets:
                self.assertEqual(request(remove, {"id": preset["id"]})[0], 200)
            self.assertEqual(request("/api/people")[1], [])
            self.assertEqual(request("/api/profile?persona=macro")[0], 400)
            self.assertEqual(request("/api/people", isolated=True)[1], presets)
            self.assertEqual(request(remove, {"id": ""})[0], 200)
            self.assertEqual(request("/api/profile")[0], 400)
            status, new = request("/api/people", {"name": "New listener", "settings": tech["profile"]})
            self.assertEqual(status, 200)
            self.assertEqual(request("/api/people")[1], [{"id": new["id"], "name": "New listener"}])
