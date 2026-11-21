from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from certa.claim_models import ClaimModels
from certa.group_events import timestamp, write_jsonl
from certa.luna import ModelError
from certa.official_releases import DEFAULT_PACK, ReleaseIndex, discover, ons_cells
from certa.trust_briefing import compose, html_view, validate_script
from certa.verify import verify


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

    def test_broad_event_checks_late_context_and_preserves_all_approved_claims(self):
        statements = [
            ("Acme opened a new computing centre.", "Acme launched a computing facility."),
            ("Acme was founded as a family business.", "Acme began as a family enterprise."),
            ("The system works because redundant servers maintain service.", "Redundant servers keep the system running."),
            ("Acme's expansion affects hospitals using the service.", "Hospitals using Acme's service are affected by the expansion."),
            ("The operator responded in a statement confirming the launch.", "The operator confirmed the opening in its response."),
        ]
        filler = " ".join("Routine operational updates were included in the report." for _ in range(20))
        body = statements[0][0] + " " + filler + " " + " ".join(s for s, _ in statements[1:])

        def transport(payload):
            data = json.loads(payload["input"])
            stage = payload["text"]["format"]["name"]
            if stage == "extract_claims":
                claims = []
                for source, paraphrase in statements:
                    indexes = [i for i, p in enumerate(data["excerpts"]) if source in p["quote"]]
                    if indexes:
                        claims.append({"kind": "reported_fact", "wording": paraphrase, "refs": indexes[:1],
                                       "geo": "", "measure": "", "period": "", "basis": "", "value": ""})
                return response({"claims": claims[:3]})
            if stage == "overview_claims":
                return response({"items": [{"claim_id": c["id"], "independent_firsthand_sources": [],
                                             "nl": "", "de": ""} for c in data["approved"]]})
            if stage == "event_review_claims":
                return response({"issues": []})
            original = next(s for s, paraphrase in statements if paraphrase == data["claim"])
            indexes = [i for i, p in enumerate(data["excerpts"]) if original in p["quote"]]
            return response({"decision": "supported", "support": indexes, "contradict": [], "reason": "direct_evidence"})

        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snap = self.verify([article("a", body)], models=service, model_events=1, model_overviews=True)
        event = snap["events"][0]
        approved = {c["id"] for c in event["claims"] if c["approved"]}
        self.assertEqual(len(approved), len(statements))
        self.assertTrue(any("family enterprise" in c["wording"] and c["approved"] for c in event["claims"]))
        self.assertEqual(set(event["overview_claim_ids"]), approved)
        self.assertTrue(any(p["start"] > len(filler) for p in event["examined_passages"]))
        from certa.categorize import run as categorize
        from certa.overview import build
        from certa.overview_reader import connect, get_event
        from certa.editions import personal_draft
        from certa.topic_rules import TOPICS
        categories, verified, catalogue = (self.root / name for name in ("categories.jsonl", "verified.json", "events.db"))
        categorize(self.feeds, categories)
        verified.write_text(json.dumps(snap), encoding="utf-8")
        build(verified, self.feeds, categories, catalogue)
        with closing(connect(catalogue)) as db:
            stored = get_event(db, event["event_id"])
            self.assertEqual({i["id"] for i in stored["items"] if i["draft_use"] == "approved_wording"}, approved)
            self.assertGreater(stored["overview_coverage"]["background"]["available_passages"], 0)
        profile = {"version": 1, "topics": list(TOPICS), "language": "en", "region": None,
                   "minutes": 3, "depth": "headlines", "weights": {}}
        brief = personal_draft(catalogue, profile, "2026-11-19", {})
        detailed = personal_draft(catalogue, {**profile, "depth": "detailed"}, "2026-11-19", {})
        self.assertEqual(len(brief["events"][0]["claims"]), 1)
        self.assertEqual(len(detailed["events"][0]["claims"]), len(statements))
        self.assertEqual(brief["events"][0]["revision"], detailed["events"][0]["revision"])

    def test_reported_numbers_require_exact_value_scale_and_official_routing(self):
        from certa.verify import reported_number_anchors
        evidence = [{"quote": "Acme reported Q3 revenue of $3 million in 2026."}]
        self.assertTrue(reported_number_anchors("Acme's Q3 revenue was $3 million in 2026.", evidence))
        for wording in ("Acme's revenue was $4 million.", "Acme's revenue was $3 billion.",
                        "Acme's revenue was €3 million.", "UK CPI was 3%.",
                        "Acme reported $3 million and marking one miss in five years."):
            with self.subTest(wording=wording):
                self.assertFalse(reported_number_anchors(wording, evidence))

    def test_qualified_context_is_publishable_with_explicit_kind_and_attribution(self):
        from certa.trust_briefing import spoken
        cases = [
            ("forecast", "Acme expects revenue could reach $3 million.",
             "Acme expects revenue may reach $3 million.", True),
            ("allegation", "A lawsuit alleges Acme concealed defects.",
             "The lawsuit alleges Acme concealed defects.", True),
            ("analysis", "Analysts believe the redesign improves flexibility.",
             "Analysts believe the redesign improves adaptability.", True),
            ("forecast", "Acme expects revenue could reach $3 million.",
             "Acme revenue reaches $3 million.", False),
            ("analysis", "Analysts suggest buying Acme shares.",
             "Analysts suggest buying Acme shares.", False),
        ]
        for index, (kind, source, wording, approved) in enumerate(cases):
            def transport(payload):
                if payload["text"]["format"]["name"] == "extract_claims":
                    return response({"claims": [{"kind": kind, "wording": wording, "refs": [0],
                        "geo": "", "measure": "", "period": "", "basis": "", "value": ""}]})
                return response({"decision": "supported", "support": [0], "contradict": [], "reason": "direct_evidence"})
            with self.subTest(kind=kind, wording=wording):
                models = ClaimModels(self.db, "small", "strong", transport=transport)
                self.db.execute("DELETE FROM claim_decision")
                snap = self.verify([article(str(index), source)], models=models, model_events=1)
                matching = [c for c in snap["events"][0]["claims"] if c["kind"] == kind]
                self.assertEqual(any(c["approved"] for c in matching), approved)
                if approved:
                    claim = matching[0]
                    self.assertIn("Example Press reports", spoken(claim, "en"))
                    self.assertIn(kind, spoken(claim, "en"))

    def test_corroboration_requires_distinct_firsthand_reporting_origins(self):
        rows = [article("a", "Our reporter observed Acme open a new plant."),
                article("b", "Our correspondent witnessed Acme opening a new factory.")]
        rows[1]["publication"]["name"] = "Independent Press"
        groups = self.root / "groups.jsonl"

        def transport(payload):
            data = json.loads(payload["input"])
            stage = payload["text"]["format"]["name"]
            refs = list(range(len(data["excerpts"])))
            if stage == "extract_claims":
                return response({"claims": [{"kind": "reported_fact", "wording":
                    "Acme opened a facility, according to reports.", "refs": refs,
                    "geo": "", "measure": "", "period": "", "basis": "", "value": ""}]})
            if stage == "overview_claims":
                return response({"items": [{"claim_id": c["id"], "independent_firsthand_sources": c["refs"],
                                             "nl": "", "de": ""} for c in data["approved"]]})
            return response({"decision": "supported", "support": refs, "contradict": [], "reason": "direct_evidence"})

        for origins, expected in [(["one", "two"], "corroborated"), (["copy", "copy"], "supported")]:
            with self.subTest(origins=origins):
                write_jsonl(groups, [{"event_id": "event", "status": "grouped", "sources": [
                    {"article_id": r["$id"], "reporting_origin_id": o} for r, o in zip(rows, origins)]}])
                models = ClaimModels(self.db, "small", "strong", transport=transport)
                snap = self.verify(rows, models=models, model_events=1, model_overviews=True, events=groups)
                claim = next(c for c in snap["events"][0]["claims"] if c["approved"])
                self.assertEqual(claim.get("evidence_state", claim["article_state"]), expected)

    def test_source_review_cannot_add_causality_basis_or_remove_uncertainty(self):
        from certa.verify import prose_anchors
        for source, claim in [
            ("Chemical prices rose 3.9%.", "Chemical prices rose 3.9% annually."),
            ("The resignation has not ended inquiries.", "The resignation prompted inquiries."),
            ("Clothing prices rose alongside shipping costs.", "Clothing prices rose because of shipping costs."),
            ("The agency attributed part of the increase to fuel.", "The agency attributed the increase to fuel."),
            ("Acme is scrambling to integrate the system.", "Acme is integrating the system."),
            ("Follow the inflation report on our Telegram channel.", "The channel published the inflation report."),
            ("Speaking to a broadcaster, he said he expected the board to investigate.", "The board is expected to investigate."),
            ("Canada CPI: March largely priced. The outlook presents a challenge for markets.", "March CPI data was largely priced in by markets."),
            ("The move made SpaceX its largest investment, ahead of its remaining Intel position.", "SpaceX became Intel's largest investment."),
            ('Where relevant, we reviewed the matter, Acme said.', 'Acme reviewed the matter.'),
            ('Recent awards from Acme and the government extend production.',
             'Acme secured recent awards from the government.'),
            ('Dingus apologised to the teenager, his family and the court.',
             'Dingus apologized to the teenager, her family and the court.'),
            ('The footage shows Acme staff smelling the samples.',
             'The footage shows Acme staff entering a room and picking up the samples.'),
            ('The contracts cover infrastructure in the Big Bend sector.',
             'The US Border Patrol awarded contracts in the Big Bend sector.'),
            ('ETH stays below $1,800 as analysts target $1,500.',
             'Analysts predict ETH will remain below $1,800 with a target of $1,500.'),
            ('Fidelity estimates $185,500 in retirement health expenses before long-term care.',
             'Fidelity estimates $185,500 in retirement health expenses prior to long-term care needs.'),
        ]:
            with self.subTest(source=source):
                self.assertFalse(prose_anchors(claim, [{"language": "en", "quote": source}]))
        self.assertTrue(prose_anchors("Acme attributed part of the increase to fuel.",
                                     [{"language": "en", "quote": "Acme attributed part of the increase to fuel costs."}]))

    def test_malformed_extraction_batch_retries_each_passage_without_losing_detail(self):
        paraphrases = {"Acme opened a new factory.": "Acme launched a new plant.",
                      "Acme was founded as a family business.": "Acme began as a family enterprise."}

        def transport(payload):
            data = json.loads(payload["input"])
            if payload["model"] == "small":
                if len(data["excerpts"]) > 1:
                    return response({"claims": "malformed batch"})
                return response({"claims": [{"kind": "reported_fact", "refs": [0],
                    "wording": paraphrases[data["excerpts"][0]["quote"]], "geo": "", "measure": "",
                    "period": "", "basis": "", "value": ""}]})
            return response({"decision": "supported", "support": [0], "contradict": [], "reason": "direct_evidence"})

        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snapshot = self.verify([article("a", " ".join(paraphrases))], models=service, model_events=1)
        self.assertEqual(snapshot["summary"]["approved"], 2)
        self.assertEqual(len(snapshot["events"][0]["examined_passages"]), 2)
        self.assertEqual(service.usage["extract"]["batch_retries"], 1)
        self.assertEqual(service.usage["extract"]["calls"], 3)
        replay = ClaimModels(self.db, "small", "strong", transport=transport)
        again = self.verify([article("a", " ".join(paraphrases))], models=replay, model_events=1)
        self.assertEqual(again["events"], snapshot["events"])
        self.assertEqual(replay.usage["extract"]["calls"], 0)
        self.assertEqual(replay.usage["review"]["calls"], 0)

    def test_overview_editor_cannot_discard_checked_event_context(self):
        service = ClaimModels(self.db, "small", "strong", transport=lambda _: response({
            "items": [{"claim_id": "c1", "independent_firsthand_sources": [], "nl": "", "de": ""}]}))
        with self.assertRaisesRegex(ModelError, "omitted checked event detail"):
            service.call("overview", {"excerpts": [{"id": 0}], "approved": [
                {"id": "c1", "refs": [0]}, {"id": "c2", "refs": [0]}]})

    def test_failed_translation_preserves_checked_english_and_other_languages(self):
        def transport(payload):
            data = json.loads(payload["input"])
            stage = payload["text"]["format"]["name"]
            if stage == "extract_claims":
                return response({"claims": [{"kind": "reported_fact", "wording": "Acme opened a plant.",
                    "refs": [0], "geo": "", "measure": "", "period": "", "basis": "", "value": ""}]})
            if stage == "overview_claims":
                return response({"items": [{"claim_id": "c1", "independent_firsthand_sources": [],
                    "nl": "Acme heeft een fabriek geopend.", "de": "Acme hat ein Werk eröffnet."}]})
            return response({"decision": "supported", "support": [] if data.get("target_language") == "nl" else [0],
                             "contradict": [], "reason": "direct_evidence"})

        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snapshot = self.verify([article("a", "Acme has launched a new manufacturing plant.")],
                               models=service, model_events=1, model_overviews=True)
        claim = snapshot["events"][0]["claims"][0]
        self.assertTrue(claim["approved"])
        self.assertNotIn("nl", claim.get("translations", {}))
        self.assertIn("de", claim["translations"])
        self.assertIn("nl", claim["translation_failures"])
        self.assertEqual(snapshot["summary"]["translation_failures"], 1)

    def test_event_wide_review_holds_conflicting_timelines_after_individual_passes(self):
        events = self.root / "events.jsonl"
        write_jsonl(events, [{"event_id": "acme", "status": "grouped", "sources": [
            {"article_id": aid, "reporting_origin_id": aid} for aid in ("a", "b")]}])

        def transport(payload):
            stage = payload["text"]["format"]["name"]
            data = json.loads(payload["input"])
            if stage == "extract_claims":
                base = {"kind": "reported_fact", "geo": "", "measure": "", "period": "", "basis": "", "value": ""}
                return response({"claims": [{**base, "wording": "Acme closed the accounts in 2018.", "refs": [0]},
                                            {**base, "wording": "Acme accounts remained active in 2019.", "refs": [1]}]})
            if stage == "event_review_claims":
                return response({"issues": [{"claim_ids": ["c1", "c2"], "evidence": [0, 1],
                                             "reason": "conflicting_timing"}]})
            return response({"decision": "supported", "support": [0] if "2018" in data["claim"] else [1],
                             "contradict": [], "reason": "direct_evidence"})

        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snapshot = self.verify([article("a", "Acme closed the accounts in 2018."),
                                article("b", "Acme accounts remained active in 2019.")],
                               events=events, models=service, model_events=1, model_overviews=True)
        self.assertEqual(snapshot["summary"]["approved"], 0)
        self.assertTrue(all(c["article_state"] == "disputed" for c in snapshot["events"][0]["claims"]))
        self.assertEqual(len(snapshot["events"][0]["event_review"]["issues"][0]["evidence_refs"]), 2)

    def test_large_model_cannot_override_a_wrong_official_figure(self):
        def transport(payload):
            if payload["model"] == "small":
                return response({"claims":[]})
            return response({"decision":"supported","support":[0],"contradict":[],"reason":"direct_evidence"})
        service = ClaimModels(self.db, "small", "strong", transport=transport)
        snap = self.verify([article("a", LEAD.replace("3.6", "3.8"))], models=service, model_events=1)
        self.assertFalse(snap["events"][0]["claims"][0]["approved"])
        self.assertEqual(service.usage["review"]["calls"], 1)

    def test_model_agreement_cannot_invent_actor_direction_or_numeric_scope(self):
        base = {"kind":"reported_fact","refs":[0],"geo":"","measure":"","period":"","basis":"","value":""}
        def transport(payload):
            if payload["model"] == "small":
                return response({"claims":[{**base,"wording":"The user received the report yesterday."},
                                           {**base,"wording":"Futures dropped after prices increased."},
                                           {**base,"kind":"official_figure","wording":"","geo":"GB","measure":"CPI",
                                            "basis":"yoy","period":"2026-10","value":"3.6"}]})
            return response({"decision":"supported","support":[0],"contradict":[],"reason":"direct_evidence"})
        models = ClaimModels(self.db,"small","large",transport=transport)
        snap = self.verify([article("a","Futures fell after the release of the report. Canadian CPI measured 3.6% in September.")],
                           models=models,model_events=1)
        self.assertEqual(snap["summary"]["approved"],0)

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
        self.assertEqual(snap["events"][0]["claims"][0]["official_state"], "not_checked")
        self.assertIn("Example Press", compose(snap, "headlines", "en")["segments"][0]["text"])


if __name__ == "__main__":
    unittest.main()
