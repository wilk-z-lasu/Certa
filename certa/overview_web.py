"""Read-only local editorial catalogue. Public evidence logs omit licensed body text."""

from contextlib import closing
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlencode, urlsplit

from .overview_material import SECTIONS
from .overview_reader import catalogue, connect, get_event, log_html, packet
from .topic_rules import TOPICS


def link(path, **params):
    return escape(path + "?" + urlencode(params), quote=True)


def page(title, body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{escape(title)} | Certa</title><style>'
            ':root{font:16px/1.5 system-ui;color:#18352e;background:#fafbf7}body{max-width:64rem;padding:1.5rem;margin:auto}'
            'nav,header,article,details{border-bottom:1px solid #ced7cf;padding:.85rem 0}nav{font-weight:700}'
            'h1,h2{font-family:Georgia,serif;font-weight:500;line-height:1.2}h1{font-size:2.4rem}'
            'a{color:#075c4f}li{margin:.35rem 0}summary{cursor:pointer}input,select,button{font:inherit;padding:.3rem}'
            'form{display:flex;gap:.7rem;align-items:end;flex-wrap:wrap}label{display:grid}small{color:#465c51}'
            'article p{max-width:77ch}code{overflow-wrap:anywhere}</style><nav><a href="/">Certa</a> / Editorial research</nav>'
            f'<main>{body}</main></html>')


def render(db, path, params):
    if path == "/":
        topic, query = params.get("topic",""), params.get("q","")
        rows = catalogue(db,topic=topic,query=query,disputes=params.get("disputes") == "yes")
        options = "".join(f'<option value="{k}" {"selected" if topic == k else ""}>{k.replace("_"," ")}</option>' for k in TOPICS)
        page_no = max(1, int(params.get("page","1")))
        start = (page_no-1)*60
        body = ('<header><h1>Event overviews</h1><form><label>Find an event<input name="q" value="'
                +escape(query,quote=True)+'"></label><label>Category<select name="topic"><option value="">All categories</option>'
                +options+'</select></label><label><span>Disagreements only</span><input name="disputes" type="checkbox" value="yes" '
                +('checked' if params.get("disputes")=="yes" else '')+'></label><button>Filter</button></form></header>'
                +f'<p>{len(rows):,} matching events</p>')
        for r in rows[start:start+60]:
            body += (f'<article><a href="{link("/event", id=r["event_id"])}">{escape(r["title"])}</a><br><small>'
                     f'{escape(r["latest"][:10])} · {escape(", ".join(r["topics"]).replace("_"," "))}'
                     + (f' · {r["disagreements"]} flagged' if r["disagreements"] else '') + '</small></article>')
        for n, label in ((page_no-1,"Previous"),(page_no+1,"Next")):
            if n > 0 and (n-1)*60 < len(rows):
                body += f' <a href="{link("/", **{**params, "page":n})}">{label}</a>'
        return "text/html", page("Event overviews",body)
    if path not in {"/event","/sources","/packet"}:
        raise ValueError("unknown page")
    e = get_event(db, params["id"],params.get("revision"))
    if path == "/sources":
        return "text/html", log_html(e)
    depth, focus, lang = params.get("depth","standard"), params.get("focus"), params.get("language","en")
    data = packet(db,e,depth=depth,focus=[focus] if focus else [],language=lang)
    if path == "/packet":
        return "application/json", json.dumps(data,ensure_ascii=False)
    base = {"id":e["event_id"],"revision":e["revision"]}
    body = (f'<header><small>{escape(", ".join(e["topics"]).replace("_"," "))}</small><h1>{escape(e["title"])}</h1>'
            f'<p>{len(e["members"])} articles · {e["origin_count"]} reporting origins · '
            f'<a href="{link("/sources",**base)}">Public source log</a> · '
            f'<a href="{link("/packet",**base,depth=depth,language=lang,focus=focus or "")}">Writer packet</a></p></header>')
    body += '<form method="get"><input type="hidden" name="id" value="'+escape(e["event_id"],quote=True)+'">'
    body += '<input type="hidden" name="revision" value="'+escape(e["revision"],quote=True)+'">'
    for name, choices, value in (("depth",("brief","standard","technical","full"),depth),
                                 ("focus",("",*SECTIONS),focus or ""),("language",("en","de","nl"),lang)):
        body += f'<label>{name.capitalize()}<select name="{name}">' + "".join(
            f'<option value="{k}" {"selected" if value==k else ""}>{k or "All sections"}</option>' for k in choices) +'</select></label>'
    body += '<button>Apply</button></form>'
    if e["disagreements"]:
        body += '<h2>Disagreements and revisions</h2><ul>'
        for d in e["disagreements"]:
            refs = ' · '.join(f'<a href="{link("/sources",**base)}#c{k}">Evidence {n}</a>'
                              for n,k in enumerate(d["claim_ids"],1))
            body += f'<li>{escape(d["kind"].replace("_"," "))} · {refs}</li>'
        body += '</ul>'
    body += '<h2>Editorial material</h2><p>Source passages are for internal research. Check new wording before narration.</p>'
    for item in data["items"]:
        txt = item.get("summary") or item.get("source_context") or item.get("source_statement","")
        body += (f'<article><small>{escape(" · ".join(item["sections"]+item["qualifiers"]))}</small>'
                 f'<p lang="{escape(item["language"])}">{escape(txt)}</p><small>{escape(item["draft_use"].replace("_"," "))} · '
                 f'<a href="{link("/sources",**base)}#c{item["id"]}">Claim sources</a></small></article>')
    return "text/html", page(e["title"],body)


def serve(path, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = self.headers.get("Host","").split(":")[0]
            if host not in {"localhost","127.0.0.1"}:
                self.send_error(403)
                return
            req = urlsplit(self.path)
            try:
                with closing(connect(path)) as db:
                    mime, body = render(db,req.path,{k:v[-1] for k,v in parse_qs(req.query).items()})
            except (ValueError, KeyError, OSError):
                self.send_error(404)
                return
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",mime+"; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","private, no-store")
            self.send_header("Referrer-Policy","no-referrer")
            self.end_headers()
            self.wfile.write(raw)
    with ThreadingHTTPServer(("127.0.0.1",port),Handler) as server:
        print(f"Editorial catalogue at http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
