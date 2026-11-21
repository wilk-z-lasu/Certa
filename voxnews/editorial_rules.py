"""Conservative claim templates for specific, factual reporting clauses."""

from dataclasses import dataclass
import re


# Use case-sensitive names inside otherwise case-insensitive clause patterns.
NAME = r"(?-i:[A-Z][\w&.-]*(?: [A-Z][\w&.-]*){0,3})"
COMPANY = rf"(?P<company>{NAME})"
SERVICE = r"(?P<service>(?-i:[A-Z][\w-]*|[a-z][A-Z][\w-]*))"
TITLE_KINDS = {
    "service_outage": r"\b(?:outages?|down|disruptions?)\b",
    "shareholder_lawsuit": r"\blawsuits?\b",
    "records_leak": r"\bleak(?:ed)?\b",
    "ipo_pricing": r"\b(?:ipo|initial public offering)\b",
    "quarterly_earnings": r"\b(?:earnings|quarterly results)\b",
    "factory_expansion_plan": r"\b(?:expansion|factory plans?|new factory)\b",
    "asset_price_threshold": r"\b(?:price|trades?|traded|below)\b",
}
TITLE_KINDS = {k: re.compile(v, re.I) for k, v in TITLE_KINDS.items()}


@dataclass(frozen=True)
class Development:
    signature: str | None
    kind: str
    wording: str
    translations: dict[str, str]
    left: int
    right: int


def occurrences(headline, lead):
    """Extract bounded positive statements, requiring a headline focused on the event."""
    results = {}
    for event, expression, templates in RULES:
        if event in results or not TITLE_KINDS[event].search(headline):
            continue
        match = expression.search(lead[:455])
        if match is None:
            continue
        fields = match.groupdict()
        if fields.get("value"):
            fields["localized_value"] = fields["value"].replace(",", " ")
        company, service = fields.get("company"), fields.get("service")
        subject = company or service
        if re.search(rf"(?<!\w){re.escape(subject)}(?!\w)", headline, re.I) is None:
            continue
        qualifier, english, german, dutch = templates
        identity = [event, subject.casefold()]
        if service and company:
            identity.append(service.casefold())
        if event == "records_leak":
            identity.append(fields["person"].split()[-1].casefold())
        if event == "shareholder_lawsuit":
            identity.append("pc_demand")
        signature = ":".join(identity) if event not in {"asset_price_threshold", "factory_expansion_plan"} else None
        results[event] = Development(
            signature, qualifier, english.format(**fields) if english else "",
            {lang: text.format(**fields) for lang, text in (("de", german), ("nl", dutch)) if text},
            *match.span(),
        )
    return results.values()


OUTAGE = (
    "reported_fact", "{company}'s {service} service was disrupted.",
    "Bei {service} von {company} kam es zu einer Störung.",
    "De dienst {service} van {company} had een storing.",
)
RULES = (
    ("service_outage", rf"^\s*{COMPANY}['’]s {SERVICE}(?: and [\w ]{{2,40}})? outage "
     r"(?:has run for|affected|disrupted|left)\b", OUTAGE),
    ("service_outage", rf"^\s*(?:A )?(?:global )?{COMPANY} outage disrupted {SERVICE}\b", OUTAGE),
    ("service_outage", rf"^\s*{COMPANY} said an internal update caused widespread outages affecting {SERVICE}\b",
     ("reported_fact", "An internal update disrupted {service} and other {company} services.",
      "Ein internes Update störte {service} und weitere Dienste von {company}.",
      "Een interne update verstoorde {service} en andere diensten van {company}.")),
    ("service_outage", rf"^\s*{COMPANY} restored {SERVICE}[\w ,'-]{{0,100}} after an internal update caused a disruption\b",
     ("reported_fact", "An internal update disrupted {service} and other {company} services.",
      "Ein internes Update störte {service} und weitere Dienste von {company}.",
      "Een interne update verstoorde {service} en andere diensten van {company}.")),
    ("shareholder_lawsuit", rf"^\s*{COMPANY} faces a (?:proposed )?shareholder lawsuit alleging "
     r"(?:(?:that )?executives concealed worsening personal computer demand|executives misled investors about weakening PC demand)\b",
     ("allegation", "A shareholder lawsuit alleges that {company} misled investors about falling demand for personal computers.",
      "In einer Aktionärsklage wird {company} vorgeworfen, Anleger über die sinkende Nachfrage nach PCs getäuscht zu haben.",
      "Een aandeelhouderszaak beschuldigt {company} ervan beleggers te hebben misleid over de dalende vraag naar pc's.")),
    ("records_leak", rf"^\s*{COMPANY} shares fell\b[^.!?]{{0,48}}\bleak of [^.!?]{{0,50}}internal records "
     rf"exposed alleged [^.!?]{{0,225}}\bpast dealings with [^.!?]{{0,45}}, (?P<person>{NAME})(?= and)",
     ("reported_fact", "Leaked internal records brought renewed attention to {company}'s past dealings with {person}.",
      "Durchgesickerte interne Unterlagen rückten frühere Geschäfte von {company} mit {person} erneut in den Fokus.",
      "Uitgelekte interne documenten vestigden opnieuw de aandacht op eerdere zaken tussen {company} en {person}.")),
    ("records_leak", rf"^\s*Leaked (?:records|files)\b[^.!?]{{0,110}}?\b(?:indicate|show|reveal) "
     rf"{COMPANY} flagged (?:about )?\$[\d.,]+m? (?:million )?in (?:suspicious )?(?P<person>{NAME})-linked transactions\b",
     ("reported_fact", "Leaked records described transactions that {company} flagged in connection with {person}.",
      "Durchgesickerte Unterlagen beschrieben Transaktionen, die {company} im Zusammenhang mit {person} markiert hatte.",
      "Uitgelekte documenten gingen over transacties die {company} in verband met {person} had gemarkeerd.")),
    ("ipo_pricing", rf"^\s*{COMPANY} (?:has )?priced its initial public offering at \$[\d.]+ a share\b",
     ("reported_fact", "{company} set the share price for its initial public offering.",
      "{company} legte den Ausgabepreis für seinen Börsengang fest.",
      "{company} stelde de uitgifteprijs voor zijn beursgang vast.")),
    ("quarterly_earnings", rf"^\s*{COMPANY} \([A-Z]+\) more than doubled its quarterly revenue\b",
     ("reported_fact", "{company}'s quarterly revenue grew sharply.",
      "Der Quartalsumsatz von {company} ist deutlich gestiegen.",
      "De kwartaalomzet van {company} steeg fors.")),
    ("quarterly_earnings", rf"\bafter {COMPANY} reported stronger-than-expected earnings\b",
     ("reported_fact", "{company} reported earnings above expectations.",
      "{company} meldete ein Ergebnis über den Erwartungen.",
      "{company} rapporteerde een resultaat boven verwachting.")),
    ("factory_expansion_plan", rf"\bAccording to (?P<source>{NAME}), {COMPANY} plans to construct an additional "
     r"production facility at its (?P<site>[\w-]+ [\w-]+), with the aim of eventually manufacturing "
     rf"(?:[\w-]+ ){{0,4}}(?P<product>{NAME} robotaxis)\b",
     ("forecast", "According to {source}, {company} plans to expand its {site} site to make {product}.",
      "{source} zufolge plant {company}, den Standort {site} für die Produktion von {product} auszubauen.",
      "Volgens {source} wil {company} de locatie {site} uitbreiden voor de productie van {product}.")),
    ("asset_price_threshold", rf"^\s*(?:Key takeaways\s+)?{COMPANY} traded below \$(?P<value>\d{{1,3}},\d{{3}})"
     r"(?![\w,]|\.\d|\s+(?:million|billion|trillion|[kmb])\b)",
     ("reported_fact", "{company} changed hands for less than {value} dollars.",
      "{company} wurde für weniger als {localized_value} Dollar gehandelt.",
      "{company} werd voor minder dan {localized_value} dollar verhandeld.")),
)
RULES = tuple((event, re.compile(expression, re.I), template) for event, expression, template in RULES)


def claims(article):
    if article["language"] != "en":
        return
    for development in occurrences(article.get("headline") or "", article.get("excerpt") or ""):
        if development.wording:
            yield development, {"field": "excerpt", "start": development.left, "end": development.right}
