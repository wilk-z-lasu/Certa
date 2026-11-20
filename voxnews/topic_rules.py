"""Topic IDs and multilingual rules shared by article categorization."""

import re
import unicodedata


TOPICS = (
    "economy_central_banks",
    "companies_stocks",
    "currencies",
    "crypto",
    "technology_ai",
    "politics_world",
    "other_news",
)

ECONOMY, COMPANIES, CURRENCIES, CRYPTO, TECHNOLOGY, POLITICS, OTHER = TOPICS


def normalize_tag(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def phrase(pattern: str, *, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", flags)


def span(rule: str, field: str, match: re.Match[str]) -> dict:
    return {"rule": rule, "field": field, "start": match.start(), "end": match.end()}


# Exact section names. Desk formats, publisher names, tickers, and geographic
# labels are deliberately absent. Stock-market and general-world desks are
# handled separately because they accept broad coverage.
PUBLISHER_SECTIONS = {
    ECONOMY: "economic|economic highlights|economy|inflation|wirtschaft|economie|inflatie|fed|boj|rba|rbnz|boc|boe|ecb",
    COMPANIES: "stocks|earnings reports|geschäftsberichte|winstrapporten|ipo|börsengang|beursgang|mergers & acquisitions|fusionen und übernahmen|fusies en overnames|etfs|börsengehandelte fonds|beursgenoteerde fondsen|etf news and commentary|smart beta etf|style box etf|sector etf|stocks in the news|corporate summary|earnings esp|screen of the week|52 week high|mutual fund equity report",
    CURRENCIES: "forex|foreign exchange",
    CRYPTO: "crypto|krypto|cryptocurrency|crypto business|bitcoin|ethereum|solana|xrp|altcoin|altcoins|defi",
    TECHNOLOGY: "tech|technology|technologie|artificial intelligence|künstliche intelligenz|kunstmatige intelligentie|cybersecurity",
    POLITICS: "political|politics|trade war",
    OTHER: "sports|sport|entertainment|crime|royals|games|science|personal finance|personal money management|leisure & entertainment|freizeit und unterhaltung|vrije tijd en entertainment|budgeting in retirement|general retirement planning",
}

SECTION_TOPIC = {
    section: topic
    for topic, sections in PUBLISHER_SECTIONS.items()
    for section in sections.split("|")
}

BROAD_SECTIONS = {
    "stock market": COMPANIES,
    "aktienmarkt": COMPANIES,
    "aandelenmarkt": COMPANIES,
    "world": POLITICS,
    "national": POLITICS,
}

# Newstex codes are weaker than publisher and article evidence. Use a short
# allowlist of topical codes because some codes are assigned inconsistently
# across translated feeds. Sentiment and geo codes never enter the map.
NEWSTEX_TOPIC = {
    "ai": TECHNOLOGY,
    "technolo": TECHNOLOGY,
    "cryptoc": CRYPTO,
    "fornexch": CURRENCIES,
    "earnings": COMPANIES,
    "mergerac": COMPANIES,
    "mutualfd": COMPANIES,
    "politics": POLITICS,
    "sports": OTHER,
    "entrtain": OTHER,
}

# Each expression has a stable ID. The first match in the headline or lead is
# recorded using original-string offsets, including for Unicode characters.
TOPIC_RULES = {
    ECONOMY: {
        "central_bank": r"central banks?|federal reserve|bank of (?:england|japan|canada)|european central bank|reserve bank of (?:australia|new zealand)|fed|ecb|boj|boc|boe|rba|rbnz|ezb|bundesbank|dnb|zentralbank(?:en)?|not(?:en)?bank(?:en)?|centrale banken?",
        "price_data": r"inflation(?:srate)?|inflatie(?:cijfers)?|ppi(?:[\s-]data)?|cpi(?:[\s-]data)?|(?:core\s+)?pce|consumer prices?|producer prices?|groothandelsprijzen|producentenprijzen|erzeugerpreise|verbraucherpreise",
        "economy_data": (
            r"(?:real\s+)?gdp|bip|bbp|payrolls|jobless claims|unemployment(?: rate)?|arbeitslosenquote|werkloosheid|"
            r"retail sales|industrial output|industrial production|wirtschaftswachstum|economische groei|"
            r"economic growth|economy contract(?:s|ed)|trade (?:balance|deficit|surplus|swings? to (?:a )?(?:deficit|surplus))|"
            r"handelstekort|handelsdefizit"
        ),
        "interest_rates": r"rate (?:cuts?|hikes?|decisions?)|interest rates?|zinssenkung\w*|zinserhöhung\w*|rentebesluit\w*|renteverlaging\w*|renteverhoging\w*",
    },
    COMPANIES: {
        "stocks_and_funds": (
            r"stocks?|shares?(?! (?:his|her|their|your|a|an|the|tips|details|photos|images)\b)|equities|shareholders?|"
            r"etfs?|mutual funds?|stock futures|nasdaq|s&p\s?500|dow(?: jones)?|aktien(?:kurs|markt)?|"
            r"aktionär\w*|aandelen(?:koers|markt)?|aandeel(?:houder\w*)?|beursgenoteerd\w*|beursgang\w*"
        ),
        "company_finance": r"earnings|eps|ebitda|capex|quarterly (?:results|revenue|profit)|revenue|net income|bilanzen|quartalsergebnisse|quartalsgewinn|quartaalresultaten|kwartaalcijfers|kwartaalwinst|beurswinst",
        "company_action": r"merger(?:s)?|acquisitions?|takeover|ipo|buybacks?|(?:interim|new) ceo|ceo (?:exit|resignation|succession)|chief executive|leader(?:ship)? shake-up|fusion(?:en)?|übernahme\w*|börsengang|rücktritt als ceo|fusie\w*|overname\w*|aftreden als ceo",
    },
    CURRENCIES: {
        "fx_pair": r"(?:USD|EUR|JPY|GBP|CAD|CHF|AUD|NZD|CNY|MXN)\s*[/–-]\s*(?:USD|EUR|JPY|GBP|CAD|CHF|AUD|NZD|CNY|MXN)",
        "fx_market": r"forex|foreign exchange|exchange rates?|devisen(?:markt|handel)?|valutamarkt|wisselkoers\w*|(?:weak|strong|weaker|stronger) (?:yen|dollar|euro|pound)|(?:yen|dollar|euro|pound) (?:rallies|slides|rises|falls|weakens|strengthens)|schwach\w* yen|zwakke yen",
    },
    CRYPTO: {
        "crypto_asset": r"bitcoin|ethereum|solana|xrp|dogecoin|altcoins?|stablecoins?|memecoins?|cryptocurrenc\w*|crypto(?:valuta|currency|currencies|markt|beurs|\s+exchange)?|krypto(?:währung\w*|markt|börse)?|blockchain|defi|tokeni[sz]\w*",
        "crypto_market": r"(?:bitcoin|crypto|ether|ethereum|krypto)[\s‑-]+(?:etfs?|exchange|börse|prijs|kurs)|(?:crypto|digital asset) (?:trading|regulation|mining)",
    },
    TECHNOLOGY: {
        "ai": r"AI|KI|artificial intelligence|künstlich\w* intelligenz|kunstmatige intelligentie|large language models?|generative (?:AI|KI)|chatbots?|machine learning",
        "chips_and_infrastructure": r"semiconductors?|chipmakers?|chips? (?:exports?|sales|production|manufacturing)|chipmaking|chip export\w*|data[ -]?cent(?:er|re)s?|halbleiter\w*|chip(?:hersteller|export)\w*|halfgeleider\w*|datacenter\w*|rechenzentrum\w*|rechenzentren|optical technology|optische technologie",
        "technology_products": r"cybersecurity|cyberattacks?|cyberangriff\w*|cyberaanval\w*|software outages?|(?:outlook|microsoft|cloud|exchange online) outage|outlook (?:down|is down|ausgefallen|uitgevallen)|(?:ausfall|storing) (?:von |van )?(?:outlook|microsoft)|robotics|robotaxi\w*|quantum computing|quantencomput\w*|kwantumcomput\w*|tech(?:nology)? (?:industry|sector|companies|giants|plays|momentum)|gaming (?:industry|market)",
    },
    POLITICS: {
        "government_and_elections": r"elections?|midterms?|senate|senat|senaat|parliament\w*|parlament\w*|congress|kongress|government shutdown|national security|national\w* sicherheit|nationale veiligheid|wahl(?:en|kampf)?|verkiezing\w*|coalition talks|political crisis|supreme court|federal agency|federal government",
        "international_policy": r"trade (?:war|talks)|trade sanctions|foreign policy|tariffs?|export (?:controls?|curbs|restrictions?)|restrictions on imports|arms embargo|military (?:action|operation|conflict)|ceasefire|diplomat\w*|botschafter\w*|gezant\w*|handelskrieg|handelsoorlog|handelsgespräche|handelsbesprekingen|importheffing\w*|einfuhrzoll|zölle|ausfuhrbeschränkung\w*|exportbeperking\w*|beschränkungen für importe|beperkingen op de import|wapenstilstand|waffenstillstand",
        "public_regulation": r"regulators?|regulatory (?:action|oversight)|antitrust|watchdog|aufsichtsbehörde\w*|derivateaufsicht|(?:mededingings)?waakhond|cftc",
    },
    OTHER: {
        "culture_sport_life": (
            r"episode|boxing (?:debut|match)|entertainment news|sports? (?:final|tournament)|"
            r"retirement (?:plans?|budget|savings)|(?:your|our|household) budget|concert|fernsehserie|"
            r"boxdebüt|pensioenplan\w*|bokswedstrijd\w*"
        ),
    },
}

COMPILED_TOPICS = {
    topic: {name: phrase(expression) for name, expression in rules.items()}
    for topic, rules in TOPIC_RULES.items()
}

# A passing mention of a company's stock in the lead is common in reporting
# about a different subject. Require a market action or a dedicated term.
STOCK_EXCERPT = phrase(
    r"(?:stocks?|shares?|aktien|aandelen) (?:of|fell|rose|gained|jumped|slumped|slid|climbed|rallied|trade\w*|"
    r"price|market|fielen|stiegen|daalden|stegen)|etfs?|mutual funds?|aktienkurs|aandelenkoers|shareholders?"
)
