from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from voxnews.claim_models import ClaimModels
from voxnews.group_events import timestamp, write_jsonl
from voxnews.luna import ModelError
from voxnews.official_releases import DEFAULT_PACK, ReleaseIndex, discover, ons_cells
from voxnews.trust_briefing import compose, html_view, validate_script
from voxnews.verify import verify


CUTOFF = timestamp("2026-11-20", allow_date=True)
LEAD = "UK annual CPI was 3.6% in October 2026."


def article(aid, body, *, when="2026-11-18T12:00:00Z", language="en"):
    return {"$id": aid, "headline": "Price data", "date": when, "permalink": f"https://example.org/{aid}",
            "language": language, "text_content": body, "publication": {"name": "Example Press"}}


def response(data):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps(data)}]}], "usage": {"input_tokens": 100, "output_tokens": 20}}


class VerificationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.feeds = self.root / "feeds"
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def verify(self, rows, **kwargs):
        write_jsonl(self.feeds / "source.jsonl", rows)
        return verify(self.feeds, kwargs.pop("before", CUTOFF), self.db, **kwargs)

    def test_wrong_basis_measure_forecast_and_prior_period_fail(self):
        for line, expected in [
            (LEAD, True), ("UK monthly CPI was 3.6% in October 2026.", False),
            ("UK annual CPIH was 3.6% in October 2026.", False),
            ("UK annual CPI was 3.6% in September 2026.", False),
            ("UK annual CPI is expected to be 3.6% in October 2026.", False),
            ("Will UK annual CPI rise to 3.6% in October 2026?", False),
            ("UK annual CPI was 3.6 percentage points in October 2026.", False),
            ("UK CPI was 3.6% in October 2026.", False),
        ]:
            with self.subTest(line=line):
                snap = self.verify([article("a", line)])
                self.assertEqual(bool(snap["summary"]["approved"]), expected)

    def test_followup_context_and_raw_unicode_offsets(self):
        body = "Résumé. " + LEAD + " Monthly CPI rose 0.5%, compared with a prior estimate."
        event = self.verify([article("a", body)])["events"][0]
        self.assertEqual(len(event["claims"]), 2)
        ref = event["claims"][1]["support"][0]
        self.assertEqual(body[ref["start"]:ref["end"]], "Monthly CPI rose 0.5%")
        self.assertEqual(body[slice(*ref["context_span"])], LEAD[:-1])
        interrupted = LEAD + " Dutch prices also changed. Monthly CPI rose 0.5%."
        self.assertEqual(self.verify([article("a", interrupted)])["summary"]["approved"], 1)

    def test_conflict_across_sources_holds_both_and_keeps_proof(self):
        snap = self.verify([article("a", LEAD), article("b", LEAD.replace("3.6", "3.7"))])
        self.assertEqual(snap["summary"]["approved"], 0)
        for event in snap["events"]:
            c = event["claims"][0]
            self.assertEqual(c["article_state"], "disputed")
            self.assertNotEqual(c["support"][0]["article_id"], c["contradict"][0]["article_id"])
        self.assertFalse(compose(snap, "rates", "en")["segments"])

    def test_time_cutoff_previews_and_official_revisions(self):
        early = article("early", LEAD, when="2026-11-18T06:55:00Z")
        later = article("later", LEAD)
        snap = self.verify([early, later], before=timestamp("2026-11-18T07:00:00Z"))
        self.assertEqual(snap["summary"]["articles_in_window"], 1)
        self.assertEqual(snap["events"][0]["claims"][0]["official_state"], "missing")
        snap = self.verify([early])
        self.assertEqual(snap["events"][0]["claims"][0]["official_state"], "no_contemporary_release")
        row = json.loads(DEFAULT_PACK.read_text(encoding="utf-8").splitlines()[0])
        corrected = {**row, "available_at": "2026-11-19T08:00:00Z", "vintage": "corrected",
                     "cells": [["GB", "CPI", "2026-10", "yoy", "3.7", "Corrected row"]]}
        pack = self.root / "release.jsonl"
        write_jsonl(pack, [row, corrected])
        newer = article("new", LEAD.replace("3.6", "3.7"), when="2026-11-19T09:00:00Z")
        snap = self.verify([later, newer], packs=[pack])
        states = {e["sources"][0]["article_id"]: e["claims"][0] for e in snap["events"]}
        self.assertEqual(states["later"]["official_state"], "revised_since_reporting")
        self.assertTrue(states["new"]["approved"])
        self.assertFalse(ReleaseIndex([pack], CUTOFF).lookup(("GB", "CPI", "2026-10", "mom")))
        write_jsonl(pack, [{**row, "vintage": "flash"}])
        self.assertEqual(self.verify([later], packs=[pack])["events"][0]["claims"][0]["official_state"], "preliminary_only")

    def test_multilingual_region_decimals_and_translations_share_one_origin(self):
        de = article("de", "Die deutsche VPI lag im Oktober 2026 jährlich bei 2,8 Prozent.", language="de",
                     when="2026-11-19T08:00:00Z")
        nl = article("nl", "De Nederlandse CPI bedroeg in oktober 2026 op jaarbasis 3,7 procent.", language="nl")
        en = article("en", "Dutch annual CPI was 3.7% in October 2026.")
        events = self.root / "events.jsonl"
        write_jsonl(events, [{"event_id": "d", "status": "singleton", "sources": [{"article_id": "de", "reporting_origin_id": "a"}]},
                             {"event_id": "n", "status": "grouped", "sources": [{"article_id": aid, "reporting_origin_id": "b"}
                                                                                for aid in ("nl", "en")]}])
        snap = self.verify([de, nl, en], events=events)
        self.assertEqual(snap["summary"]["approved"], 2)
        self.assertEqual(len(snap["events"][1]["claims"][0]["support"]), 2)
        self.assertEqual(snap["summary"]["reporting_origins"], 2)
        spoken = compose(snap, "rates", "nl", "NL")["segments"]
        self.assertEqual(len(spoken), 1)
        self.assertIn("3,7 procent op jaarbasis", spoken[0]["text"])
        self.assertIn("2,8 Prozent", compose(snap, "rates", "de", "DE")["segments"][0]["text"])

    def test_official_import_read_named_columns_and_carry_year(self):
        csv = ('Table 1\n\n,,CPI 1-month rate (%),"CPIH 12-\nmonth rate (%)",CPI 12-month rate (%),CPIH 1-month rate (%)\n'
               '2026,Sep,0.4,3.6,3.5,0.4\n,Oct,0.5,3.7,3.6,0.5\n')
        data = {tuple(r[:4]): r[4] for r in ons_cells(csv.encode())}
        self.assertEqual(data[("GB", "CPI", "2026-10", "yoy")], "3.6")
        self.assertEqual(data[("GB", "CPIH", "2026-10", "yoy")], "3.7")
        with self.assertRaises(ValueError):
            ons_cells(csv.replace("CPI 12-month rate", "RPI 12-month rate").encode())
        row = json.loads(DEFAULT_PACK.read_text(encoding="utf-8").splitlines()[0])
        for changes in [{"url": "https://www.ons.gov.uk.example.com/pretend"}, {"issuer": "CBS"}]:
            pack = self.root / "release.jsonl"
            write_jsonl(pack, [{**row, **changes}])
            with self.assertRaises(ValueError):
                ReleaseIndex([pack], CUTOFF)

    def test_feed_discovery_validates_issuer_and_dutch_timestamp(self):
        item = ("<item><title>Nieuwe cijfers</title><link>https://www.cbs.nl/nl-nl/nieuws/test</link>"
                "<pubDate>Thu, 19 Nov 2026 06:30:00 +01:00</pubDate></item>")
        xml = ("<rss><channel>" + item + item.replace("www.cbs.nl", "unknown.example") + "</channel></rss>").encode()
        leads = discover(xml, "CBS", timestamp("2026-11-19", allow_date=True), CUTOFF, "cijfers")
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["feed_timestamp"], "2026-11-19T05:30:00+00:00")

    def test_advice_and_forecasts_are_withheld_even_with_a_matching_number(self):
        def transport(payload):
            self.assertEqual(payload["model"], "small")
            base = {"refs":[0], "wording":"A projection for UK inflation.", "geo":"GB", "measure":"CPI",
                    "period":"2026-10", "basis":"yoy", "value":"3.6"}
            return response({"claims":[{**base,"kind":"forecast"},{**base,"kind":"advice"}]})
        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snap = self.verify([article("a", "Analysts had expected UK annual CPI to reach 3.6% in October 2026.")],
                           models=service, model_events=1)
        self.assertEqual(snap["summary"]["approved"], 0)
        self.assertEqual(service.usage["review"]["calls"], 0)

    def test_literal_gate_rejects_composition_drift_and_reuses_cache(self):
        rows = [article("a", LEAD), article("b", "The Bank of England raised Bank Rate to 4% on November 5.")]
        snap = self.verify(rows)
        again = self.verify(rows)
        self.assertEqual(again["events"], snap["events"])
        self.assertEqual(again["summary"]["rule_cache_hits"], 2)
        script = compose(snap, "rates", "en")
        self.assertEqual(len(script["segments"]), 2)
        self.assertIn("Bank Rate", script["segments"][0]["text"])
        html = html_view(script)
        self.assertIn("https://example.org/a", html)
        self.assertIn("CPI 12-month rate", html)
        for changes in ("3.6 percent monthly", "You should buy bonds"):
            edited = deepcopy(script)
            edited["segments"][1]["text"] = changes
            with self.assertRaises(ValueError):
                validate_script(edited, snap)
        snap["events"][0]["claims"][0]["support"][0]["permalink"] = "https://example.org/wrong"
        with self.assertRaisesRegex(ValueError, "saved verification revision"):
            compose(snap, "rates", "en")

    def test_model_route_reviews_ambiguous_claim_caches_and_meters(self):
        calls = []
        candidate = {"kind":"official_figure", "refs":[0], "wording":"A UK inflation reading.",
                     "geo":"GB", "measure":"CPI", "period":"2026-10", "basis":"yoy", "value":"3.6"}
        def transport(payload):
            calls.append(payload)
            self.assertFalse(payload["store"])
            if payload["model"] == "small":
                return response({"claims":[candidate]})
            return response({"decision":"supported","support":[0],"contradict":[],"reason":"direct_evidence"})
        prices = {name: {"input": 1, "cached": 0.1, "output": 5} for name in ["small", "strong"]}
        service = ClaimModels(self.db, "small", "strong", transport=transport, prices=prices)
        body = "In October 2026, UK CPI measured on a year-on-year basis registered 3.6%."
        snap = self.verify([article("a", body)], models=service, model_events=1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(snap["events"][0]["claims"][0]["approved"])
        self.assertAlmostEqual(snap["summary"]["verification_model_cost_usd"], .0004)
        again = self.verify([article("a", body)], models=ClaimModels(self.db,"small","strong",transport=transport), model_events=1)
        self.assertEqual(snap["events"], again["events"])
        self.assertEqual(again["summary"]["verification_model_cost_usd"], 0)
        self.assertEqual(len(calls), 2)
        bad = ClaimModels(self.db, "invalid", "strong", transport=lambda _: response({"claims":[{**candidate, "refs":[9]}]}))
        with self.assertRaises(ModelError):
            self.verify([article("a", body)], models=bad, model_events=1)

    def test_large_model_cannot_override_a_wrong_official_figure(self):
        def transport(payload):
            if payload["model"] == "small":
                return response({"claims":[]})
            return response({"decision":"supported","support":[0],"contradict":[],"reason":"direct_evidence"})
        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snap = self.verify([article("a", LEAD.replace("3.6", "3.8"))], models=service, model_events=1)
        self.assertFalse(snap["events"][0]["claims"][0]["approved"])
        self.assertEqual(service.usage["review"]["calls"], 1)

    def test_attributed_nonnumeric_reporting_and_misclassified_advice(self):
        def transport(payload):
            if payload["model"] == "small":
                base = {"kind":"reported_fact","refs":[0],"geo":"","measure":"","period":"","basis":"","value":""}
                return response({"claims":[{**base,"wording":"The rail operator cancelled the strike."},
                                           {**base,"wording":"Investors should buy the rail operator."}]})
            return response({"decision":"supported","support":[0],"contradict":[],"reason":"direct_evidence"})
        m = ClaimModels(self.db, "small", "strong", transport=transport)
        snap = self.verify([article("a", "The railway company announced its planned strike had been called off.")],
                           models=m, model_events=1)
        self.assertEqual(m.usage["review"]["calls"], 1)
        self.assertEqual(snap["summary"]["approved"], 1)
        self.assertIn("Example Press", compose(snap, "headlines", "en")["segments"][0]["text"])


if __name__ == "__main__":
    unittest.main()
