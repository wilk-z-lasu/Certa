"""Export recorded daily editions and audited claim evidence as one local HTML file."""

import argparse
from base64 import b64encode
from contextlib import closing
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import re
import sqlite3

from .evaluate import text_audit
from .official_releases import safe_url
from .verify import write_atomic


def recording(db, catalogue, directory, name, edition, media):
    row = db.execute("SELECT listener,draft,briefing FROM delivery WHERE edition=?", (edition,)).fetchone()
    if row is None or not re.fullmatch(r"[0-9a-f]{64}", edition):
        raise ValueError("Unknown recorded edition")
    listener, draft, briefing = row[0], json.loads(row[1]), json.loads(row[2])
    audit = text_audit(catalogue, draft, briefing, include_quotes=True)
    claims = {item["claim_id"]: item for item in audit["checked"]}
    base = directory / "listeners" / listener
    manifest = json.loads((base / edition / "audio.json").read_bytes())
    if manifest["edition"] != edition or len(manifest["segments"]) != len(briefing["spoken_segments"]):
        raise ValueError("Audio manifest differs from the saved edition")
    lines = []
    start = 0
    for block, part in zip(briefing["spoken_segments"], manifest["segments"]):
        if (any(part.get(key) != value for key, value in block.items())
                or not math.isclose(part["start_seconds"], start, abs_tol=.001)
                or not 0 < part["duration"] < 3600
                or not re.fullmatch(r"[0-9a-f]{64}\.mp3", part["file"])):
            raise ValueError("Segment differs from its validated text or timing")
        raw = (base / "audio" / part["file"]).read_bytes()
        key = sha256(raw).hexdigest()
        if key != part["sha256"]:
            raise ValueError("Audio digest differs from its saved recording")
        if key not in media:
            media[key] = "data:audio/mpeg;base64," + b64encode(raw).decode("ascii")
        evidence = ""
        if "claim_id" in block:
            item = claims[block["claim_id"]]
            refs = []
            for ref in item["evidence"]:
                loc = ref.get("locator") or f'{ref["field"]} · characters {ref["start"]}–{ref["end"]}'
                quote = f'<blockquote>{escape(ref["quote"])}</blockquote>' if ref.get("quote") else ""
                refs.append(f'<li><a href="{escape(safe_url(ref["url"]))}">{escape(ref["label"])}</a> · {escape(loc)}{quote}</li>')
            evidence = ('<details><summary>Claim evidence</summary><ul>' + "".join(refs) +
                        '</ul><small>Event revision ' + escape(item["revision"]) + '</small></details>')
        seconds = int(start)
        lines.append(f'<li><button data-audio="{key}" aria-label="Play from {seconds} seconds">'
                     f'{seconds // 60}:{seconds % 60:02}</button><div>{escape(block["text"])}{evidence}</div></li>')
        start += part["duration"]
    if not math.isclose(start, manifest["duration"], abs_tol=.001):
        raise ValueError("Recording duration differs from the manifest")
    return (f'<section hidden lang="{escape(briefing["selection"]["language"])}"><h2>{escape(name)}</h2>'
            f'<p>{escape(briefing["date"])} · {int(start) // 60}:{int(start) % 60:02} · Synthetic narration</p>'
            '<ol>' + "".join(lines) + '</ol></section>')


def export(catalogue, directory, editions, output):
    media, panels, choices = {}, [], []
    with closing(sqlite3.connect((directory / "listeners.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for index, (name, edition) in enumerate(editions):
            panels.append(recording(db, catalogue, directory, name, edition, media))
            choices.append(f'<option value="{index}">{escape(name)}</option>')
    html = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Certa · Recorded briefings</title><style>*{box-sizing:border-box}body{margin:auto;max-width:52rem;padding:2rem 1.25rem 4rem;
color:#163d33;background:#f8f5eb;font:17px/1.55 system-ui}h1,h2{font:normal 2.3rem Georgia,serif}
h1{border-bottom:2px solid;padding-bottom:.6em}select,button{font:inherit;padding:.35em .65em;color:inherit}
label{display:block}audio{width:100%;margin:1.2em 0 .4em}ol{padding:0;list-style:none}ol>li{display:flex;align-items:start;
gap:1em;border-top:1px solid #b9c4b7;padding:1em 0}button{cursor:pointer;border:1px solid #a4b7a6;border-radius:.3em}
button[aria-current]{background:#153f33;color:white}summary,a{color:#125b42}summary{cursor:pointer}
small{overflow-wrap:anywhere}details{font-size:.85em}</style>
<main><h1>Certa</h1><label>Recorded listener <select id="chooser">""" + "".join(choices) + """</select></label>
<audio controls preload="metadata"></audio>""" + "".join(panels) + """</main><script>
const media=""" + json.dumps(media) + """;
const player=document.querySelector('audio'),chooser=document.querySelector('#chooser'),sections=[...document.querySelectorAll('section')];
let queue=[],current=0;
function select(index,play){
  if(queue[current])queue[current].removeAttribute('aria-current');
  current=index;queue[current].setAttribute('aria-current','true');player.src=media[queue[current].dataset.audio];
  if(play)player.play().catch(()=>{});
}
function show(){
  player.pause();sections.forEach((section,i)=>section.hidden=i!==chooser.selectedIndex);
  queue=[...sections[chooser.selectedIndex].querySelectorAll('button')];
  queue.forEach((button,i)=>button.onclick=()=>select(i,true));select(0,false);
}
chooser.onchange=show;player.onended=()=>{if(current+1<queue.length)select(current+1,true)};show();
</script></html>"""
    write_atomic(output, html)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("output/event-overviews.sqlite3"))
    p.add_argument("--listeners", type=Path, default=Path("user_data"))
    p.add_argument("--edition", action="append", nargs=2, metavar=("NAME", "EDITION_ID"), required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.suffix.lower() != ".html":
        p.error("Choose an HTML output file.")
    try:
        export(args.db, args.listeners, args.edition, args.output)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        p.exit(1, f"Pitch export failed: {exc}\n")


if __name__ == "__main__":
    main()
