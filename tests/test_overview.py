from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import wave
from zipfile import ZipFile

from voxnews.categorization import categorize_article
from voxnews.group_events import timestamp, write_jsonl
from voxnews.official_releases import digest
from voxnews.overview import build
from voxnews.overview_demo import event_page, export_demo
from voxnews.overview_reader import catalogue, connect, get_event, log_html, packet, source_log
from voxnews.overview_synthesis import enrich, grounded_notes
from voxnews.overview_web import render
from voxnews.trust_briefing import compose
from voxnews.verify import verify


def article(i, body, language="en"):
    return {"$id": i, "text_content": body, "headline": "Acme earnings and the economy", "language": language,
            "publication": {"name": "Publisher " + i}, "source": "Reporter " + i, "date": "2026-11-19T12:00:00Z",
            "permalink":"https://example.com/" + i}


class OverviewTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "events.db"
        self.feeds = self.root / "feeds"
        self.cats = self.root / "categories.jsonl"
        self.ver = self.root / "verification.json"

    def seed(self, rows, origins=None):
        write_jsonl(self.feeds / "news.jsonl", rows)
        write_jsonl(self.cats, [categorize_article(r) for r in rows])
        group = self.root / "group.jsonl"
        write_jsonl(group, [{"event_id":"evt", "status":"grouped", "sources":[
            {"article_id":r["$id"],"reporting_origin_id":o} for r,o in zip(rows,origins or [r["$id"] for r in rows])]}])
        with closing(sqlite3.connect(":memory:")) as db:
            snap = verify(self.feeds,timestamp("2026-11-20",allow_date=True),db,events=group)
        self.ver.write_text(json.dumps(snap),encoding="utf8")
        return self.run_build()

    def run_build(self):
        return build(self.ver,self.feeds,self.cats,self.db)

    def test_writer_packet_survives_moving_database_and_feeds(self):
        self.seed([article("a", "Acme reported higher production in the quarter.")])
        moved = self.root / "moved"
        moved.mkdir()
        shutil.move(self.feeds, moved / "feeds")
        relocated = moved / self.db.name
        self.db.rename(relocated)
        with closing(connect(relocated)) as db:
            items = packet(db, get_event(db, "evt"), depth="full")["items"]
            self.assertTrue(any("higher production" in i["source_statement"] for i in items))

    def test_offline_archive_preserves_recorded_claim_and_rejects_stale_export(self):
        self.seed([article("a", "UK annual CPI was 3.6% in October 2026.")])
        script = compose(json.loads(self.ver.read_bytes()), "headlines", "en")
        self.assertEqual(len(script["segments"]), 1)
        name = "briefing-" + digest(["fixture", script])[:16] + ".wav"
        with wave.open(str(self.root / name), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0" * 16000)
        script["segments"][0].update(start_seconds=0.25, end_seconds=1)
        script["audio"] = {"file": name, "voice": "fixture", "seconds": 1}
        script_path = self.root / "script.json"
        script_path.write_text(json.dumps(script), encoding="utf-8")
        archive = self.root / "demo.zip"
        with closing(connect(self.db)) as db:
            export_demo(db, self.ver, [self.root], archive)
            with ZipFile(archive) as demo:
                self.assertIsNone(demo.testzip())
                self.assertIn(event_page("evt"), demo.read("index.html").decode())
                self.assertIn(script["segments"][0]["claim_id"][:16], demo.read("briefings/1/index.html").decode())
                self.assertIn(name, demo.read("briefings/1/index.html").decode())
                self.assertIn("briefings/1/" + name, demo.namelist())
                self.assertNotIn("script.json", demo.namelist())
            original = archive.read_bytes()
            script["segments"][0]["text"] = "Unverified replacement."
            script_path.write_text(json.dumps(script), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approved claims"):
                export_demo(db, self.ver, [self.root], archive)
            self.assertEqual(archive.read_bytes(), original)

    def test_full_dossier_covers_late_material_and_selects_by_facet(self):
        filler = " ".join(f"The operator recorded {n} users on the platform." for n in range(1,38))
        body = "The operator published results. " + filler + " Operating margin improved because infrastructure costs fell."
        result = self.seed([article("a",body)])
        self.assertEqual(result["events_with_material"],1)
        with closing(connect(self.db)) as db:
            e = get_event(db,"evt")
            data = packet(db,e,depth="full")
            self.assertGreater(len(data["items"]),35)
            self.assertTrue(data["synopsis"])
            focused = packet(db,e,focus=["mechanism"])
            self.assertTrue(any("infrastructure costs fell" in i["source_statement"] for i in focused["items"]))
            self.assertLess(len(packet(db,e,depth="brief")["items"]),len(data["items"]))
            self.assertTrue(catalogue(db,topic=e["topics"][0]))
            self.assertEqual(catalogue(db,region="unmatched"),[])
            self.assertNotIn("infrastructure costs fell",log_html(e))
            late = next(i for i in data["items"] if i.get("technical_terms") and "infrastructure" in i["source_statement"])
            ref = source_log(e,late)[0]
            self.assertEqual(ref["author"],"Reporter a")
            self.assertEqual(body[ref["start"]:ref["end"]],late["source_statement"])
            self.assertEqual(200 if render(db,"/event",{"id":"evt"})[1].startswith("<!doctype") else 0,200)

    def test_conflicts_hold_both_sides_and_keep_translations_one_origin(self):
        rows = [article("a","Acme reported Q3 2026 revenue of $1 billion."),
                article("b","Acme posted revenue of $900 million for Q3 2026.")]
        self.seed(rows)
        with closing(connect(self.db)) as db:
            p = packet(db,get_event(db,"evt"),depth="brief",focus=["outlook"])
            self.assertFalse(p["items"])
            self.assertEqual(p["disagreements"][0]["kind"],"conflicting_reported_values")
            self.assertEqual({i["evidence"][0]["source_id"] for i in p["disputed_or_revised_material"]},{"a","b"})
        self.seed([rows[0],article("b","Acme posted revenue of $1000 million for Q3 2026.")])
        with closing(connect(self.db)) as db:
            self.assertFalse(get_event(db,"evt")["disagreements"])
        self.seed([article("a","Acme approved the planned acquisition."),article("b","Acme rejected the planned acquisition.")],["same","same"])
        with closing(connect(self.db)) as db:
            self.assertEqual(get_event(db,"evt")["disagreements"][0]["kind"],"same_origin_variance")

    def test_periods_and_estimates_are_not_treated_as_actual_conflicts(self):
        self.seed([article("a","Acme reported Q3 2026 revenue of $1 billion."),
                   article("b","Acme posted revenue of $900 million for Q2 2026. Acme expects revenue of $850 million for Q3 2026.")])
        with closing(connect(self.db)) as db:
            e = get_event(db,"evt")
            self.assertFalse(e["disagreements"])
            self.assertTrue(any("forecast" in i["qualifiers"] for i in e["items"]))

    def test_upstream_conflict_article_and_official_logs_and_stale_editions(self):
        rows = [article("a","UK annual CPI was 3.6% in October 2026."),article("b","UK annual CPI was 3.7% in October 2026.")]
        self.seed(rows)
        with closing(connect(self.db)) as db:
            e = get_event(db,"evt")
            self.assertFalse(packet(db,e)["items"])
            c = next(i for i in e["items"] if i["type"]=="checked_claim")
            roles = {r["role"] for r in source_log(e,c)}
            self.assertTrue({"supports","contradicts","official_at_reporting","official_at_cutoff"} <= roles)
        self.assertEqual(self.run_build()["cache_hits"],1)
        original = rows[0]["text_content"]
        rows[0]["text_content"] = original.replace("3.6","3.5")
        write_jsonl(self.feeds/"news.jsonl",rows)
        with self.assertRaisesRegex(ValueError,"stale verification"):
            self.run_build()
        with closing(connect(self.db)) as db:
            self.assertEqual(get_event(db,"evt")["revision"],e["revision"])
            with self.assertRaisesRegex(ValueError,"source edition"):
                packet(db,e)
        self.seed(rows)
        with closing(connect(self.db)) as db:
            self.assertNotEqual(get_event(db,"evt")["revision"],e["revision"])
            self.assertEqual(get_event(db,"evt",e["revision"])["revision"],e["revision"])

    def test_synthesis_cache_references_and_preference_survive_rebuild(self):
        self.seed([article("a","Acme increased its workforce to 500 users. Sales improved."),
                   article("b","Acme said it now has 500 users.")])
        class Model:
            name,version="test","mock-digest"
            calls=0
            def __call__(self, rows):
                self.calls+=1
                return {"notes":[{"text":"Acme put the user count at 500 users.","kind":"reporting","section":"figures",
                                  "support":[0,1],"opposes":[]}]},{"input_tokens":100,"output_tokens":40}
        m=Model()
        with closing(sqlite3.connect(self.db)) as db:
            result = enrich(db,"evt",m)
            e = get_event(db,"evt")
            n = next(i for i in e["items"] if i["type"]=="synthesis")
            self.assertEqual({r["source_id"] for r in source_log(e,n)},{"a","b"})
            self.assertEqual(n["draft_use"],"paraphrase_and_check")
            self.assertTrue(enrich(db,"evt",m)["cached"])
            self.assertEqual(m.calls,1)
        self.run_build()
        with closing(connect(self.db)) as db:
            self.assertEqual(get_event(db,"evt")["revision"],result["revision"])

    def test_unknown_references_invented_values_and_changed_units_are_rejected(self):
        item={"id":"a","evidence":[{"source_id":"s"}],"draft_use":"paraphrase_and_check","qualifiers":[],"disagreements":[]}
        batch=[(item,{"text":"Acme spent $3 million on equipment."})]
        base={"text":"Acme allocated $3 million for equipment.","section":"figures","kind":"reporting","support":[0],"opposes":[]}
        proposals=[{**base,"text":"Acme spent $4 million."},{**base,"text":"Acme spent $3 billion."},{**base,"support":[20]}]
        notes, rejected = grounded_notes({"event_id":"e"},batch,{"notes":proposals})
        self.assertFalse(notes)
        self.assertEqual(sum(rejected.values()),3)


if __name__ == "__main__":
    unittest.main()
