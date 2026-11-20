import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from voxnews.categorization import categorize_article
from voxnews.categorize import run


def article(headline: str, **fields) -> dict:
    return {
        "$id": "fixture-1",
        "permalink": "https://example.com/story",
        "language": "en",
        "headline": headline,
        **fields,
    }


class CategorizationTests(unittest.TestCase):
    def test_translations_preserve_topics_regions_and_original_offsets(self):
        for language, headline, location, section in (
            ("en", "Shares gain on expansion plans", "German manufacturing facility", "Stock market"),
            ("de", "Aktien steigen nach Ausbauplänen", "deutsche Produktionsstätte", "Aktienmarkt"),
            ("nl", "Aandelen stijgen na uitbreidingsplannen", "Duitse productiefaciliteit", "Aandelenmarkt"),
        ):
            with self.subTest(language=language):
                excerpt = f"€ — {location}."
                source = article(headline, language=language, excerpt=excerpt, provider_categories=[section])
                result = categorize_article(source)
                self.assertEqual(result["language"], language)
                self.assertEqual(result["topics"], ["companies_stocks"])
                self.assertEqual(result["regions"], ["DE"])
                evidence = result["evidence"]["regions"]["DE"]
                self.assertEqual(excerpt[evidence["start"]:evidence["end"]], location)

    def test_dutch_export_policy_in_english_has_local_evidence(self):
        result = categorize_article(article("China opposes Dutch ASML export controls on chipmaking equipment"))
        self.assertEqual(result["regions"], ["CN", "NL"])
        self.assertEqual(result["topics"], ["technology_ai", "politics_world"])

    def test_publisher_geography_and_sentiment_are_hints_only(self):
        result = categorize_article(article(
            "An update", language="de", provider_categories=["Germany"], categories=["NEGATIVE", "POSITIVE"]
        ))
        self.assertEqual(result["topics"], ["other_news"])
        self.assertEqual(result["regions"], ["unknown"])
        self.assertEqual(result["evidence"]["regions"], {})
        self.assertEqual(result["review_reasons"], ["no_supported_topic", "unconfirmed_publisher_location"])

    def test_country_mentions_and_global_scope(self):
        source = article("Global outage disrupts Outlook", excerpt="The spokesperson, who grew up in Germany, commented.")
        self.assertEqual(categorize_article(source)["regions"], ["global"])
        for headline in ("Eurozone trade swings to deficit", "Shares debut on the Nasdaq Global Select Market"):
            with self.subTest(headline=headline):
                self.assertEqual(categorize_article(article(headline))["regions"], ["unknown"])

    def test_bilateral_policy_keeps_both_countries(self):
        result = categorize_article(article("U.S.-China talks resume over tariff dispute"))
        self.assertEqual(result["regions"], ["CN", "US"])


class FeedTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.feeds = root / "feeds"
        self.feeds.mkdir()
        self.destination = root / "output" / "labels.jsonl"
        self.first = self.feeds / "a.jsonl"
        self.first.write_text(json.dumps(article("Bitcoin rises", text_content="Private body")) + "\n", encoding="utf-8")

    def test_write_once_per_article_and_repeat_identically(self):
        second = self.feeds / "b.jsonl"
        second.write_text(json.dumps(article("AI news", **{"$id": "fixture-2"})), encoding="utf-8")
        summary = run(self.feeds, self.destination)
        first_run = self.destination.read_bytes()
        self.assertEqual(summary["articles"], 2)
        self.assertEqual([json.loads(row)["article_id"] for row in first_run.splitlines()], ["fixture-1", "fixture-2"])
        self.assertNotIn(b"Bitcoin rises", first_run)
        self.assertNotIn(b"Private body", first_run)
        run(self.feeds, self.destination)
        self.assertEqual(self.destination.read_bytes(), first_run)

    def test_invalid_and_duplicate_rows_leave_previous_result_in_place(self):
        run(self.feeds, self.destination)
        first_run = self.destination.read_bytes()
        second = self.feeds / "b.jsonl"
        for data, expected in (
            (b"malformed json\n", r"b\.jsonl:1: Expecting value"),
            (b"\xff\n", r"b\.jsonl:1: .*utf-8"),
            (b"{}\n", r"b\.jsonl:1: \$id must be a non-empty string"),
            (self.first.read_bytes(), r"b\.jsonl:1: duplicate article ID .* first seen at a\.jsonl:1"),
        ):
            with self.subTest(data=data):
                second.write_bytes(data)
                with self.assertRaisesRegex(ValueError, expected):
                    run(self.feeds, self.destination)
                self.assertEqual(self.destination.read_bytes(), first_run)
                self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])


if __name__ == "__main__":
    unittest.main()
