from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

try:
    import numpy as np
except ImportError:
    np = None

from voxnews.event_candidates import Article, CandidateIndex, reporting_origins
from voxnews.event_groups import form_groups
from voxnews.group_events import run
from voxnews.luna import Decision, LunaJudge, ModelError


def fixture(article_id, headline, day="2026-11-13", hour="12:00", **extra):
    return {
        "$id": article_id, "headline": headline, "language": "en",
        "date": f"{day}T{hour}:00+00:00",
        "permalink": f"https://example.com/{article_id}",
        **extra,
    }


def label(row, topics=("companies_stocks",)):
    return {
        "article_id": row["$id"], "permalink": row["permalink"], "language": row["language"],
        "topics": list(topics), "regions": ["US"],
    }


def article(row, feed="example"):
    return Article.from_source(row, label(row), feed, datetime.fromisoformat(row["date"]))


def identical_vectors(articles):
    return np.ones((len(articles), 1), dtype=np.float32)


def fake_response(payload, decision="same_event", reason="matching_occurrence"):
    pairs = json.loads(payload["input"])
    data = {"decisions": [
        {"pair_id": pair["pair_id"], "decision": decision, "reason": reason, "features": ["event_types"]}
        for pair in pairs
    ]}
    return {
        "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(data)},
        ]}],
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


@unittest.skipUnless(np is not None, "install requirements-events.txt for the grouping tests")
class CandidateTests(unittest.TestCase):
    def test_different_reporting_periods_are_excluded(self):
        articles = [
            article(fixture("a", "US producer prices for September")),
            article(fixture("b", "US wholesale inflation for October")),
            article(fixture("c", "October PPI figures", day="2026-11-18")),
            article(fixture("d", "A related market briefing", day="2026-11-18")),
        ]
        index = CandidateIndex(articles, identical_vectors(articles))
        candidates = index.shortlist(list(range(4)))
        self.assertIn((1, 2), candidates)
        self.assertNotIn((0, 1), candidates)
        self.assertNotIn((0, 2), candidates)
        self.assertNotIn((1, 3), candidates)

    def test_matching_mentioned_date_and_actor_extend_window(self):
        articles = [
            article(fixture("a", "Intel lawsuit filed November 13")),
            article(fixture("b", "Allegations in Intel lawsuit filed 13 November", day="2026-11-18")),
            article(fixture("c", "Intel lawsuit filed November 18", day="2026-11-18")),
        ]
        index = CandidateIndex(articles, identical_vectors(articles))
        candidates = index.shortlist(list(range(3)))
        self.assertIn((0, 1), candidates)
        self.assertNotIn((0, 2), candidates)

    def test_copy_and_translation_share_origin_but_ambiguous_match_is_flagged(self):
        articles = [
            article(fixture("a", "Intel lawsuit", source="Reporter One", text_content="A unique report"), "invezz_en"),
            article(fixture("copy", "A copied headline", text_content="A  unique REPORT")),
            article(fixture("de", "Klage gegen Intel", hour="12:04", language="de", source="Reporter One"), "invezz_de"),
            article(fixture("b", "Intel sued again", source="Reporter One", hour="12:05"), "invezz_en"),
            article(fixture("nl", "Rechtszaak tegen Intel", hour="12:06", language="nl", source="Reporter One"), "invezz_nl"),
        ]
        vectors = np.array([[1, 0], [1, 0], [1, 0], [0.6, 0.8], [0.8944, 0.4472]])
        groups, review = reporting_origins(articles, CandidateIndex(articles, vectors))
        self.assertEqual(groups, {0: [0, 1, 2], 3: [3], 4: [4]})
        self.assertEqual(review, {4})

    def test_members_need_an_anchor_match_without_conflicting_pairs(self):
        articles = [article(fixture(name, "Intel lawsuit")) for name in ("a", "b", "c")]
        index = CandidateIndex(articles, identical_vectors(articles))
        origins = {0: [0], 1: [1], 2: [2]}
        same = Decision("same_event", "matching_occurrence", ("actors",))
        different = Decision("different_event", "different_action", ("event_types",))
        decisions = {(0, 1): same, (1, 2): same}

        groups, reviews, missing = form_groups(index, origins, {}, decisions)
        self.assertEqual(groups, {0: [0, 1], 2: [2]})
        self.assertEqual(reviews, {2: "unconfirmed_event_match"})
        self.assertIn((0, 2), missing)
        groups, _, _ = form_groups(index, origins, missing, {**decisions, (0, 2): same})
        self.assertEqual(groups, {0: [0, 1, 2]})
        groups, reviews, _ = form_groups(index, origins, {}, {**decisions, (0, 2): different})
        self.assertEqual(groups, {0: [0, 1], 2: [2]})
        self.assertEqual(reviews, {2: "conflicting_event_match"})


@unittest.skipUnless(np is not None, "install requirements-events.txt for the grouping tests")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.feeds = root / "feeds"
        self.feeds.mkdir()
        self.categories = root / "categories.jsonl"
        self.events = root / "events.jsonl"
        self.cache = root / "cache.sqlite3"
        self.a = fixture("a", "Intel lawsuit SecretHead", excerpt="SecretLead", text_content="SecretBody")
        self.b = fixture("b", "Intel sued after stock decline", hour="14:00")

    def write_inputs(self, rows):
        (self.feeds / "feed.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8",
        )
        labels = [label(row, ("politics_world",) if row["$id"] == "b" else ("companies_stocks",)) for row in rows]
        self.categories.write_text("\n".join(json.dumps(row) for row in labels) + "\n", encoding="utf-8")

    def group(self, transport, **kwargs):
        return run(
            self.feeds, self.categories, self.events, encoder=identical_vectors,
            judge=LunaJudge(self.cache, transport=transport, pause=lambda _: None), **kwargs,
        )

    def test_cached_rerun_is_identical_and_payload_contains_only_features(self):
        self.write_inputs([self.a, self.b])
        requests = []

        def answer(payload):
            requests.append(payload)
            return fake_response(payload)

        summary = self.group(answer)
        first = self.events.read_bytes()
        event = json.loads(first)
        self.assertEqual(summary["luna_calls"], 1)
        self.assertEqual(summary["input_tokens"], 100)
        self.assertEqual(event["topics"], ["companies_stocks", "politics_world"])
        self.assertEqual([source["article_id"] for source in event["sources"]], ["a", "b"])
        self.assertEqual(event["sources"][1]["grouping"]["matched_article_id"], "a")
        self.assertNotEqual(event["sources"][0]["reporting_origin_id"], event["sources"][1]["reporting_origin_id"])
        self.assertFalse(requests[0]["store"])
        self.assertTrue(requests[0]["text"]["format"]["strict"])
        for private in ("SecretHead", "SecretLead", "SecretBody", "https://example.com"):
            self.assertNotIn(private, requests[0]["input"])

        self.assertEqual(self.group(answer)["luna_calls"], 0)
        self.assertEqual(self.events.read_bytes(), first)
        self.assertEqual(len(requests), 1)

    def test_late_article_keeps_existing_event_id_and_cutoff_excludes_future(self):
        self.write_inputs([self.a, self.b])
        self.group(fake_response)
        previous_id = json.loads(self.events.read_bytes())["event_id"]
        late = fixture("early", "Intel lawsuit", day="2026-11-12")
        future = fixture("future", "Intel lawsuit", day="2026-11-14")
        self.write_inputs([self.a, self.b, late, future])
        summary = self.group(
            fake_response, previous=self.events, before=datetime(2026, 11, 14, tzinfo=timezone.utc),
        )
        result = json.loads(self.events.read_bytes())
        self.assertEqual(summary["articles"], 3)
        self.assertEqual(result["anchor_article_id"], "early")
        self.assertEqual(result["event_id"], previous_id)
        self.assertEqual([source["article_id"] for source in result["sources"]], ["early", "a", "b"])

    def test_rate_limit_and_malformed_batch_retry_then_succeed(self):
        self.write_inputs([self.a, self.b])
        attempts = []

        def answer(payload):
            attempts.append(payload)
            if len(attempts) == 1:
                raise HTTPError("https://example.com", 429, "limited", {"Retry-After": "1"}, BytesIO())
            if len(attempts) == 2:
                malformed = fake_response(payload)
                malformed["output"][0]["content"][0]["text"] = '{"decisions":[]}'
                return malformed
            return fake_response(payload)

        summary = self.group(answer)
        self.assertEqual(summary["retries"], 2)
        self.assertEqual(summary["luna_calls"], 3)

    def test_failed_run_leaves_previous_snapshot_intact(self):
        self.write_inputs([self.a, self.b])
        self.events.write_bytes(b"previous snapshot\n")
        with self.assertRaisesRegex(ModelError, "malformed decision batch after three attempts"):
            self.group(lambda _: {"status": "completed", "output": []})
        self.assertEqual(self.events.read_bytes(), b"previous snapshot\n")


if __name__ == "__main__":
    unittest.main()
