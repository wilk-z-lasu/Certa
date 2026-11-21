from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from certa.editorial_rules import occurrences
from certa.event_candidates import Article, CandidateIndex, reporting_origins
from certa.luna import LunaJudge


def article(headline, excerpt, *, day=14, minute=0, language="en", feed="fixture", **metadata):
    date = datetime(2027, 1, day, 0, minute, tzinfo=timezone.utc)
    source = {"$id": headline, "permalink": "https://example.com/news", "language": language,
              "headline": headline, "excerpt": excerpt, **metadata}
    return Article.from_source(source, {"topics": (), "regions": ()}, feed, date)


class EditorialRulesTests(unittest.TestCase):
    def test_outage_signatures_match_new_company_and_product(self):
        a = article("Helix Mail outage", "Helix's Mail outage affected customers.")
        b = article("Helix battles outage in Mail", "Helix outage disrupted Mail.")
        c = article("Helix Store outage", "Helix outage disrupted Store.")
        d = article("Helix Mail outage", "Helix outage disrupted Mail again.", day=17)
        index = CandidateIndex([a, b, c, d], None)
        self.assertEqual(list(index.signature_pairs(range(4))), [(0, 1)])

    def test_attributed_lawsuit_needs_both_substance_and_headline_focus(self):
        title = "Helix hit with shareholder lawsuit"
        self.assertFalse(list(occurrences(title, "Helix faces a shareholder lawsuit alleging unrelated breaches.")))
        self.assertFalse(list(occurrences("Helix shares fall", "Helix faces a shareholder lawsuit alleging executives concealed worsening personal computer demand.")))
        self.assertFalse(list(occurrences(title, "Helix denies it faces a shareholder lawsuit alleging executives concealed worsening personal computer demand.")))
        lead = "Helix faces a shareholder lawsuit alleging executives concealed worsening personal computer demand before an offering."
        result, = occurrences(title, lead)
        self.assertEqual(result.kind, "allegation")
        self.assertIn("alleges that Helix", result.wording)
        self.assertTrue(lead[result.left:result.right].endswith("demand"))

    def test_forecast_and_different_period_do_not_match_release(self):
        left = article("US PPI rises in December", "US producer prices rose in December.")
        match = article("US wholesale inflation rises in December", "US wholesale prices increased in December.")
        forecast = article("US PPI expected to rise in December", "US producer prices may rise in December.")
        previous = article("US PPI rises in November", "US producer prices rose in November.")
        canada = article("Canadian PPI rises in December", "Canadian producer prices rose in December.")
        index = CandidateIndex([left, match, forecast, previous, canada], None)
        self.assertEqual(list(index.signature_pairs(range(5))), [(0, 1)])

    def test_cloud_judge_uses_supported_signature_without_calling_model(self):
        left = article("US PPI slows to 0.3%", "US producer prices rose in October.")
        right = article("US wholesale inflation rises in October", "US wholesale prices rose in October.")
        articles = [left, right]
        pairs = CandidateIndex(articles, None).signature_pairs(range(2))
        transport = Mock()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"CERTA_CLOUD_ONLY": "1", "CERTA_PROVIDER": "openai"}
        ):
            judge = LunaJudge(Path(tmp) / "cache.sqlite3", transport=transport)
            decisions = judge.judge(list(pairs.values()), articles)
        self.assertEqual(decisions[(0, 1)].reason, "matching_release")
        transport.assert_not_called()

    def test_market_threshold_uses_traded_level_and_ignores_forward_target(self):
        headline = "Asteroid price today: below $64,000 as bank cuts its price target"
        source = "Key takeaways Asteroid traded below $64,000 as a bank cut its price target to $99,532."
        result, = occurrences(headline, source)
        self.assertEqual(result.wording, "Asteroid changed hands for less than 64,000 dollars.")
        self.assertEqual(source[result.left:result.right], "Key takeaways Asteroid traded below $64,000")
        self.assertFalse(list(occurrences(headline, "Asteroid could trade below $64,000.")))
        self.assertFalse(list(occurrences(headline, "Asteroid traded below $64,000.50.")))
        self.assertFalse(list(occurrences(headline, "Asteroid traded below $64,000,000.")))
        self.assertFalse(list(occurrences(headline, "Asteroid traded below $64,000 million.")))
        self.assertTrue(list(occurrences(headline, "Asteroid traded below $64,000.")))

    def test_unconfirmed_nominal_outage_does_not_create_claim(self):
        self.assertFalse(list(occurrences("Helix Mail outage?", "Helix's Mail outage was a false alarm.")))

    def test_offline_translation_requires_unique_artwork_byline_and_close_time(self):
        def translated(headline, language, *, minute=0, author="Pat Reporter", image="acme.jpg"):
            return article(headline, "", language=language, feed=f"invezz_{language}", minute=minute,
                           source=author, thumb_url=f"https://example.com/{image}")

        en = translated("Acme opens a factory", "en")
        de = translated("Acme eröffnet eine Fabrik", "de", minute=2)
        nl = translated("Acme opent een fabriek", "nl", minute=3)
        self.assertEqual(reporting_origins([en, de, nl])[0], {0: [0, 1, 2]})
        de_again = translated("Acme baut eine weitere Fabrik", "de", minute=3)
        self.assertEqual(reporting_origins([en, de, nl, de_again])[0], {0: [0, 2], 1: [1], 3: [3]})
        for mismatch in (translated("Andere Überschrift", "de", minute=16),
                         translated("Andere Überschrift", "de", author="Another Reporter"),
                         translated("Andere Überschrift", "de", image="placeholder.jpg")):
            self.assertEqual(reporting_origins([en, mismatch])[0], {0: [0], 1: [1]})


if __name__ == "__main__":
    unittest.main()
