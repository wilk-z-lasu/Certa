from datetime import date
import os
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from build_preai import approved_claim
from generate_script import compose_draft, framed_segments, ScriptError
from voxnews import providers
from voxnews.cloud_embeddings import CloudEncoder
from voxnews.category_review import CategoryReview
from voxnews.claim_models import ClaimModels
from voxnews.luna import RequestsPaused, send_request
from voxnews.daily import prepare
from voxnews.event_embeddings import E5Encoder
from voxnews.trust_briefing import spoken_figure


def cloud_event():
    return {"event_id":"e", "revision":"r", "model_status":"reviewed",
            "processing": {k:"openai" for k in ("provider","embedding_provider","grouping_provider")},
            "model_versions": {stage:{"provider":"openai"} for stage in
                               ("extract","review","event_review","overview","translation")}}


class CloudDemoTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"VOXNEWS_PROVIDER":"openai", "VOXNEWS_CLOUD_ONLY":"1"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_local_inference_and_local_embeddings_are_disabled(self):
        with self.assertRaisesRegex(ValueError, "disabled"):
            providers.local_request({})
        with self.assertRaisesRegex(ValueError, "disabled"):
            E5Encoder(Path("unused"))([])
        with patch.dict(os.environ, {"VOXNEWS_PROVIDER":"ollama"}):
            with self.assertRaisesRegex(ValueError, "requires"):
                providers.local()

    def test_local_cached_events_cannot_supply_claims_or_composition(self):
        event = cloud_event()
        self.assertTrue(providers.cloud_event(event))
        event["processing"]["embedding_provider"] = "local"
        self.assertFalse(providers.cloud_event(event))
        self.assertIsNone(approved_claim({}, event, "en", None))
        with patch("generate_script.request_script") as writer:
            with self.assertRaisesRegex(ScriptError, "cloud-generated"):
                compose_draft({"events":[{**event,"claims":[]}]}, {})
            writer.assert_not_called()

    def test_missing_key_never_uses_offline_fallback(self):
        draft = {"events":[{**cloud_event(),"claims":[{"claim_id":"c","text":"A checked statement.","sources":[]}]}]}
        with patch("generate_script.api_key", return_value=None), patch("generate_script.request_script") as writer:
            with self.assertRaisesRegex(ScriptError, "OPENAI_API_KEY"):
                compose_draft(draft, {})
            writer.assert_not_called()
        with TemporaryDirectory() as temp:
            output = Path(temp)/"not-created"
            with self.assertRaisesRegex(ValueError, "Rules-only"):
                prepare(Path(temp), output, date(2026,11,19), 7, offline=True)
            self.assertFalse(output.exists())

    def test_credit_pause_blocks_new_requests_but_keeps_cached_results(self):
        with patch.dict(os.environ,{"VOXNEWS_API_REQUESTS_PAUSED":"1"}), \
                patch("voxnews.luna.urlopen") as network:
            with self.assertRaises(RequestsPaused):
                send_request({})
            with self.assertRaisesRegex(ScriptError,"paused"):
                from generate_script import request_script
                request_script({}, {}, "unused")
            with self.assertRaisesRegex(ValueError,"paused"):
                CloudEncoder(Path("unused")).request(["unused"])
            with sqlite3.connect(":memory:") as db:
                transport=Mock()
                model=ClaimModels(db,"gpt-6-luna","gpt-6.2-astra",transport=transport)
                with self.assertRaises(RequestsPaused):
                    model.call("extract",{"excerpts":[]})
                self.assertEqual(model.usage["extract"]["calls"],0)
                self.assertEqual(model.usage["extract"]["budget_holds"],1)
                transport.assert_not_called()
            network.assert_not_called()

    def test_cloud_embedding_cache_indexes_and_normalization(self):
        vector = [3.,4.] + [0.]*382
        transport = Mock(return_value={"data":[{"index":1,"embedding":vector}, {"index":0,"embedding":vector}],
                                       "usage":{"prompt_tokens":12}})
        articles = [SimpleNamespace(headline="Story "+str(i),excerpt="Context") for i in range(2)]
        with TemporaryDirectory() as temp:
            path=Path(temp)/"embeddings.sqlite3"
            encoder=CloudEncoder(path,transport=transport)
            values=encoder(articles)
            self.assertEqual(values.shape,(2,384))
            self.assertAlmostEqual(float(values[0,0]),0.6)
            self.assertAlmostEqual(float(values[0,1]),0.8)
            self.assertEqual(encoder.usage["input_tokens"],12)
            replay=CloudEncoder(path,transport=transport)
            replay(articles)
            self.assertEqual(replay.usage["cache_hits"],2)
            self.assertEqual(transport.call_count,1)

    def test_invalid_cloud_embedding_response_is_not_cached(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"embeddings.sqlite3"
            encoder=CloudEncoder(path, transport=lambda _: {"data":[{"index":4,"embedding":[1.]*384}],"usage":{"prompt_tokens":1}})
            with self.assertRaisesRegex(ValueError, "indexes"):
                encoder([SimpleNamespace(headline="Story",excerpt="Context")])
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM embedding").fetchone()[0],0)

    def test_cloud_classifier_reserves_its_small_budget_for_json(self):
        output={"status":"completed","usage":{"input_tokens":20,"output_tokens":6},
                "output":[{"content":[{"text":json.dumps({"ids":[0]})}]}]}
        transport=Mock(return_value=output)
        record={"needs_review":True,"topics":["other_news"],"regions":["unknown"],
                "evidence":{"topics":{"other_news":[]},"regions":{}}}
        option={"facet":"topics","label":"technology_ai","quote":"An AI system.","start":0,"end":13}
        with sqlite3.connect(":memory:") as db, patch("voxnews.category_review.candidates",return_value=[option]):
            model=CategoryReview(db,transport=transport)
            result=model.apply({},record)
            self.assertEqual(result["topics"],["technology_ai"])
            self.assertEqual(transport.call_args.args[0]["reasoning"],{"effort":"none"})

    def test_inflation_measures_and_publication_dates_are_explicit(self):
        fact={"geo":"GB","measure":"CPI","period":"2026-10","basis":"yoy","value":"3.6","unit":"%"}
        headline=spoken_figure(fact,"en",version=2)
        core=spoken_figure({**fact,"measure":"core CPI","value":"2.8"},"en",version=2)
        self.assertIn("headline",headline)
        self.assertIn("all CPI items",headline)
        self.assertIn("excluding energy, food, alcohol and tobacco",core)
        self.assertIn("October 2026",headline)
        self.assertIn("October 2026",core)
        self.assertNotIn("headline",spoken_figure(fact,"en",version=1))
        draft={"date":"2026-11-19","selection":{"language":"en","region":None},"coverage":{"sparse":False},
               "events":[{"event_id":"e","latest":"2026-11-16T12:00:00Z","development":"new_to_listener"}]}
        claims=[{"event_id":"e","revision":"r","local":False,"text":headline,"reported_on":"2026-11-16"}]
        old=" ".join(b["text"] for b in framed_segments(draft,claims,version=1))
        new=" ".join(b["text"] for b in framed_segments(draft,claims,version=2))
        self.assertIn("From 2026-11-16.",old)
        self.assertIn("Reporting published on 16 November 2026.",new)
        self.assertIn("Your briefing for 19 November 2026.",new)
        self.assertIn("October 2026",new)
