import unittest

from voxnews.number_validation import source_numbers_support, translation_numbers_match


class TranslationNumbersTest(unittest.TestCase):
    def test_locale_changes_preserve_values_and_units(self):
        for original, translated, language in [
            ("Revenue was $28,309 million in October 2026.",
             "De omzet bedroeg 28.309 miljoen dollar in oktober 2026.", "nl"),
            ("Inflation was 3.6 percent year on year.", "Die Inflation lag bei 3,6 Prozent gegenüber dem Vorjahresmonat.", "de"),
            ("The stake was worth $1.9 billion.", "Het belang was 1,9 miljard dollar waard.", "nl"),
            ("The fee is $299 monthly.", "Het tarief is 299 dollar per maand.", "nl"),
            ("The outage lasted 19 hours.", "De storing duurde 19 uur.", "nl"),
            ("The outage lasted two hours.", "Der Ausfall dauerte zwei Stunden.", "de"),
            ("The amount is $1.9e3.", "Het bedrag is $1,9e3.", "nl"),
            ("The amount is USD3.03.", "Der Betrag ist 3,03 USD.", "de"),
        ]:
            with self.subTest(translated=translated):
                self.assertTrue(translation_numbers_match(original, translated, language))

    def test_changed_values_scales_and_units_are_rejected(self):
        for original, translated in [
            ("Revenue was $28,309 million.", "De omzet was 28,309 miljoen dollar."),
            ("The stake was worth $1.9 billion.", "Het belang was 1,9 biljoen dollar waard."),
            ("The rate rose 3.6 percentage points.", "Het tarief steeg 3,6 procent."),
            ("The price was $3.", "De prijs was 3 euro."),
            ("Acme opened a plant.", "Acme opende 99 fabrieken."),
            ("The forecast covers the next 12 months.", "De prognose omvat de komende 12 jaar."),
            ("The amount is $1234567890123456789012345678901.",
             "Het bedrag is $1234567890123456789012345678902."),
            ("The amount is $1e-3.", "Het bedrag is $1e+3."),
            ("The price was $3.", "De prijs was 3 USD."),
        ]:
            with self.subTest(translated=translated):
                self.assertFalse(translation_numbers_match(original, translated, "nl"))

    def test_dates_and_reporting_quarters_are_preserved(self):
        self.assertTrue(translation_numbers_match("The outage began on November 12, 2026.", "Der Ausfall begann am 12. November 2026.", "de"))
        self.assertTrue(translation_numbers_match("The outage began on 2026-11-12.", "Der Ausfall begann am 12.11.2026.", "de"))
        self.assertFalse(translation_numbers_match("The outage began on November 12, 2026.", "Der Ausfall begann am 12. Oktober 2026.", "de"))
        self.assertTrue(translation_numbers_match("Q3 2026 earnings were $3.03 per share.", "Der Gewinn im 3. Quartal 2026 lag bei 3,03 Dollar je Aktie.", "de"))
        self.assertFalse(translation_numbers_match("Q3 2026 earnings were $3.03 per share.", "Der Gewinn im 4. Quartal 2026 lag bei 3,03 Dollar je Aktie.", "de"))
        self.assertTrue(translation_numbers_match("Third quarter earnings were $3.03 per share.", "Der Gewinn im dritten Quartal lag bei 3,03 Dollar je Aktie.", "de"))

    def test_english_claims_can_use_localized_source_numbers(self):
        source = "Acme meldete im zweiten Quartal 2026 einen Gewinn von 3,6 Milliarden USD."
        self.assertTrue(source_numbers_support("Acme reported Q2 2026 income of USD 3.6 billion.", source, "de"))
        self.assertFalse(source_numbers_support("Acme reported Q3 2026 income of USD 3.6 billion.", source, "de"))
        self.assertFalse(source_numbers_support("Acme reported Q2 2026 income of USD 3.6 million.", source, "de"))
        self.assertFalse(source_numbers_support("Acme reported one departure.", "Acme reported two departures."))
