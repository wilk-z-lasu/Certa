"""Render an evidence-linked listening view from an immutable verification result."""

import argparse
import calendar
from datetime import date
from html import escape
import json
import locale
from pathlib import Path
from tempfile import TemporaryDirectory
import wave

from .group_events import timestamp
from .official_releases import digest, safe_url
from .verify import ADVICE, qualified_wording, write_atomic


DISCLOSURE = {"en": "This briefing uses a synthetic voice.", "de": "Diese Nachrichten werden mit einer synthetischen Stimme vorgelesen.",
              "nl": "Deze briefing wordt voorgelezen met een synthetische stem."}
COUNTRY = {"en": {"GB": "UK", "DE": "German", "EA": "Euro area", "NL": "Dutch"},
           "de": {"GB": "im Vereinigten Königreich", "DE": "in Deutschland", "EA": "im Euroraum", "NL": "in den Niederlanden"},
           "nl": {"GB": "in het Verenigd Koninkrijk", "DE": "in Duitsland", "EA": "in de eurozone", "NL": "in Nederland"}}
LABEL = {
    "en": {"CPI": "consumer price inflation", "CPIH": "inflation including owner-occupiers’ housing costs",
           "HICP": "harmonised consumer price inflation", "core CPI": "core consumer price inflation",
           "bank lending": "bank lending growth", "Bank Rate": "Bank Rate", "deposit facility rate": "deposit facility rate"},
    "de": {"CPI": "Verbraucherpreisinflation", "CPIH": "Inflation einschließlich der Wohnkosten von Eigentümern",
           "HICP": "harmonisierte Verbraucherpreisinflation", "core CPI": "Kerninflation", "bank lending": "Wachstumsrate der Bankkredite",
           "Bank Rate": "Leitzins der Bank of England", "deposit facility rate": "Einlagenzins der EZB"},
    "nl": {"CPI": "consumentenprijsinflatie", "CPIH": "inflatie inclusief woonkosten van huiseigenaren",
           "HICP": "geharmoniseerde consumentenprijsinflatie", "core CPI": "kerninflatie", "bank lending": "groei van de bankkredieten",
           "Bank Rate": "beleidsrente van de Bank of England", "deposit facility rate": "depositorente van de ECB"},
}
MONTHS = {"en": list(calendar.month_name), "de": ["", *"Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split()],
          "nl": ["", *"januari februari maart april mei juni juli augustus september oktober november december".split()]}


def attributed_wording(kind, publisher, text, lang):
    if lang == "en" and kind == "reported_fact":
        return f"{publisher} reports: {text}"
    labels = {
        "en": {"forecast": "reports a forecast", "allegation": "reports an allegation", "analysis": "reports analysis"},
        "nl": {"reported_fact": "meldt het volgende", "forecast": "meldt een prognose",
               "allegation": "bericht over een beschuldiging", "analysis": "bericht over een analyse"},
        "de": {"reported_fact": "berichtet Folgendes", "forecast": "berichtet über eine Prognose",
               "allegation": "berichtet über einen Vorwurf", "analysis": "berichtet über eine Analyse"},
    }
    return f"{publisher} {labels[lang][kind]}. {text}"


def spoken(claim, lang, *, version=1):
    if not claim["approved"] or claim["article_state"] != "supported" or not claim["support"]:
        raise ValueError("segment lacks approved article evidence")
    if claim["kind"] != "official_figure":
        verified = (claim.get("review", {}).get("decision") == "supported"
                    or claim.get("method") == "editorial_rules")
        if (lang != "en" or not qualified_wording(claim["kind"], claim["wording"])
                or not verified
                or ADVICE.search(claim["wording"])):
            raise ValueError("no approved wording for this language")
        return attributed_wording(claim["kind"], claim["support"][0]["publisher"], claim["wording"], lang)
    f = claim["fact"]
    if claim["official_state"] != "matched" or not claim["official"] or any(
            cell["value"] != f["value"] or cell["unit"] != f["unit"] for cell in claim["official"]):
        raise ValueError("official figure has inconsistent evidence")
    return spoken_figure(f, lang, version=version)


def spoken_figure(f, lang, *, version=1):
    """Render an already approved official observation in the listener's language."""
    value = f["value"] if lang == "en" else f["value"].replace(".", ",")
    country, measure = COUNTRY[lang][f["geo"]], LABEL[lang][f["measure"]]
    if version >= 2:
        measure = {
            "en": {"CPI": "headline consumer price inflation covering all CPI items",
                   "core CPI": "core consumer price inflation excluding energy, food, alcohol and tobacco"},
            "de": {"CPI": "gesamte Verbraucherpreisinflation",
                   "core CPI": "Kerninflation ohne Energie, Nahrungsmittel, Alkohol und Tabak"},
            "nl": {"CPI": "totale consumentenprijsinflatie",
                   "core CPI": "kerninflatie exclusief energie, voedingsmiddelen, alcohol en tabak"},
        }[lang].get(f["measure"], measure)
    level = f["basis"] == "level"
    when = date.fromisoformat(f["period"] if level else f["period"] + "-01")
    month = MONTHS[lang][when.month]
    period = f"{month} {when.year}"
    if level:
        if lang == "en":
            bank = "Bank of England" if f["geo"] == "GB" else "European Central Bank"
            return f"The {bank} set its {measure} at {value} percent on {when.day} {period}."
        if lang == "de":
            return f"Der {measure} lag am {when.day}. {period} bei {value} Prozent."
        return f"De {measure} stond op {when.day} {period} op {value} procent."
    if lang == "en":
        basis = "year on year" if f["basis"] == "yoy" else "month on month"
        return f"{country} {measure} was {value} percent {basis} in {period}."
    if lang == "de":
        basis = "gegenüber dem Vorjahresmonat" if f["basis"] == "yoy" else "gegenüber dem Vormonat"
        return f"Die {measure} {country} lag im {period} bei {value} Prozent {basis}."
    basis = "op jaarbasis" if f["basis"] == "yoy" else "op maandbasis"
    return f"De {measure} {country} bedroeg in {period} {value} procent {basis}."


def compose(snapshot, profile, lang, region=None):
    segments, used, events_used = [], set(), set()
    options = []
    for event in snapshot["events"]:
        if event["revision"] != digest({k: v for k, v in event.items() if k != "revision"}):
            raise ValueError("event evidence differs from the saved verification revision")
        for claim in event["claims"]:
            if not claim["approved"] or (lang != "en" and "fact" not in claim):
                continue
            fact = claim.get("fact", {})
            if region and fact.get("geo") != region:
                continue
            latest = max(timestamp(r["published_at"]) for r in claim["support"])
            basis = fact.get("basis")
            priority = (basis == "level" if profile == "rates" else False,
                        latest, basis == "yoy", fact.get("measure") in {"CPI", "HICP"}, claim["id"])
            options.append((priority, event, claim))
    for _, event, claim in sorted(options, key=lambda item: item[0], reverse=True):
        key = digest(claim.get("fact") or claim["wording"])
        if key in used or (profile == "headlines" and event["event_id"] in events_used):
            continue
        segments.append({"claim_id": claim["id"], "event_id": event["event_id"], "event_revision": event["revision"],
                         "text": spoken(claim, lang), "support": claim["support"], "official": claim["official"]})
        used.add(key)
        events_used.add(event["event_id"])
        if len(segments) == (2 if profile == "headlines" else 6):
            break
    return {"profile": profile, "language": lang, "region": region, "cutoff_exclusive": snapshot["cutoff_exclusive"],
            "disclosure": DISCLOSURE[lang], "segments": segments}


def validate_script(script, snapshot):
    """Bind the exact TTS input to its approved wording, evidence and event revision."""
    expected = compose(snapshot, script["profile"], script["language"], script["region"])
    if script != expected:
        raise ValueError("script differs from approved claims or evidence")


def make_audio(script, directory):
    try:
        import win32com.client
    except ImportError as error:
        raise ValueError("WAV export requires Windows SAPI and pywin32; the HTML view also supports browser speech") from error
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for token in voice.GetVoices():
        codes = token.GetAttribute("Language").split(";")
        if any(locale.windows_locale.get(int(code, 16), "").split("_")[0] == script["language"] for code in codes):
            voice.Voice = token
            break
    else:
        raise ValueError(f'no installed SAPI voice for {script["language"]}')
    voice_name = token.GetDescription()
    lines = [script["disclosure"], *(s["text"] for s in script["segments"])]
    with TemporaryDirectory(dir=directory) as temp:
        temp = Path(temp)
        whole = temp / "briefing.wav"
        positions, frames, fmt = [], 0, None
        with wave.open(str(whole), "wb") as output:
            for index, line in enumerate(lines):
                stream = win32com.client.Dispatch("SAPI.SpFileStream")
                clip = temp / f"{index}.wav"
                stream.Open(str(clip.resolve()), 3, False)
                try:
                    voice.AudioOutputStream = stream
                    voice.Speak(line, 16)  # SVSFIsNotXML
                finally:
                    stream.Close()
                with wave.open(str(clip), "rb") as src:
                    params = src.getparams()[:3]
                    if not fmt:
                        fmt = params
                        output.setnchannels(fmt[0])
                        output.setsampwidth(fmt[1])
                        output.setframerate(fmt[2])
                    if fmt != params or not src.getnframes():
                        raise ValueError("speech engine returned an incompatible or empty clip")
                    positions.append(round(frames / fmt[2], 4))
                    frames += src.getnframes()
                    output.writeframes(src.readframes(src.getnframes()))
        name = "briefing-" + digest([voice_name, script])[:16] + ".wav"
        whole.replace(directory / name)
    for index, segment in enumerate(script["segments"], 1):
        segment["start_seconds"] = positions[index]
        segment["end_seconds"] = positions[index + 1] if index + 1 < len(positions) else round(frames / fmt[2], 4)
    script["audio"] = {"file": name, "voice": voice_name, "seconds": round(frames / fmt[2], 3)}


def html_view(script):
    def link(url, label):
        return f'<a href="{escape(safe_url(url), quote=True)}">{escape(label)}</a>'
    rows = []
    for idx, s in enumerate(script["segments"], 1):
        sources = []
        for ref in s["support"]:
            loc = f'{ref["field"]} [{ref["start"]}, {ref["end"]})'
            if ref.get("context_span"):
                loc += " · context " + str(ref["context_span"])
            sources.append(f'<li>{link(ref["permalink"], ref["publisher"])} · {escape(loc)}</li>')
        for cell in s["official"]:
            sources.append(f'<li>{link(cell["url"], cell["issuer"])} · {escape(cell["locator"])}</li>')
        rows.append(f'<section><button data-offset="{s.get("start_seconds", 0)}" aria-label="Play sentence {idx}">Play</button>'
                    f'<p class="line" lang="{script["language"]}">{escape(s["text"])}</p>'
                    f'<details><summary>Source evidence</summary><ul>{"".join(sources)}</ul>'
                    f'<small>Claim {escape(s["claim_id"][:16])} · event revision {escape(s["event_revision"][:16])}</small>'
                    '</details></section>')
    player = (f'<audio controls src="{escape(script["audio"]["file"])}"></audio>' if "audio" in script
              else '<button id="all">Listen to briefing</button>')
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>VoxNews | Verified briefing</title><style>'
            'body{font:17px/1.5 system-ui;color:#192c36;background:#f8faf9;max-width:48rem;margin:3rem auto;padding:0 1.2rem}'
            'h1{font:2.4rem Georgia,serif;margin:.2rem 0}header,section{padding:1.2rem 0;border-bottom:1px solid #ccd6d5}'
            'button,summary{cursor:pointer}button{font:inherit;border:1px solid #35605a;border-radius:4px;padding:.3rem .8rem;background:white}'
            'section button{float:right;margin-left:1rem}.line{margin:0 0 .8rem}a{color:#07564c}small{color:#47575c}'
            'audio{width:100%}</style><main><header><small>VoxNews</small>'
            f'<h1>{"Rates briefing" if script["profile"] == "rates" else "Headlines"}</h1>'
            f'<p id="disclosure" lang="{script["language"]}">{escape(script["disclosure"])}</p>{player}</header>'
            + ("".join(rows) or '<p>No approved claims for this selection.</p>') +
            '<p id="status" role="status"></p></main><script>'
            'const audio=document.querySelector("audio"), lines=[...document.querySelectorAll(".line")];'
            'function speak(items){if(!("speechSynthesis" in window)){document.querySelector("#status").textContent="Speech playback is unavailable in this browser.";return;}'
            'speechSynthesis.cancel();for(const el of items){const u=new SpeechSynthesisUtterance(el.textContent);u.lang=el.lang;speechSynthesis.speak(u);}}'
            'document.querySelectorAll("[data-offset]").forEach((b,i)=>b.onclick=()=>{if(audio){audio.currentTime=Number(b.dataset.offset);audio.play();}else speak([lines[i]]);});'
            'const all=document.querySelector("#all");if(all)all.onclick=()=>speak([document.querySelector("#disclosure"),...lines]);'
            '</script></html>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified", type=Path, default=Path("output/verification.json"))
    parser.add_argument("--profile", choices=("headlines", "rates"), required=True)
    parser.add_argument("--language", choices=DISCLOSURE, default="en")
    parser.add_argument("--region", choices=("GB", "DE", "NL", "EA"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--wav", action="store_true")
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.verified.read_text(encoding="utf-8"))
        script = compose(snapshot, args.profile, args.language, args.region)
        validate_script(script, snapshot)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        if args.wav and script["segments"]:
            make_audio(script, args.out_dir)
        write_atomic(args.out_dir / "script.json", json.dumps(script, ensure_ascii=False, indent=2))
        write_atomic(args.out_dir / "index.html", html_view(script))
        print(f'{len(script["segments"])} approved segments in {args.out_dir / "index.html"}')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"briefing failed: {error}\n")


if __name__ == "__main__":
    main()
