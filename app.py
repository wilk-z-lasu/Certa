"""Run with python3 app.py and open the printed local URL."""
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from build_preai import build_preai, read_category_content
from generate_script import ScriptError, generate_script

DIRECTORY = Path(__file__).resolve().parent / "user_data"


def categories():
    lines = (DIRECTORY / "all_categories").read_text(encoding="utf-8").splitlines()
    return list(dict.fromkeys(line.strip() for line in lines if line.strip()))


def category_options():
    content = read_category_content(DIRECTORY)
    options = {}
    for name in categories():
        body = content.get(name, "")
        options[name] = isinstance(body, str) and bool(body.strip()) and not re.fullmatch(r"text\d+", body.strip())
    return options


PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Today's interests · VoxNews</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5ee;color:#193b36;font:1rem/1.5 system-ui}
main{max-width:900px;margin:auto;padding:clamp(20px,5vw,60px)}
header{border-bottom:2px solid;padding-bottom:12px;font:bold 1.45rem Georgia}
h1{font:normal clamp(2.3rem,6vw,4rem)/1.05 Georgia;margin:40px 0 12px}
#choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,175px),1fr));gap:10px;margin:25px 0}
label{background:white;border:1px solid #a9b8ac;border-radius:8px;padding:12px;display:flex;align-items:center;gap:8px;overflow-wrap:anywhere;cursor:pointer}
label:has(:checked){background:#dbecd9;border-color:#27664d}input{accent-color:#27664d}
label:has(:disabled){background:#efefe8;color:#526761;cursor:default}
footer{display:flex;align-items:center;gap:20px;flex-wrap:wrap}button{border:0;border-radius:7px;background:#205942;color:white;padding:12px 20px;font:inherit;cursor:pointer}
button:disabled{background:#d6ddd5;color:#49584b;cursor:default}
#script{white-space:pre-wrap;overflow-wrap:anywhere;max-width:65ch;line-height:1.7}
</style>
<main><header>VoxNews</header><section id="picker"><h1>What interests you today?</h1>
<p>Choose at least 5 categories for your briefing.</p>
<form><div id="choices"></div><footer><button disabled>Save interests</button>
<output id="count">0 selected · Choose 5 more</output></footer></form><p role="status"></p></section>
<h1 id="loading" tabindex="-1" hidden>your personalized news is loading</h1>
<section id="failed" hidden>
<h1 id="failure-title" tabindex="-1">Could not prepare your briefing</h1>
<p id="failure-detail" role="status"></p>
<footer><button id="retry" type="button">Try again</button>
<button id="change" type="button">Change categories</button></footer>
</section>
<section id="ready" hidden><h1 id="ready-title" tabindex="-1">Your personalized news</h1>
<article id="script"></article></section></main>
<script>
const form=document.querySelector('form'), choices=document.querySelector('#choices'),
button=form.querySelector('button'), statusLine=document.querySelector('[role=status]');
const picker=document.querySelector('#picker'), loading=document.querySelector('#loading'),
ready=document.querySelector('#ready'), failed=document.querySelector('#failed'),
failureDetail=document.querySelector('#failure-detail');
const selected=()=>Array.from(choices.querySelectorAll(':checked'),box=>box.value);
form.onchange=()=>{
  const n=selected().length;
  document.querySelector('#count').textContent=n+' selected'+(n<5 ? ' · Choose '+(5-n)+' more' : '');
  button.disabled=n<5;
  statusLine.textContent='';
};
async function load(){
  try {
    const response=await fetch('/categories');
    if(!response.ok) throw Error();
    const options=Object.entries(await response.json());
    for(const [name, available] of options){
      const label=document.createElement('label'), box=document.createElement('input');
      box.type='checkbox'; box.value=name;
      box.disabled=!available;
      label.append(box,document.createTextNode(available ? name : name+' (no articles)'));
      choices.append(label);
    }
    if(options.filter(([, available])=>available).length<5) {
      statusLine.textContent='Fewer than five categories have articles. Add reporting to categories.json and refresh.';
    }
  } catch {statusLine.textContent='Could not load categories. Refresh to try again.'}
}
async function saveInterests(){
  if (button.disabled) return;
  button.disabled=true;
  picker.hidden=true;
  failed.hidden=true;
  failureDetail.textContent='';
  loading.hidden=false;
  loading.focus();
  let errorMessage;
  try {
    const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected())});
    const body=await response.text();
    if (response.ok) {
      document.querySelector('#script').textContent=body;
      loading.hidden=true;
      ready.hidden=false;
      document.querySelector('#ready-title').focus();
      return;
    }
    errorMessage=body;
  } catch {errorMessage='Could not prepare your briefing. Please try again.'}
  loading.hidden=true;
  failed.hidden=false;
  failureDetail.textContent=errorMessage;
  button.disabled=false;
  document.querySelector('#failure-title').focus();
}
form.onsubmit=event=>{
  event.preventDefault();
  return saveInterests();
};
document.querySelector('#retry').onclick=saveInterests;
document.querySelector('#change').onclick=()=>{
  failed.hidden=true;
  picker.hidden=false;
  button.focus();
};
load();
</script></html>"""


class Picker(BaseHTTPRequestHandler):
    def reply(self, code, body, kind="text/plain"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.reply(200, PAGE, "text/html")
        elif self.path == "/categories":
            try:
                self.reply(200, json.dumps(category_options()), "application/json")
            except (OSError, ValueError):
                self.reply(500, "Could not load categories and articles.")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/save":
            return self.send_error(404)
        if self.headers.get_content_type() != "application/json":
            return self.send_error(415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                return self.send_error(400)
            picks = json.loads(self.rfile.read(length))
            if not isinstance(picks, list) or not all(isinstance(p, str) for p in picks):
                return self.send_error(400)
            allowed = category_options()
            chosen = set(picks)
            if len(chosen) < 5 or any(not allowed.get(name) for name in chosen):
                return self.reply(400, "Choose at least five different categories that have articles.")
            target = DIRECTORY / "user_liked_categories"
            temp = target.with_suffix(".tmp")
            temp.write_text("".join(p + "\n" for p in allowed if p in chosen), encoding="utf-8")
            temp.replace(target)
        except (ValueError, UnicodeError):
            return self.send_error(400)
        except OSError:
            return self.reply(500, "Could not save your interests.")
        try:
            build_preai(DIRECTORY)
        except (OSError, ValueError) as error:
            self.log_error("Could not generate preAI.md: %s", error)
            return self.reply(500, "Your choices were saved, but briefing preparation failed. Please retry.")
        try:
            script = generate_script(DIRECTORY)
        except ScriptError as error:
            return self.reply(422, str(error))
        except (OSError, UnicodeError) as error:
            self.log_error("Could not generate script.md: %s", error)
            return self.reply(500, "Could not write your briefing script. Please retry.")
        self.reply(200, script)


if __name__ == "__main__":
    with HTTPServer(("127.0.0.1", 0), Picker) as server:
        print(f"Open http://127.0.0.1:{server.server_port} in your browser.", flush=True)
        server.serve_forever()
