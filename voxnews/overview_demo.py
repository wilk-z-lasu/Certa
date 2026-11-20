"""Export a portable, offline event catalogue with verified recordings and claim evidence."""

from html import escape
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import wave
from zipfile import ZIP_DEFLATED, ZipFile

from .official_releases import digest
from .overview_reader import catalogue, get_event, log_html, source_directory
from .trust_briefing import html_view, validate_script


def event_page(event_id):
    return f"events/{digest(event_id)}.html"


def index_html(events, recordings):
    links = []
    for page, profile, lang, seconds in recordings:
        links.append(f'<li><a href="{page}">{escape(profile.title())}</a> · {escape(lang)} · {seconds:.0f} seconds</li>')
    rows = []
    for e in events:
        issue = " · flagged for review" if e["disagreements"] else ""
        topics = escape(" · ".join(e["topics"]))
        rows.append(f'<li><a href="{event_page(e["event_id"])}">{escape(e["title"])}</a> '
                    f'<small>{topics}{issue}</small></li>')
    return ('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>VoxNews | Offline demo</title><style>
body{font:17px/1.5 system-ui;color:#183530;background:#fafbf8;max-width:60rem;margin:3rem auto;padding:0 1rem}
h1,h2{font-family:Georgia,serif}h1{font-size:2.6rem}a{color:#065e56}li{margin:.55rem 0}
small{color:#495854}input{font:inherit;padding:.4rem;max-width:90%}
</style><main><h1>VoxNews</h1><h2>Listen to a briefing</h2><ul>'''
            + "".join(links)
            + f'</ul><h2>Event source logs</h2><p>{len(events):,} events. Open a claim to inspect its sources. '
              'Links to original publications require internet access.</p>'
              '<label>Filter by title, topic or review flag <input type="search" id="filter"></label>'
              '<ul id="events">' + "".join(rows)
            + '''</ul></main><script>
const field=document.getElementById("filter"), rows=document.querySelectorAll("#events li");
field.addEventListener("input",()=>{const q=field.value.trim().toLowerCase();
for(const row of rows) row.hidden=!row.textContent.toLowerCase().includes(q);});
</script></html>''')


def add_recording(archive, directory, index, snapshot, db):
    script = json.loads((directory / "script.json").read_bytes())
    audio = script["audio"]
    clean = {k: v for k, v in script.items() if k != "audio"}
    clean["segments"] = [{k: v for k, v in seg.items() if k not in {"start_seconds", "end_seconds"}}
                         for seg in script["segments"]]
    validate_script(clean, snapshot)
    expected_file = "briefing-" + digest([audio["voice"], clean])[:16] + ".wav"
    if audio["file"] != expected_file or not clean["segments"]:
        raise ValueError("recording must reference the verified script and contain at least one claim")
    wav = directory / expected_file
    with wave.open(str(wav), "rb") as recording:
        seconds = recording.getnframes() / recording.getframerate()
        byte_count = recording.getnframes() * recording.getnchannels() * recording.getsampwidth()
        if len(recording.readframes(recording.getnframes())) != byte_count or round(seconds, 3) != audio["seconds"]:
            raise ValueError(f"incomplete or mismatched recording in {directory}")
    prior_end = None
    for segment in script["segments"]:
        start, end = segment["start_seconds"], segment["end_seconds"]
        if not 0 <= start < end <= round(seconds, 4) or prior_end is not None and start != prior_end:
            raise ValueError("invalid sentence timestamps in recording")
        prior_end = end
        event = get_event(db, segment["event_id"])
        if event["verification_revision"] != segment["event_revision"] or not any(
                i["id"] == segment["claim_id"] and i["draft_use"] == "approved_wording" for i in event["items"]):
            raise ValueError("recording uses a claim outside the approved overview revision")
    if prior_end != round(seconds, 4):
        raise ValueError("recording duration differs from the final sentence timestamp")
    page = f"briefings/{index}/index.html"
    archive.write(wav, f"briefings/{index}/{expected_file}")
    archive.writestr(page, html_view(script))
    return page, clean["profile"], clean["language"], seconds


def export_demo(db, verified, briefings, output):
    target = output.resolve()
    if target.suffix.lower() != ".zip" or source_directory(db) in target.parents:
        raise ValueError("choose a .zip destination outside the licensed feeds")
    if not briefings:
        raise ValueError("include at least one recorded briefing")
    events = catalogue(db)
    snapshot = json.loads(verified.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as f:
        temporary = Path(f.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=4) as archive:
            recordings = [add_recording(archive, directory, n, snapshot, db)
                          for n, directory in enumerate(briefings, 1)]
            for row in events:
                event = get_event(db, row["event_id"], row["revision"])
                archive.writestr(event_page(row["event_id"]), log_html(event))
            archive.writestr("index.html", index_html(events, recordings))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"archive": str(target), "events": len(events), "briefings": len(recordings)}
