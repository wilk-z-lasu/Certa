"""High-precision patterns for dated price observations and policy decisions."""

from datetime import date
from decimal import Decimal
import re

from .event_candidates import MONTH_NAMES, MONTH_NUMBER
from .official_releases import number


GEO = {
    "uk": "GB", "british": "GB", "united kingdom": "GB", "britische": "GB", "britse": "GB",
    "german": "DE", "germany": "DE", "deutsche": "DE", "duitse": "DE", "deutschland": "DE",
    "dutch": "NL", "nederlandse": "NL", "niederländische": "NL", "netherlands": "NL",
    "eurozone": "EA", "euro area": "EA", "euroraum": "EA", "eurogebied": "EA",
}
MEASURE = {"cpi": "CPI", "cpih": "CPIH", "hicp": "HICP", "hvpi": "HICP",
           "vpi": "CPI", "core cpi": "core CPI"}
GEOS = "|".join(GEO)
MEASURES = "|".join(MEASURE)
VALUE = r"[-+−]?\d+(?:[.,]\d+)?"
PERCENT = r"\s*(?:%|percent\b|per cent\b|prozent\b|procent\b)"
VAL = rf"(?P<value>{VALUE}){PERCENT}"
BASIS = r"year[- ]on[- ]year|yoy|annual|monthly|mom|jährlich|monatlich|op jaarbasis|op maandbasis"
SCOPE = rf"(?P<geo>{GEOS})\s+(?:headline\s+)?(?:(?P<before>{BASIS})\s+)?(?P<measure>{MEASURES})(?:[- ](?:inflation|inflatie))?"
VERB = (r"(?:inflation\s+)?(?:was|stood at|rose to|fell to|edged up|accelerated|"
        r"increased to|remained at|stieg auf|lag bei|bedroeg|steeg naar)")
MONTH = rf"(?P<month>{MONTH_NAMES})(?!\w)(?:\s+(?P<year>20\d{{2}}))?"
MOVE = rf"(?:\s+from\s+(?P<prior>{VALUE}){PERCENT}\s+to)?"
DIRECT = re.compile(
    rf"^(?:the |die |der |de )?{SCOPE}\s+{VERB}{MOVE}\s+{VAL}"
    rf"(?:\s+(?P<after>{BASIS}))?\s+(?:in|im|for)\s+{MONTH}"
    rf"(?:\s+(?P<last>{BASIS}))?$", re.I)
LOCAL = re.compile(
    rf"^(?:die |der |de )?{SCOPE}\s+(?:lag|stieg|bedroeg)\s+(?:im|in)\s+{MONTH}"
    rf"\s+(?P<basis>{BASIS})\s+(?:(?:bei|auf|met)\s+)?{VAL}$", re.I)
FOLLOW = re.compile(
    rf"^(?:(?P<before>Monthly|Annual)\s+)?(?P<measure>core CPI|CPIH|CPI)"
    rf"(?: inflation)? (?:rose|fell|remained unchanged at|was|stood at) {VAL}(?: (?P<after>yoy|mom))?$", re.I)
BANK = re.compile(
    rf"^(?:the )?(?P<bank>BoE|Bank of England|ECB)(?:[’']s)? "
    rf"(?:(?:\d+\s*bps? (?:increase|cut) to)|(?:(?:raised|cut|held|kept) "
    rf"(?:its |the )?(?P<rate>bank rate|deposit facility rate) (?:to|at))) {VAL}"
    rf" on (?P<month>{MONTH_NAMES}) (?P<day>\d{{1,2}})(?:,? (?P<year>20\d{{2}}))?$", re.I)
FORECAST = re.compile(r"\b(?:forecast\w*|expect(?:s|ed)?|may|might|could|would|will|if|"
                      r"provisional|preliminary|flash|estimate[ds]?|revised|not|unlikely|likely|"
                      r"erwart\w*|prognos\w*|zou|verwacht\w*)\b", re.I)
SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)|\n|$)", re.S)
# These tails start a separate comparison, attribution or interpretation. Only
# the preceding factual clause is admitted to the rule's evidence span.
TAIL = re.compile(r",\s+(?=matching market expectations\b|also in line\b|compared with\b|"
                  r"while\b|confirming the flash estimate\b|according to\b)", re.I)


def period_of(match, published, day=False):
    month = MONTH_NUMBER[match["month"].lower()]
    year = int(match["year"]) if match["year"] else published.year - (month > published.month)
    period = date(year, month, int(match["day"]) if day else 1)
    age = (published.date() - period).days
    if age < 0 or (not match["year"] and age > 70):
        return None
    return period.isoformat() if day else period.strftime("%Y-%m")


def basis_of(*labels):
    bases = {"mom" if label.lower() in {"monthly", "mom", "monatlich", "op maandbasis"} else "yoy"
             for label in labels if label}
    return next(iter(bases)) if len(bases) == 1 else None


def extract(article, published):
    text = article.get("text_content") or ""
    context = None
    results = []
    for sentence in SENTENCE.finditer(text):
        raw = sentence[0].strip()
        sentence_start = sentence.start() + len(sentence[0]) - len(sentence[0].lstrip())
        main = TAIL.split(raw.rstrip(".!?"), maxsplit=1)[0]
        previous = context
        context = None
        if not main or FORECAST.search(main) or raw.endswith("?"):
            continue
        # A separately named bank in an explicit sequence of decisions.
        clause = main.split(", followed by ")[-1]
        start = sentence_start + main.rfind(clause)
        match = BANK.fullmatch(clause)
        context_span = None
        if match:
            geo = "EA" if match["bank"].lower() == "ecb" else "GB"
            measure = "Bank Rate" if geo == "GB" else "deposit facility rate"
            if geo == "EA" and not match["rate"]:
                continue
            if match["rate"] and match["rate"].lower() != measure.lower():
                continue
            try:
                period = period_of(match, published, day=True)
            except ValueError:
                continue
            basis = "level"
        else:
            clause, start = main, sentence_start
            match = DIRECT.fullmatch(clause) or LOCAL.fullmatch(clause)
            if match:
                fields = match.groupdict()
                geo, measure = GEO[match["geo"].lower()], MEASURE[match["measure"].lower()]
                period = period_of(match, published)
                basis = basis_of(*(fields.get(key) for key in ("before", "after", "last", "basis")))
                if fields.get("prior") and re.search(r"edged up|accelerated", clause, re.I):
                    prior_value = fields["prior"].replace(",", ".").replace("−", "-")
                    next_value = match["value"].replace(",", ".").replace("−", "-")
                    if Decimal(prior_value) >= Decimal(next_value):
                        continue
                if period and basis:
                    context = (geo, period, start, start + len(clause), 0)
            elif previous and previous[4] < 2 and (match := FOLLOW.fullmatch(clause)):
                geo, period, left, right, depth = previous
                measure = MEASURE[match["measure"].lower()]
                basis = basis_of(match["before"], match["after"])
                context_span = [left, right]
                if basis:
                    context = (geo, period, left, right, depth + 1)
            else:
                continue
        if not period or not basis:
            continue
        value = number(match["value"].replace(",", ".").replace("−", "-"))
        if match.re is FOLLOW and " fell " in clause.lower():
            if Decimal(value) <= 0:
                continue
            value = number("-" + value)
        evidence = {"field": "text_content", "start": start, "end": start + len(clause)}
        if context_span:
            evidence["context_span"] = context_span
        results.append(((geo, measure, period, basis), value, evidence))
    return results
