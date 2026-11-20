"""Local passage indexing, editorial facets and conservative disagreement detection."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .event_candidates import ACTOR_PATTERNS, ACTORS
from .official_releases import digest
from .verify import ADVICE


SECTIONS = ("development", "figures", "mechanism", "timeline", "background", "reaction",
            "implications", "outlook", "uncertainty")
FACETS = {
    "mechanism": r"because|driven by|due to|attribut\w* to|reflects?|defined as|exclud\w*|adjusted|methodolog\w*|architecture|infrastruc\w*|protocol|mechanism|denominator|liquidity|margin|valuation|yields?|multiples?|ratio|benchmark|duration|consensus|gross|operating|diluted|basis points?|dadurch|aufgrund|bereinig\w*|infrastruktur|omdat|doordat|gecorrigeerd|winstmarge",
    "background": r"histor\w*|previously|formerly|prior to|founded|since|last year|years ago|seit|zuvor|vorjahr\w*|früher|sinds|voorheen|vorig jaar",
    "reaction": r"react\w*|respond\w*|response|critic\w*|apologi\w*|in a statement|market reaction|jumped|slid|rallied|reagier\w*|reaktion\w*|reageer\w*|reactie",
    "implications": r"impact\w*|implica\w*|affect\w*|consequen\w*|enable\w*|pressure\w*|exposure|risk\w*|depend\w*|auswirkung\w*|risik\w*|betroff\w*|gevolg\w*|invloed|blootstelling",
    "outlook": r"forecast\w*|expect\w*|project(?:ed|ion\w*)|outlook|scheduled|plans to|deadline|will|could|guidance|erwart\w*|prognos\w*|geplant\w*|könnte\w*|verwacht\w*|vooruitzicht\w*|zou|zullen",
    "uncertainty": r"uncertain\w*|unconfirmed|unclear|disput\w*|denie[ds]|alleg\w*|no evidence|could not confirm|unverified|preliminary|revised|reportedly|unklar|bestreit\w*|angeblich|vorläufig\w*|onzeker\w*|ontken\w*|voorlopig\w*|betwist\w*",
}
FACETS = {k: re.compile(r"\b(?:" + v + r")\b", re.I) for k, v in FACETS.items()}
MODALITY = {
    "advice": re.compile(ADVICE.pattern + r"|\b(?:buy now|strong buy|strong sell|should (?:buy|sell)|kaufempfehlung|koopadvies|verkoopadvies)\b", re.I),
    "allegation": re.compile(r"\b(?:alleg\w*|accus\w*|plaintiffs? (?:say|claim)\w*|beschuld\w*|vorgeworfen|aanklag\w*)\b", re.I),
    "denial": re.compile(r"\b(?:denied|denies|refut\w*|dementier\w*|bestreit\w*|ontken\w*)\b", re.I),
    "forecast": FACETS["outlook"],
    "interpretation": re.compile(r"\b(?:suggests?|implies|argu(?:es|ed)|according to analysts|in our view|deutet|volgens analisten|suggereert)\b", re.I),
    "preliminary": re.compile(r"\b(?:preliminary|provisional|flash estimate|vorläufig\w*|voorlopig\w*|snelle raming)\b", re.I),
    "revision": re.compile(r"\b(?:revis(?:ed|ion)|correct(?:ed|ion)|revidiert|korrigiert|herzien\w*|gecorrigeerd)\b", re.I),
}
DATE = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|Q[1-4](?:\s+20\d{2})?|(?:19|20)\d{2}|"
                  r"(?:\d{1,2}(?:st|nd|rd|th)?\.?\s+)?(?:January|Januar[iy]?|February|Februar[iy]?|March|März|maart|April|May|Mai|mei|June?|Juni|July?|Juli|August(?:us)?|September|O[ck]tober|November|De[cz]ember)"
                  r"(?:\s+\d{1,2}(?!\d)(?:st|nd|rd|th)?)?(?:,?\s+20\d{2})?)\b", re.I)
QUANTITY = re.compile(r"(?<![\w.])(?P<currency>[$€£¥]|(?:USD|EUR|GBP|JPY)\s+)?"
                      r"(?P<value>[+−-]?\d+(?:[.,]\d+)*(?:[’']\d{3})*)"
                      r"(?:[ \t]*(?P<scale>trillion|billion|million|thousand|milliard\w*|millionen|miljoen|duizend|mrd\.?|mio\.?|bn|mn|[mbk](?!\w)))?"
                      r"(?:[ \t]*(?P<unit>percentage points?|percent(?:age)?|per cent|prozent(?:punkte?)?|procent(?:punt(?:en)?)?|basis points?|bps|%|"
                      r"USD|EUR|GBP|dollars?|euros?|pounds?|shares?|seats?|votes?|users?|hours?|days?|"
                      r"megawatts?|gigawatts?|terabytes?|gigabytes?|MW|GW|GB|km|barrels?)(?!\w))?", re.I)
BOUNDARY = re.compile(r"[.!?]+[”’\"')\]]*(?=\s|$)|\n+")
ABBREV = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Dr|Prof|Inc|Corp|Ltd|vs|ca|z\.B|bzw|Nr|e\.g|i\.e)|\b[A-Z](?:\.[A-Z])+|\b[A-Z])\.$")
BOILERPLATE = re.compile(r"^(?:click here|read (?:also|more):|also read:|zacks'? (?:top|free) stock|"
                         r"want the latest recommendations|to read this article on zacks|the views and opinions expressed|"
                         r"originally published on|bildquelle:|lees ook:|lesen sie auch:)\b", re.I)
FOOTER = re.compile(r"\b(?:AI disclosure:\s*AI tools|KI[- ](?:Offenlegung|Hinweis):|AI[- ](?:vermelding|disclosure):|"
                    r"Want the latest recommendations from Zacks|Click to get this free report|"
                    r"This article originally published on Zacks|The post .{0,320}? appeared first on Invezz)", re.I)
ATTRIBUTION = re.compile(r"\b(?P<speaker>[A-ZÀ-Þ][\w’'-]*(?: (?:[A-ZÀ-Þ][\w’'-]*|of|van|de|der)){0,5})"
                         r"\s+(?P<verb>said|reported|warned|argued|denied|confirmed|estimated|alleged|"
                         r"sagte|meldete|warnte|bestätigte|zei|meldde|bevestigde|verklaarde)\b")
CHALLENGE = re.compile(r"\b(?:denied (?:the |any |that |allegations)|disputed (?:the |that )|"
                       r"reject(?:ed|s) (?:the )?(?:allegation|claim)|dementierte (?:den |die |das )|"
                       r"ontkende (?:dat |de |het ))", re.I)
VOCABULARY = re.compile(r"\b(?:earnings per share|diluted EPS|adjusted EPS|forward P/E|free cash flow|operating margin|"
                        r"gross margin|net income|EBITDA|net asset value|expense ratio|dividend yield|"
                        r"basis points?|seasonally adjusted|headline (?:CPI|PPI)|core (?:CPI|PPI)|"
                        r"deposit facility|policy rate|carry trade|exchange rate|support level|resistance level|"
                        r"market cap(?:itali[sz]ation)?|staking|token unlock|hash rate|proof.of.stake|"
                        r"inference|latency|semiconductor|compute capacity|training data|outage|"
                        r"class action|injunction|regulat\w+ approval|bill passed|vote share|"
                        r"Gewinn je Aktie|Bruttomarge|Basispunkte?|Wechselkurs|winst per aandeel|"
                        r"brutomarge|basispunten|wisselkoers)\b", re.I)
CLAUSE = re.compile(r";\s+|,\s+(?=whereas\b|while\b|während\b|terwijl\b)", re.I)


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def sentences(text):
    start = 0
    for boundary in BOUNDARY.finditer(text):
        end = boundary.end()
        if boundary[0] == "." and ABBREV.search(text[max(start, end-12):end]):
            continue
        left = start + len(text[start:end]) - len(text[start:end].lstrip())
        right = end - (len(text[left:end]) - len(text[left:end].rstrip()))
        if left < right:
            yield left, right
        start = end
    if text[start:].strip():
        yield start + len(text[start:]) - len(text[start:].lstrip()), len(text.rstrip())


def describe(text):
    modes = [mode for mode, rx in MODALITY.items() if rx.search(text)]
    if text.rstrip().endswith("?"):
        modes.append("question")
    dates = [m for m in DATE.finditer(text) if m[0] != "may"]
    quantities = []
    for m in QUANTITY.finditer(text):
        if not (m["currency"] or m["scale"] or m["unit"]) and any(d.start() <= m.start() < d.end() for d in dates):
            continue
        quantities.append({"raw": m[0], "start": m.start(), "end": m.end(), "literal": m["value"],
                           "currency": (m["currency"] or "").strip(), "scale": m["scale"] or "", "unit": m["unit"] or ""})
    sections = [key for key, pattern in FACETS.items() if pattern.search(text)]
    if quantities:
        sections.append("figures")
    if dates:
        sections.append("timeline")
    if not sections:
        sections.append("development")
    return {"sections": sections, "qualifiers": modes, "quantities": quantities,
            "dates": [{"raw": m[0], "start": m.start(), "end": m.end()} for m in dates],
            "technical_terms": list(dict.fromkeys(m[0] for m in VOCABULARY.finditer(text))),
            "attributions": [{"speaker": m["speaker"], "verb": m["verb"], "start": m.start(), "end": m.end()}
                             for m in ATTRIBUTION.finditer(text)],
            "named_actors": sorted({ACTORS[name] for name, rx in ACTOR_PATTERNS.items() if rx.search(text)})}


# Comparison frames retain the entire sentence apart from one explicitly measured
# quantity or one polarity marker. Other figures, attribution and periods remain in the key.
STANCE = re.compile(r"\b(?:confirmed|denied|approved|rejected|bestätigte|dementierte|bevestigde|ontkende)\b", re.I)
STANCE_FAMILY = {"confirmed": ("confirmation", 1), "denied": ("confirmation", -1),
                 "bestätigte": ("confirmation", 1), "dementierte": ("confirmation", -1),
                 "bevestigde": ("confirmation", 1), "ontkende": ("confirmation", -1),
                 "approved": ("approval", 1), "rejected": ("approval", -1)}

# Narrow accounting statements can be compared across different phrasings when
# the subject, reporting period, accounting metric, units and actual basis match.
ACCOUNTING = re.compile(
    r"^(?P<subject>[\w&.'’ -]{2,65}?)\s+(?:(?:reported|posted|recorded)\s+|(?:had)\s+)"
    r"(?:(?P<early>Q[1-4]\s+20\d{2})\s+)?(?P<metric>(?:adjusted |net |operating |gross )?"
    r"(?:revenue|sales|income|profit|earnings per share|margin))\s+(?:of\s+)?"
    r"(?P<amount>[$£€]?\s*[+−-]?\d+(?:[.,]\d+)*\s*(?:million|billion|percent|%)?)"
    r"(?:\s+(?:for|in|during)\s+(?P<late>Q[1-4]\s+20\d{2}))?[.!]?$", re.I)
ISSUES = {key: re.compile(pattern, re.I) for key, pattern in {
    "acquisition": r"\b(?:merger|acquir\w*|acquisition|takeover|fusion\w*|übernahme|overname|fusie)\b",
    "resignation": r"\b(?:resign\w*|stepp?\w* down|rücktritt|aftreden|opstapp\w*)\b",
    "breach": r"\b(?:breach\w*|unauthori[sz]ed access|datenleck|datalek)\b",
    "outage": r"\b(?:outage|disruption|storing|ausfall)\b",
    "payment": r"\b(?:payment\w*|zahlung\w*|betaling\w*)\b",
}.items()}
POSITIVES = re.compile(r"\b(?:confirmed|confirms|alleges?|alleged|approved|bestätigt\w*|bevestig\w*)\b", re.I)


def frames(text, info, lang):
    if {"forecast", "revision", "preliminary", "question", "advice"} & set(info["qualifiers"]):
        return
    template = lambda s: " ".join(re.findall(r"[\w%€£$]+|<slot>", norm(s)))
    for q in info["quantities"]:
        if not (q["unit"] or q["currency"] or q["scale"]):
            continue
        # A comma can be a thousands separator or a decimal point.
        value = q["literal"].replace("−", "-")
        if "," in value and lang == "en" and not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
            continue
        try:
            decimal = Decimal(value.replace(",", "") if lang == "en" else value.replace(".", "").replace(",", "."))
        except InvalidOperation:
            continue
        surrounding = template(text[:q["start"]] + " <slot> " + text[q["end"]:])
        if len(surrounding.split()) >= 4:
            yield ("quantity", lang, q["currency"].casefold(), q["scale"].casefold(), q["unit"].casefold(), surrounding), str(decimal.normalize())
        metric = ACCOUNTING.fullmatch(text) if lang == "en" else None
        if metric and (metric["early"] or metric["late"]) and q["raw"].strip() == metric["amount"].strip():
            multiplier = {"million": 10**6, "billion": 10**9, "": 1}.get(norm(q["scale"]))
            if multiplier is not None:
                yield ("accounting", norm(metric["subject"]), norm(metric["metric"]), norm(metric["early"] or metric["late"]),
                       norm(q["currency"]), norm(q["unit"])), str((decimal * multiplier).normalize())
    stances = list(STANCE.finditer(text))
    if len(stances) == 1:
        m = stances[0]
        family, value = STANCE_FAMILY[m[0].casefold()]
        key = template(text[:m.start()] + " <slot> " + text[m.end():])
        if len(key.split()) >= 4:
            yield ("stance", lang, family, key), str(value)
    negative = "denial" in info["qualifiers"]
    if negative or POSITIVES.search(text):
        for issue, rx in ISSUES.items():
            if rx.search(text):
                for actor in info["named_actors"]:
                    yield ("possible_stance", issue, actor), "denial" if negative else "assertion"


def passage_material(event_id, sources, articles):
    materials, comparisons = {}, defaultdict(list)
    for source in sources:
        article = articles[source["article_id"]]
        field = next((k for k in ("text_content", "excerpt", "headline") if article.get(k, "").strip()), "headline")
        text = article[field]
        kept = 0
        footer = FOOTER.search(text)
        body = text[:footer.start()] if footer else text
        spans = []
        for left, right in sentences(body):
            start = left
            for cut in CLAUSE.finditer(body, left, right):
                spans.append((start, cut.start(), left, right))
                start = cut.end()
            spans.append((start, right, left, right))
        for start, end, left, right in spans:
            statement = text[start:end]
            if BOILERPLATE.search(statement) or not any(c.isalpha() for c in statement):
                continue
            # Case and punctuation can change the meaning (US/us, questions, signs).
            # Only identical text shares a claim; translations retain their own spans.
            needs_context = (left != start or end != right or re.match(
                r"^(?:It|That|This|They|He|She|These|Those|The former|Das|Dies|Het|Dit|Ze)\b", statement, re.I))
            context = [left, right] if left != start or end != right else None
            if needs_context and not context and kept:
                context = [previous_left, right]
            key = digest([event_id, article["language"], statement, source["article_id"] if needs_context else None,
                          text[slice(*context)] if context else None])
            ref = {"source_id": source["article_id"], "field": field, "start": start, "end": end,
                   "span_hash": digest(statement)}
            if context:
                ref["context_span"] = context
            if key not in materials:
                info = describe(statement)
                item = {"id": key, "type": "passage", "language": article["language"], **info,
                        "evidence": [], "is_lead": False, "disagreements": [],
                        "reported_challenge": bool(CHALLENGE.search(statement)),
                        "draft_use": "omit" if {"advice", "question"} & set(info["qualifiers"]) else "paraphrase_and_check"}
                materials[key] = item
                for frame, value in frames(statement, info, item["language"]):
                    comparisons[frame].append((key, value))
            item = materials[key]
            item["evidence"].append({**ref, "role": "reported_in"})
            if kept == 0:
                item["is_lead"] = True
                if "development" not in item["sections"]:
                    item["sections"].append("development")
            kept += 1
            previous_left = left
    return list(materials.values()), comparisons
