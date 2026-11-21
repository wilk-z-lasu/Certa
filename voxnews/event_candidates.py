"""Derive event features and shortlist pairs on the local machine."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from heapq import heappush, heappushpop
import re
from urllib.parse import urlsplit
from zlib import crc32
import unicodedata

from .topic_rules import phrase
from .editorial_rules import occurrences


KINDS = {
    "producer_prices": r"ppi|producer prices?|wholesale (?:prices?|inflation)|erzeugerpreise|producentenprijzen|groothandelsprijzen",
    "consumer_prices": r"cpi|consumer prices?|verbraucherpreise|consumentenprijzen",
    "gdp": r"gdp|bip|bbp|gross domestic product|bruttoinlandsprodukt",
    "jobs_report": r"payrolls|jobless claims|unemployment rate|arbeitslosenquote|werkloosheidscijfers",
    "rate_decision": r"rate decision|holds? rates?|raises? rates?|cuts? rates?|zinsentscheid\w*|rentebesluit\w*",
    "lawsuit": r"lawsuits?|sues?|sued|court case|klage\w*|verklag\w*|rechtszaak|aanklacht",
    "court_ruling": r"court rules|court ruling|judges? ruled|gerichtsurteil\w*|uitspraak",
    "leadership_change": r"resign\w*|quits?|steps? down|interim ceo|ceo exit|ceo succession|rücktritt\w*|aftreden|afgetreden|vertrek als",
    "acquisition": r"mergers?|acquisitions?|takeovers?|fusion\w*|übernahme\w*|fusie\w*|overname\w*",
    "earnings": r"earnings|quarterly results|quarterly profit|quartalszahlen|quartalsergebnis\w*|kwartaalcijfers|kwartaalresultaten",
    "outage": r"outages?|service disruption\w*|ausfall\w*|ausgefallen|storing\w*|uitgevallen",
    "election": r"elections?|midterms?|wahl(?:en|sieg)?|verkiezing\w*",
    "trade_policy": r"tariffs?|trade (?:talks|deal|war)|export (?:controls?|curbs|restrictions?)|zölle|handelsgespräch\w*|handelsgesprekken|importheffing\w*",
    "offering": r"ipo|initial public offering|börsengang\w*|beursgang\w*",
    "document_leak": r"(?:record|data|document) leaks?|leaked (?:documents?|files?|records?)|leak\w*|gelekt\w*",
    "market_move": r"(?:shares?|stocks?|yen|dollar|bitcoin) (?:fell|rise\w*|rose|falls?|gain\w*|slid\w*|rall\w*)|aktien\w* (?:steigen|fallen)|aandelen\w* (?:stijgen|dalen)",
}
KIND_PATTERNS = {kind: phrase(pattern) for kind, pattern in KINDS.items()}

# These are the subjects of economic releases. A market story mentioning EUR/GBP can
# concern both currencies while describing a single country's inflation release.
RELEASE_SUBJECTS = {
    "EA":r"euro[ -]?(?:area|zone)|euroraum|eurogebied",
    "GB":r"u\.?k\.?|britain|british|united kingdom|britische|britse",
    "CA":r"canada|canadian|kanadische|canadese",
    "US":r"u\.?s\.?|united states|american|amerikaanse",
    "DE":r"germany|german|deutschland|deutsche|duitse",
    "NL":r"netherlands|dutch|nederlandse|niederländische",
}
RELEASE_PATTERNS = {region:re.compile(
    rf"\b(?:{names})(?:['’]s)?\s+(?:(?:headline|core|wholesale|annual|monthly)\s+)?"
    r"(?:inflation|inflatie|cpi[h]?|hicp|ppi|producer prices?|consumer prices?|wholesale (?:prices?|inflation)|gdp)\b",re.I)
    for region,names in RELEASE_SUBJECTS.items()}
PERIOD_KINDS = {"producer_prices", "consumer_prices", "gdp", "jobs_report", "earnings"}
RELEASE_MATCH_KINDS = frozenset({"producer_prices"})
REPORTED_RELEASE = phrase(r"(?:ppi|producer prices?|wholesale (?:prices?|inflation)) "
                          r"(?:slows?|rose|rises?|increased|increases?|fell|falls?|declined|held)")

# Only these canonical names, validated ticker symbols, and derived counts can
# leave the process. Other entity-like tokens are used for local ranking only.
ACTORS = {
    "intel": "intel",
    "nvidia": "nvidia",
    "jensen huang": "jensen_huang",
    "microsoft": "microsoft",
    "outlook": "outlook",
    "exchange online": "exchange_online",
    "tesla": "tesla",
    "spacex": "spacex",
    "amd": "amd",
    "broadcom": "broadcom",
    "apple": "apple",
    "alphabet": "alphabet",
    "google": "alphabet",
    "amazon": "amazon",
    "meta": "meta",
    "openai": "openai",
    "anthropic": "anthropic",
    "asml": "asml",
    "deutsche bank": "deutsche_bank",
    "ubs": "ubs",
    "el niño": "el_nino",
    "kraken": "kraken",
    "coinbase": "coinbase",
    "cftc": "cftc",
    "federal reserve": "federal_reserve",
    "fed": "federal_reserve",
    "ecb": "european_central_bank",
    "ezb": "european_central_bank",
    "bank of japan": "bank_of_japan",
    "boj": "bank_of_japan",
    "bank of england": "bank_of_england",
    "boe": "bank_of_england",
    "bank of canada": "bank_of_canada",
    "boc": "bank_of_canada",
    "donald trump": "donald_trump",
    "bitcoin": "bitcoin",
    "ethereum": "ethereum",
}
ACTOR_PATTERNS = {name: phrase(re.escape(name)) for name in ACTORS}
PROPER_WORD = re.compile(r"(?<!\w)[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ]{2,}(?!\w)")
TICKER = re.compile(r"[A-Z]{1,5}(?:[.-][A-Z]{1,2})?")
INLINE_TICKER = re.compile(r"(?:\b(?:NASDAQ|NYSE)\s*:\s*|\$)([A-Z]{1,5}(?:[.-][A-Z]{1,2})?)(?!\w)")

MONTHS = (
    "january|januar|januari", "february|februar|februari", "march|märz|maart",
    "april", "may|mai|mei", "june|juni", "july|juli", "august|augustus",
    "september", "october|oktober", "november", "december|dezember",
)
MONTH_NUMBER = {name: number for number, names in enumerate(MONTHS, 1) for name in names.split("|")}
MONTH_NAMES = "|".join(MONTH_NUMBER)
MONTH = phrase(rf"(?P<month>{MONTH_NAMES})(?!\d)(?:\s+(?P<year>20\d{{2}}))?")
QUARTER = phrase(r"Q([1-4])(?:[\s-]+(20\d{2}))?")
DATE_MENTION = phrase(
    rf"(?:(?P<first_day>\d{{1,2}})\.?\s+(?P<first_month>{MONTH_NAMES})|"
    rf"(?P<last_month>{MONTH_NAMES})\s+(?P<last_day>\d{{1,2}}))(?:,?\s+(?P<year>20\d{{2}}))?|"
    r"(?P<iso_date>20\d{2}-\d{2}-\d{2})",
)


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fingerprint(value):
    return sha256(value.encode("utf-8")).hexdigest()


def reporting_period(headline, excerpt, kinds, published):
    if not PERIOD_KINDS.intersection(kinds):
        return None
    for text in (headline, excerpt):
        if match := QUARTER.search(text):
            quarter = int(match[1])
            year = int(match[2]) if match[2] else published.year - (quarter > (published.month - 1) // 3 + 1)
            return f"{year}-Q{quarter}"
        for match in MONTH.finditer(text):
            name = match["month"].casefold()
            # English 'may' often introduces a possibility.
            if name == "may" and match["month"] == "may" and not match["year"]:
                continue
            month = MONTH_NUMBER[name]
            year = int(match["year"]) if match["year"] else published.year - (month > published.month)
            return f"{year}-{month:02}"
    return None


def named_event_date(headline, excerpt, published):
    for match in DATE_MENTION.finditer(headline + "\n" + excerpt):
        try:
            if match["iso_date"]:
                return date.fromisoformat(match["iso_date"]).isoformat()
            month = MONTH_NUMBER[(match["first_month"] or match["last_month"]).casefold()]
            day = int(match["first_day"] or match["last_day"])
            return date(int(match["year"] or published.year), month, day).isoformat()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class Article:
    id: str
    permalink: str
    language: str
    feed: str
    published: datetime
    topics: tuple[str, ...]
    regions: tuple[str, ...]
    headline: str
    excerpt: str
    author: str
    body_hash: str
    actors: tuple[str, ...]
    kinds: tuple[str, ...]
    period: str | None
    event_date: str | None
    terms: frozenset[str]
    shingles: frozenset[int]
    figures: tuple[str, ...]
    release_regions: tuple[str, ...]
    occurrence_cues: tuple[tuple[str, str], ...] = ()
    thumbnail: str = ""

    @classmethod
    def from_source(cls, row, category, feed, published):
        headline = (row.get("headline") or "")[:300]
        excerpt = (row.get("excerpt") or "")[:700]
        text = headline + "\n" + excerpt
        primary = [kind for kind, pattern in KIND_PATTERNS.items() if pattern.search(headline)]
        kinds = tuple(primary or [kind for kind, pattern in KIND_PATTERNS.items() if pattern.search(excerpt[:400])])
        cues = tuple(
            (event.signature.partition(":")[0], fingerprint(event.signature)[:16])
            for event in occurrences(headline, excerpt) if event.signature
        )
        if any(kind == "service_outage" for kind, _ in cues) and "outage" not in kinds:
            kinds += ("outage",)
        names = {ACTORS[name] for name, pattern in ACTOR_PATTERNS.items() if pattern.search(text)}
        tickers = row.get("company_tickers") or []
        if isinstance(tickers, list):
            names.update(f"ticker:{ticker}" for ticker in tickers if isinstance(ticker, str) and TICKER.fullmatch(ticker))
        names.update(f"ticker:{ticker}" for ticker in INLINE_TICKER.findall(text))
        body = normalize(row.get("text_content") or "")
        words = body.split()
        shingles = (frozenset(crc32(" ".join(words[i:i+5]).encode()) for i in range(len(words)-4))
                    if len(words) >= 50 else frozenset())
        author = row.get("source") or ""
        return cls(
            row["$id"], row["permalink"], row["language"], feed, published,
            tuple(sorted(set(category["topics"]))), tuple(sorted(set(category["regions"]))),
            headline, excerpt, normalize(author), fingerprint(body) if body else "",
            tuple(sorted(names))[:12], kinds, reporting_period(headline, excerpt[:400], kinds, published),
            named_event_date(headline, excerpt[:400], published),
            frozenset(normalize(word) for word in PROPER_WORD.findall(text)),
            shingles, tuple(re.findall(r"\d+(?:[.,]\d+)*",body)),
            tuple(code for code,pattern in RELEASE_PATTERNS.items() if pattern.search(headline)),
            cues,
            thumbnail_key(row.get("thumb_url")),
        )

    def descriptor(self):
        return {
            "published_day": self.published.date().isoformat(),
            "topics": self.topics,
            "regions": self.regions,
            "actors": self.actors,
            "event_types": self.kinds,
            "reporting_period": self.period,
            "mentioned_date": self.event_date,
            "release_regions":self.release_regions,
            "occurrence_cues": self.occurrence_cues,
        }

    def signatures(self):
        signatures = [("occurrence_cues", cue) for cue in self.occurrence_cues]
        measures = RELEASE_MATCH_KINDS.intersection(self.kinds)
        if (self.period and len(self.release_regions) == len(measures) == 1
                and REPORTED_RELEASE.search(self.headline) and "?" not in self.headline
                and not re.search(r"\b(?:if|could|would|may|forecast|revisions?|revised)\b", self.headline, re.I)):
            signatures.append(("reporting_period", self.release_regions[0], next(iter(measures)), self.period))
        return signatures


@dataclass(frozen=True)
class Comparison:
    left: int
    right: int
    similarity: float
    gap_hours: float
    shared_terms: int
    shared_actors: int
    shared_kind: bool
    shared_period: bool
    shared_event_date: bool

    @property
    def key(self):
        return self.left, self.right

    @property
    def score(self):
        return (
            self.similarity + 0.034 * min(self.shared_actors, 3)
            + 0.004 * min(self.shared_terms, 5) + 0.055 * self.shared_kind
            + 0.04 * self.shared_period - 0.00035 * self.gap_hours
        )

    @property
    def within_window(self):
        return self.gap_hours <= 72 or (
            self.gap_hours <= 168 and self.shared_kind
            and (self.shared_period or (self.shared_actors and self.shared_event_date))
        )

    def local_candidate(self, articles):
        """Use the embedding match and occurrence details to shortlist for the small local classifier."""
        a, b = articles[self.left], articles[self.right]
        if a.release_regions and b.release_regions and set(a.release_regions)!=set(b.release_regions):
            return False
        kinds = set(a.kinds).intersection(b.kinds)
        national_release = kinds.intersection({"producer_prices","consumer_prices","gdp","jobs_report","rate_decision"})
        a_regions, b_regions = (set(r.regions)-{"unknown","global"} for r in (a,b))
        if national_release and len(a_regions) == len(b_regions) == 1 and a_regions.isdisjoint(b_regions):
            return False
        if self.shared_kind and (self.shared_actors or self.shared_period or (national_release and a_regions & b_regions)):
            return True
        # A high-similarity pair with a shared name can be an occurrence outside the event lexicon.
        return self.similarity >= .925 and self.shared_terms >= 3 and self.gap_hours <= 48

    def payload(self, articles):
        return {
            "left": articles[self.left].descriptor(),
            "right": articles[self.right].descriptor(),
            "hours_apart": self.gap_hours,
            "multilingual_similarity": self.similarity,
            "shared_local_terms": self.shared_terms,
        }

    def matching_signature(self, articles):
        left, right = (articles[i] for i in self.key)
        return matching_signature(left, right, self.gap_hours)


def matching_signature(left, right, hours):
    if left.event_date and right.event_date and left.event_date != right.event_date:
        return None
    for signature in left.signatures():
        if signature in right.signatures():
            limit = 36 if signature[0] == "occurrence_cues" else 24
            if hours <= limit and not conflicting_periods(left, right):
                return signature[0]
    return None


def conflicting_periods(left, right):
    # Different explicit periods form distinct occurrences of the same type.
    return bool(
        left.period and right.period and left.period != right.period
        and ("-Q" in left.period) == ("-Q" in right.period)
        and len(left.kinds) == 1 and left.kinds == right.kinds
    )


def thumbnail_key(value):
    if not isinstance(value, str):
        return ""
    try:
        url = urlsplit(value)
    except ValueError:
        return ""
    filename = url.path.rsplit("/", 1)[-1]
    if (url.scheme != "https" or not url.hostname or not filename
            or re.search(r"placeholder|default|no[-_]?image|logo|generic", filename, re.I)):
        return ""
    return value


def thumbnail_translations(articles, representatives):
    """Link publisher translations using unique artwork, byline and release timing."""
    relevant = [(i, article) for i, article in enumerate(articles)
                if article.language in {"en", "de", "nl"} and article.feed == f"invezz_{article.language}"
                and article.thumbnail]
    uses = Counter((article.language, article.thumbnail) for _, article in relevant)
    originals = {
        article.thumbnail: i for i, article in relevant
        if article.language == "en" and uses["en", article.thumbnail] == 1
    }
    translations = {}
    for i, article in relevant:
        if (article.language == "en" or representatives[i] != i
                or uses[article.language, article.thumbnail] != 1):
            continue
        j = originals.get(article.thumbnail)
        if j is None:
            continue
        original = articles[j]
        if (article.author and article.author == original.author
                and abs((article.published - original.published).total_seconds()) <= 900
                and not conflicting_periods(article, original)):
            translations[i] = representatives[j]
    return translations


class CandidateIndex:
    def __init__(self, articles, vectors):
        self.articles = articles
        self.vectors = vectors

    def compare(self, a, b, similarity=None):
        left, right = sorted((a, b))
        first, second = self.articles[left], self.articles[right]
        if similarity is None:
            similarity = self.vectors[left] @ self.vectors[right] if self.vectors is not None else 0
        return Comparison(
            left, right, round(float(similarity), 4),
            round(abs((second.published - first.published).total_seconds()) / 3600, 3),
            min(len(first.terms & second.terms), 12), len(set(first.actors) & set(second.actors)),
            bool(set(first.kinds) & set(second.kinds)), bool(first.period and first.period == second.period),
            bool(first.event_date and first.event_date == second.event_date),
        )

    def shortlist(self, representatives):
        times = [self.articles[i].published.timestamp() for i in representatives]
        per_article = defaultdict(list)
        for pos, left in enumerate(representatives):
            # Score only neighbors in range, in one vector operation per row.
            end = bisect_right(times, times[pos] + 7 * 24 * 3600)
            others = representatives[pos + 1:end]
            if not others:
                continue
            for right, similarity in zip(others, self.vectors[others] @ self.vectors[left]):
                pair = self.compare(left, right, similarity)
                if not pair.within_window:
                    continue
                if pair.similarity < 0.79 and not (pair.shared_kind and (pair.shared_period or pair.shared_actors)):
                    continue
                if conflicting_periods(self.articles[left], self.articles[right]):
                    continue
                ranked = (pair.score, -left, -right, pair)
                for article in (left, right):
                    heap = per_article[article]
                    if len(heap) < 8:
                        heappush(heap, ranked)
                    else:
                        heappushpop(heap, ranked)

        selected = {}
        for heap in per_article.values():
            for _, _, _, pair in heap:
                selected[pair.key] = pair
        return dict(sorted(selected.items()))

    def signature_pairs(self, representatives):
        """Preserve specific occurrence matches even when generic neighbors rank higher."""
        recent = defaultdict(list)
        selected = {}
        for right in representatives:
            article = self.articles[right]
            for signature in article.signatures():
                hours = article.published.timestamp() - 36 * 3600
                # Remove expired articles before comparing reports sharing the signature.
                recent[signature] = [i for i in recent[signature]
                                     if self.articles[i].published.timestamp() >= hours]
                for left in recent[signature]:
                    pair = self.compare(left, right)
                    if pair.matching_signature(self.articles):
                        selected[pair.key] = pair
                recent[signature].append(right)
        return selected


def reporting_origins(articles, index=None):
    """Map confirmed copies and translations to representative article indices."""
    exact, representatives = {}, {}
    anchors = defaultdict(list)
    for i, article in enumerate(articles):
        if article.body_hash in exact:
            representatives[i] = exact[article.body_hash]
            continue
        representative = i
        keys = [(article.language,k) for k in sorted(article.shingles)[:4]]
        for j in sorted({j for k in keys for j in anchors[k]}):
            other = articles[j]
            if (article.figures != other.figures or abs((article.published-other.published).days)>3
                    or conflicting_periods(article,other)):
                continue
            if len(article.shingles & other.shingles) >= .90 * len(article.shingles | other.shingles):
                representative = j
                break
        representatives[i] = representative
        if article.body_hash:
            exact[article.body_hash] = representative
        if representative == i:
            for k in keys:
                anchors[k].append(i)

    if index is None:
        translations = thumbnail_translations(articles, representatives)
        by_origin = defaultdict(list)
        for i, rep in representatives.items():
            by_origin[translations.get(rep, rep)].append(i)
        return dict(sorted(by_origin.items())), set()
    english = defaultdict(list)
    for i, article in enumerate(articles):
        if article.feed == "invezz_en" and article.language == "en" and article.author:
            english[article.author].append(i)

    # An English origin may have one German and one Dutch counterpart.
    proposals = defaultdict(list)
    reviews = set()
    for i, article in enumerate(articles):
        if article.language not in {"de", "nl"} or article.feed != f"invezz_{article.language}":
            continue
        if representatives[i] != i:
            continue
        possible = [
            index.compare(i, j)
            for j in english[article.author]
            if abs((article.published - articles[j].published).total_seconds()) <= 900
            and not conflicting_periods(article, articles[j])
        ]
        ranked = sorted(possible, key=lambda p: (-p.similarity, p.key))
        if not ranked:
            continue
        best = ranked[0]
        original = best.right if best.left == i else best.left
        close_alternative = len(ranked) > 1 and best.similarity - ranked[1].similarity < 0.025
        supports = best.shared_kind or best.shared_actors or best.shared_terms >= 2 or best.similarity >= 0.94
        strong_details = best.shared_kind and best.shared_actors >= 2
        threshold = 0.85 if strong_details else 0.885
        if best.similarity >= threshold and supports and not close_alternative:
            proposals[representatives[original], article.language].append(i)
        else:
            reviews.add(i)

    translations = {}
    for (original, _), translated in proposals.items():
        if len(translated) == 1:
            translations[translated[0]] = original
        else:
            reviews.update(translated)

    by_origin = defaultdict(list)
    for i, rep in representatives.items():
        by_origin[translations.get(rep, rep)].append(i)
    # Use the English original for translations and the first copy otherwise.
    return dict(sorted(by_origin.items())), reviews
