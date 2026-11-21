"""Geographic relevance inferred from the subject and scope of the reporting."""

import re

from .topic_rules import normalize_tag, phrase, span


# Country names, demonyms, and national institutions for the most common
# geography in the feeds. Demonyms need a local subject, such as a factory.
COUNTRIES = {
    "NL": (r"netherlands|nederland|niederlande|amsterdam|rotterdam|the hague|den haag", r"dutch|nederlands\w*|niederländisch\w*", r"de nederlandsche bank|dutch central bank|nederlandse centrale bank"),
    "DE": (r"germany|deutschland|duitsland|berlin(?:[‑-]brandenburg)?|frankfurt", r"german|deutsch\w*|duits\w*", r"bundesbank|bundestag"),
    "US": (
        r"united states|verenigde staten|vereinigte staaten|(?-i:U\.?S\.?(?:A\.?)?)|louisiana",
        r"american|amerikanisch\w*|amerikaanse?|us[‑-]amerikanisch\w*",
        r"federal reserve|(?-i:Fed)|us treasury|bureau of labor statistics|commodity futures trading commission|"
        r"(?-i:CFTC|Social Security COLA)",
    ),
    "GB": (r"united kingdom|great britain|britain|verenigd koninkrijk|großbritannien|(?-i:U\.?K\.?)", r"british|britisch\w*|brits\w*", r"bank of england|(?-i:BoE)"),
    "CN": (r"china|beijing|peking", r"chinese|chinesisch\w*", r"people.s bank of china|(?-i:PBoC|PBOC)"),
    "JP": (r"japan", r"japanese|japans\w*|japanisch\w*", r"bank of japan|(?-i:BoJ|BOJ)"),
    "CA": (r"canada|kanada", r"canadian|canadees|canadese|kanadisch\w*", r"bank of canada|(?-i:BoC|BOC)"),
    "AU": (r"australia|australië|australien", r"australian|australisch\w*", r"reserve bank of australia|(?-i:RBA)"),
    "NZ": (r"new zealand|neuseeland|nieuw[ -]zeeland", r"new zealand|nieuw[ -]zeelands\w*|neuseeländisch\w*", r"reserve bank of new zealand|(?-i:RBNZ)"),
    "FR": (r"france|frankrijk|frankreich", r"french|frans\w*|französisch\w*", r"banque de france"),
    "IN": (r"india|indien", r"indian|indiaas\w*|indiase|indisch\w*", r"reserve bank of india"),
    "RU": (r"russia|russland", r"russian|russisch\w*", r"bank of russia|russian central bank"),
    "UA": (r"ukraine|oekraine|oekraïne", r"ukrainian|ukrainisch\w*|oekraïens\w*", r"national bank of ukraine"),
    "KR": (r"south korea|zuid[ -]korea|südkorea", r"south korean|zuid[ -]koreaans\w*|südkoreanisch\w*", r"bank of korea"),
    "TW": (r"taiwan", r"taiwanese|taiwanisch\w*", r"central bank of taiwan"),
    "CH": (r"switzerland|schweiz|zwitserland", r"swiss|schweizer\w*|zwitsers\w*", r"swiss national bank|schweizerische nationalbank|(?-i:SNB)"),
    "MX": (r"mexico|mexiko", r"mexican|mexicaans\w*|mexikanisch\w*", r"bank of mexico|banxico"),
    "IR": (r"iran", r"iranian|iraans\w*|iranisch\w*", r"central bank of iran"),
    "IL": (r"israel|israël", r"israeli|israelisch\w*|israëlisch\w*", r"bank of israel"),
}


LOCAL_SUBJECT = (
    r"(?:\w+[‑-])?(?:stocks?|shares?|equities|futures|markets?|economy|inflation|wholesale (?:prices?|inflation)|"
    r"producer prices?|consumer prices?|ppi|cpi|gdp|industrial output|retail sales|"
    r"(?:(?-i:[A-Z]{2,6}) )?(?:export|import) (?:curbs|controls?|restrictions?)|exports?|imports?|tariffs?|"
    r"government|treasury|senate|regulator\w*|elections?|midterms?|energy grid|workers?|households?|"
    r"defen[cs]e|security concerns?|diplomat\w*|envoy|military|"
    r"(?:manufacturing|production) (?:facility|plant|site)|factory|(?:optical technology |tech(?:nology)? )?companies|"
    r"data[ -]?cent(?:er|re) equipment|businesses|lender|bank(?:en)?|"
    r"industrieproduktion|handel\w*|wirtschaft\w*|aktien\w*|technologieunternehmen|bundesstaat\w*|regierung\w*|"
    r"produktionsstätt\w*|produktionsanlag\w*|werk\b|senat|inflation\w*|bip|ausfuhr\w*|einfuhr\w*|unternehmen|"
    r"rechenzentrumsausrüstung|"
    r"aandelen\w*|staten|economie\w*|bbp|inflatie\w*|markten?|fabriek\w*|productiefaciliteit\w*|gezant\w*|"
    r"technologiebedrijven|bedrijven|apparatuur|beperkingen)"
)

EVENT = phrase(
    r"invest\w*|intervention|trade talks|handel\w*|growth\b|produk\w*|productie\w*|production\b|"
    r"contracts?|expan\w*|build\w*|open\w*|close[sd]?|rate (?:hikes?|cuts?)|inflation|prices?|"
    r"trade|export\w*|import\w*|restric\w*|tariffs?|sanctions?|steuer\w*|zölle|beperkingen|"
    r"ban(?:s|ned)?|election\w*|arrest\w*|detain\w*|court|lawsuit\w*|"
    r"security|concerns?|attacks?|war|ceasefire|launch\w*|outages?|disrupt\w*|activit\w*"
)

GLOBAL_SCOPE = phrase(
    r"(?:global|worldwide|weltweit\w*|wereldwijde?) (?:(?:service|internet|power|oil|gas|financial) )?"
    r"(?:outages?|disruptions?|shortages?|supply (?:glut|surplus)|pandemics?|markets?|demand|sales|users?|"
    r"ausfall\w*|störung\w*|angebotsüberschuss\w*|nachfrage|storing\w*|aanbodoverschot\w*|vraag)|"
    r"(?:affect\w*|disrupt\w*|hit) (?:\w+\s+){0,3}(?:worldwide|across the globe)|"
    r"(?:betroffen|ausgefallen) (?:\w+\s+){0,2}weltweit|"
    r"(?:storing|getroffen) (?:\w+\s+){0,2}wereldwijd"
)

COUNTRY_RULES = {
    country: {
        "national_subject": phrase(rf"(?:{name}|{demonym})(?:[’']s)?[ \t‑-]+{LOCAL_SUBJECT}"),
        "national_institution": phrase(institution),
        "location": phrase(rf"(?:in|across|within|into|to|from|nach|aus|naar|uit) (?:the |de |den |die )?(?:{name})"),
        "country_mention": phrase(name),
    }
    for country, (name, demonym, institution) in COUNTRIES.items()
}

JOINT_ACTION = phrase(r"talks|negotiations|trade dispute|trade deal|handelsoverleg|handelsgespräche")
PLACE_CONNECTOR = re.compile(r"[\s‑–-]*(?:\band\b|\bund\b|\ben\b|[‑–-])[\s‑–-]*", re.IGNORECASE)

# Only direct country labels are hints. Publisher geography never creates a
# tag by itself, and regional institutions like the ECB imply no member state.
LOCATION_TAGS = {
    "netherlands": "NL", "nederland": "NL", "niederlande": "NL",
    "germany": "DE", "deutschland": "DE", "duitsland": "DE",
    "united states": "US", "united kingdom": "GB", "china": "CN", "japan": "JP",
    "canada": "CA", "australia": "AU", "new zealand": "NZ", "france": "FR",
    "india": "IN", "russia": "RU", "ukraine": "UA", "south korea": "KR",
    "taiwan": "TW", "switzerland": "CH", "mexico": "MX", "iran": "IR", "israel": "IL",
}

FX_HOME = {"USD": "US", "JPY": "JP", "GBP": "GB", "CAD": "CA", "CHF": "CH", "AUD": "AU", "NZD": "NZ", "CNY": "CN", "MXN": "MX"}
FX_PAIR = phrase(r"(USD|EUR|JPY|GBP|CAD|CHF|AUD|NZD|CNY|MXN)\s*/\s*(USD|EUR|JPY|GBP|CAD|CHF|AUD|NZD|CNY|MXN)", flags=0)
CLAUSE_BREAK = re.compile(r"[!?;]|(?<!\b[A-Z])\.(?=\s|$)")


def nearby_event(text: str, location: re.Match[str], *, distance: int) -> bool:
    """Find a relevant action in the same clause as a place mention."""
    left = text[max(0, location.start() - distance):location.start()]
    right = text[location.end():location.end() + distance]
    return bool(EVENT.search(CLAUSE_BREAK.split(left)[-1]) or EVENT.search(CLAUSE_BREAK.split(right)[0]))


def joint_action_regions(headline: str) -> dict[str, dict]:
    """Recognize countries named together as parties to talks or a deal."""
    if not JOINT_ACTION.search(headline):
        return {}

    places = sorted(
        ((match.start(), match.end(), country) for country, rules in COUNTRY_RULES.items()
         for match in rules["country_mention"].finditer(headline)),
    )
    regions = {}
    for first, second in zip(places, places[1:]):
        if first[2] != second[2] and PLACE_CONNECTOR.fullmatch(headline[first[1]:second[0]]):
            context = headline[second[1]:second[1] + 28]
            if action := JOINT_ACTION.search(context):
                evidence = {
                    "rule": "geo.joint_action",
                    "field": "headline",
                    "start": first[0],
                    "end": second[1] + action.end(),
                }
                regions[first[2]] = regions[second[2]] = evidence
    return regions


def classify_regions(headline: str, excerpt: str, provider_tags: list[str]) -> tuple[dict[str, dict], list[str]]:
    regions = joint_action_regions(headline)
    for field, text in (("headline", headline), ("excerpt", excerpt[:450])):
        global_scope = GLOBAL_SCOPE.search(text)
        if global_scope and "global" not in regions:
            regions["global"] = span("geo.worldwide_impact", field, global_scope)

        for country, rules in COUNTRY_RULES.items():
            if country in regions:
                continue

            for rule in ("national_subject", "national_institution"):
                match = rules[rule].search(text)
                if match and (field == "headline" or rule == "national_subject" or nearby_event(text, match, distance=48)):
                    regions[country] = span(f"geo.{rule}", field, match)
                    break
            if country in regions:
                continue

            # A country named on its own in an excerpt may be a comparison.
            # Require a directional/location phrase in the lead, or a place
            # named with a relevant action in the headline.
            rule = "country_mention" if field == "headline" else "location"
            for match in rules[rule].finditer(text):
                if nearby_event(text, match, distance=42):
                    regions[country] = span(f"geo.{rule}_with_event", field, match)
                    break

    pair = FX_PAIR.search(headline)
    if pair:
        for currency in pair.groups():
            country = FX_HOME.get(currency)
            if country and country not in regions:
                regions[country] = span("geo.headline_fx_market", "headline", pair)

    location_hints = {LOCATION_TAGS.get(normalize_tag(tag)) for tag in provider_tags} - {None}
    review = ["unconfirmed_publisher_location"] if location_hints - regions.keys() else []
    return regions, review
