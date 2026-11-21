"""Compare printed quantities and dates across the three briefing languages."""

from collections import Counter
from datetime import date
from decimal import Decimal
import re

from .event_candidates import DATE_MENTION, MONTH, MONTH_NUMBER, QUARTER


NUMBER = re.compile(r"(?<!\w)[+−-]?\d+(?:[.,]\d+)*")
SCIENTIFIC = re.compile(r"(?<!\w)([+−-]?\d+(?:[.,]\d+)?)[eE]([+−-]?\d+)")
DOT_DATE = re.compile(r"\b(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>20\d{2})\b")
LOCAL_QUARTER = re.compile(r"\b([1-4])\.?\s+(?:Quartal|kwartaal|quarter)(?:\s+(20\d{2}))?\b", re.I)
FISCAL_YEAR = re.compile(r"\b(?:FY|GJ|fiscal year|Geschäftsjahr|boekjaar)\s*-?\s*(20\d{2})\b", re.I)
QUARTER_WORDS = {"first": 1, "erste": 1, "ersten": 1, "erstes": 1, "eerste": 1,
                 "second": 2, "zweite": 2, "zweiten": 2, "zweites": 2, "tweede": 2,
                 "third": 3, "dritte": 3, "dritten": 3, "drittes": 3, "derde": 3,
                 "fourth": 4, "vierte": 4, "vierten": 4, "viertes": 4, "vierde": 4}
WORD_QUARTER = re.compile(r"\b(" + "|".join(QUARTER_WORDS) +
    r")\s+(?:quarter|Quartals?|kwartaal)(?:\s+(?:of\s+|van\s+)?(20\d{2}))?\b", re.I)
WORDS = {
    "prozentpunkte": "percentage points", "prozentpunkt": "percentage points",
    "procentpunten": "percentage points", "procentpunt": "percentage points",
    "basispunkte": "basis points", "basispunt": "basis points", "basispunten": "basis points",
    "prozent": "percent", "procent": "percent", "milliarde": "billion", "milliarden": "billion",
    "miljard": "billion", "miljarden": "billion", "biljoen": "trillion", "biljoenen": "trillion",
    "millionen": "million", "miljoen": "million", "miljoenen": "million", "duizend": "thousand",
    "tausend": "thousand", "stunden": "hours", "stunde": "hours", "uur": "hours", "uren": "hours",
    "tage": "days", "tagen": "days", "dagen": "days", "aktien": "shares", "aandelen": "shares",
    "nutzer": "users", "gebruikers": "users", "dollar": "dollars", "pfund": "pounds", "pond": "pounds",
}
CARDINAL_WORDS = (
    "zero|nul|null", "one|één|eins", "two|twee|zwei", "three|drie|drei", "four|vier", "five|vijf|fünf",
    "six|zes|sechs", "seven|zeven|sieben", "eight|acht", "nine|negen|neun", "ten|tien|zehn",
    "eleven|elf", "twelve|twaalf|zwölf", "thirteen|dertien|dreizehn", "fourteen|veertien|vierzehn",
    "fifteen|vijftien|fünfzehn", "sixteen|zestien|sechzehn", "seventeen|zeventien|siebzehn",
    "eighteen|achttien|achtzehn", "nineteen|negentien|neunzehn", "twenty|twintig|zwanzig",
)
WORDS.update({word: str(value) for value, names in enumerate(CARDINAL_WORDS) for word in names.split("|") if word})
WORD_PATTERN = re.compile(r"\b(?:" + "|".join(sorted(WORDS, key=len, reverse=True)) + r")\b", re.I)
CURRENCIES = {"$": "$", "€": "EUR", "£": "£", "¥": "¥",
              "dollar": "$", "dollars": "$", "euro": "EUR", "euros": "EUR",
              "pound": "£", "pounds": "£", "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY"}
SCALES = {"": "", "k": "thousand", "thousand": "thousand", "m": "million", "mn": "million",
          "mio": "million", "million": "million", "b": "billion", "bn": "billion",
          "mrd": "billion", "billion": "billion", "trillion": "trillion"}
UNITS = {"percent": "%", "percentage": "%", "per cent": "%", "basis point": "bps", "basis points": "bps",
         "percentage point": "pp", "percentage points": "pp", "share": "shares", "user": "users",
         "hour": "hours", "day": "days", "barrel": "barrels"}
DIMENSIONS = {
    "per_share": r"\b(?:per share|EPS|je Aktie|pro Aktie|winst per aandeel|per aandeel)\b",
    "annual": r"\b(?:annual\w*|yearly|year[- ](?:on|over)[- ]year|yoy|jährlich\w*|jaarlijks\w*|op jaarbasis|gegenüber dem Vorjahresmonat)\b",
    "monthly": r"\b(?:monthly|month[- ]on[- ]month|mom|monatlich\w*|maandelijks\w*|op maandbasis|gegenüber dem Vormonat|per month|pro Monat|per maand)\b",
    "months": r"\b\d+\s+(?:months?|Monate[n]?|maanden)\b",
    "years": r"\b\d+\s+(?:years?|Jahre[n]?|jaar)\b",
}


def decimal_value(token, language):
    thousands, point = (",", ".") if language == "en" else (".", ",")
    integer = rf"(?:\d{{1,3}}(?:{re.escape(thousands)}\d{{3}})+|\d+)"
    if not re.fullmatch(rf"[+−-]?{integer}(?:{re.escape(point)}\d+)?", token):
        raise ValueError("ambiguous numeric format")
    value = Decimal(token.replace("−", "-").replace(thousands, "").replace(point, "."))
    if not value:
        return "0"
    exact = format(value, "f")
    return exact.rstrip("0").rstrip(".") if "." in exact else exact


def signature(text, language):
    # Imported at call time because the passage index also consumes verification primitives.
    from .overview_material import QUANTITY

    text = re.sub(r"\b(USD|EUR|GBP|JPY)(?=[+−-]?\d)", r"\1 ", text)
    values = Counter()

    def calendar_date(match):
        if match.re is DOT_DATE:
            year, month, day = (int(match[k]) for k in ("year", "month", "day"))
        elif match["iso_date"]:
            parsed = date.fromisoformat(match["iso_date"])
            year, month, day = parsed.year, parsed.month, parsed.day
        else:
            year = int(match["year"]) if match["year"] else None
            month = MONTH_NUMBER[(match["first_month"] or match["last_month"]).casefold()]
            day = int(match["first_day"] or match["last_day"])
        date(year or 2000, month, day)
        values["date", year, month, day] += 1
        return " "

    remaining = DATE_MENTION.sub(calendar_date, DOT_DATE.sub(calendar_date, text))

    def period(match):
        if match[0] == "may" and not match["year"]:
            return match[0]
        values["month", int(match["year"]) if match["year"] else None,
               MONTH_NUMBER[match["month"].casefold()]] += 1
        return " "

    remaining = MONTH.sub(period, remaining)

    def quarter(match):
        value = QUARTER_WORDS[match[1].casefold()] if match.re is WORD_QUARTER else int(match[1])
        values["quarter", value, int(match[2]) if match[2] else None] += 1
        return " "

    remaining = WORD_QUARTER.sub(quarter, LOCAL_QUARTER.sub(quarter, QUARTER.sub(quarter, remaining)))

    def fiscal_year(match):
        values["fiscal_year", int(match[1])] += 1
        return " "

    remaining = FISCAL_YEAR.sub(fiscal_year, remaining)
    normalized = WORD_PATTERN.sub(lambda m: WORDS[m[0].casefold()], remaining)

    def scientific(match):
        values["scientific", decimal_value(match[1], language), int(match[2].replace("−", "-"))] += 1
        return "0"

    normalized = SCIENTIFIC.sub(scientific, normalized)
    for match in NUMBER.finditer(normalized):
        values["number", decimal_value(match[0], language)] += 1
    for match in QUANTITY.finditer(normalized):
        if not (match["currency"] or match["scale"] or match["unit"]):
            continue
        unit = (match["unit"] or "").casefold()
        currency = CURRENCIES.get((match["currency"] or "").strip().upper(), "")
        unit_currency = CURRENCIES.get(unit) or CURRENCIES.get(unit.upper())
        if unit_currency:
            if currency and currency != unit_currency:
                raise ValueError("conflicting currency labels")
            currency, unit = unit_currency, ""
        scale = (match["scale"] or "").casefold().rstrip(".")
        values["quantity", decimal_value(match["value"], language), currency,
               SCALES.get(scale, scale), UNITS.get(unit, unit)] += 1
    for label, pattern in DIMENSIONS.items():
        if re.search(pattern, text, re.I):
            values["dimension", label] = 1
    return values


def translation_numbers_match(original, translated, language):
    if language not in {"de", "nl"}:
        raise ValueError("expected German or Dutch translation")
    try:
        return signature(original, "en") == signature(translated, language)
    except (ValueError, ArithmeticError):
        return False


def source_numbers_support(wording, quote, language="en"):
    """Allow a claim to use part of a source, retaining each quantity's dimensions."""
    try:
        wanted, available = signature(wording, "en"), signature(quote, language)
    except (ValueError, ArithmeticError):
        return False
    for key, count in wanted.items():
        if key[0] in {"date", "month"} and key[1] is None:
            found = sum(n for candidate, n in available.items() if candidate[0] == key[0] and candidate[2:] == key[2:])
        elif key[0] == "quarter" and key[2] is None:
            found = sum(n for candidate, n in available.items() if candidate[0] == "quarter" and candidate[1] == key[1])
        else:
            found = available[key]
        if found < count:
            return False
    return True
