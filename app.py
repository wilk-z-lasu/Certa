"""Run with python3 app.py and open the printed local URL."""
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from build_preai import build_preai, read_category_content
from generate_script import ScriptError, generate_script
from md_to_speech import generate_news_audio

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
<title>VoxNews · Your daily briefing</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5ee;color:#193b36;font:1rem/1.5 system-ui}
[hidden]{display:none!important}
main{max-width:900px;margin:auto;padding:clamp(20px,5vw,60px)}
header{border-bottom:2px solid;padding-bottom:12px;font:bold 1.45rem Georgia}
h1{font:normal clamp(2.3rem,6vw,4rem)/1.05 Georgia;margin:40px 0 12px}
#choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,175px),1fr));gap:10px;margin:25px 0}
label{background:white;border:1px solid #a9b8ac;border-radius:8px;padding:12px;display:flex;align-items:center;gap:8px;overflow-wrap:anywhere;cursor:pointer}
label:has(:checked){background:#dbecd9;border-color:#27664d}input{accent-color:#27664d}
label:has(:disabled){background:#efefe8;color:#526761;cursor:default}
footer{display:flex;align-items:center;gap:20px;flex-wrap:wrap}button{border:0;border-radius:7px;background:#205942;color:white;padding:12px 20px;font:inherit;cursor:pointer}
button:disabled{background:#d6ddd5;color:#49584b;cursor:default}

.briefing-card {
  --mint: #c6efa3;
  --paper: #f5faee;
  margin-top: clamp(24px, 6vw, 56px);
  padding: clamp(20px, 5vw, 42px);
  border: 1px solid #23473d;
  border-radius: clamp(20px, 4vw, 34px);
  background: radial-gradient(ellipse at top right, #245245, transparent 65%), #142f29;
  box-shadow: 0 18px 40px #193b3624;
  color: var(--paper);
}
.briefing-card h1 { margin: 0; }
.briefing-card h1:focus { outline: none; }
.stage {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 14px 0 0;
  color: #d2e3d8;
}
.stage::before {
  content: '';
  flex: 0 0 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--mint);
}
.briefing-card[data-phase="audio-error"] .stage::before { background: #ffbfab; }
.waveform {
  display: flex;
  align-items: center;
  gap: clamp(3px, .85vw, 9px);
  height: clamp(90px, 17vw, 132px);
  margin: clamp(24px, 5vw, 36px) 0 clamp(20px, 4vw, 28px);
  padding: 8px 0;
  border-block: 1px solid #b8e6cd29;
  background: linear-gradient(#b8e6cd29, #b8e6cd29) center / 100% 1px no-repeat;
}
.waveform span {
  flex: 1;
  height: var(--height);
  border-radius: 999px;
  background: var(--mint);
  opacity: .55;
}
.waveform[data-animated="true"] span {
  animation: wave 1.25s ease-in-out var(--delay) infinite alternate;
}
@keyframes wave {
  from { transform: scaleY(.34); opacity: .45; }
  to { transform: scaleY(1); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .waveform[data-animated="true"] span { animation: none; }
}
.audio-controls {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid #b8e6cd38;
  border-radius: 16px;
  background: #0e2823;
}
.play-button {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  padding: 0;
  border-radius: 50%;
  background: var(--mint);
  color: #142f29;
}
.play-button:hover { background: #daf7c2; }
.play-button::before {
  content: '';
  margin-left: 3px;
  border-block: 8px solid transparent;
  border-left: 12px solid currentColor;
}
.play-button.is-playing::before {
  width: 12px;
  height: 15px;
  margin: 0;
  border: 0;
  border-inline: 4px solid currentColor;
}
.audio-seek {
  display: block;
  width: 100%;
  height: 24px;
  margin: 0;
  appearance: none;
  background: transparent;
  cursor: pointer;
}
.audio-seek::-webkit-slider-runnable-track {
  height: 5px;
  border-radius: 999px;
  background: linear-gradient(to right, var(--mint) var(--progress, 0%), #507268 var(--progress, 0%));
}
.audio-seek::-moz-range-track {
  height: 5px;
  border-radius: 999px;
  background: linear-gradient(to right, var(--mint) var(--progress, 0%), #507268 var(--progress, 0%));
}
.audio-seek::-webkit-slider-thumb {
  appearance: none;
  width: 15px;
  height: 15px;
  margin-top: -5px;
  border-radius: 50%;
  background: var(--mint);
}
.audio-seek::-moz-range-thumb {
  width: 15px;
  height: 15px;
  border: 0;
  border-radius: 50%;
  background: var(--mint);
}
.audio-times {
  display: flex;
  justify-content: space-between;
  color: #d2e3d8;
  font-size: .8rem;
  font-variant-numeric: tabular-nums;
}
.briefing-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.audio-controls:not([hidden]) + .briefing-actions { margin-top: 16px; }
.briefing-actions button, .briefing-actions a {
  padding: 9px 14px;
  border: 1px solid #b8e6cd66;
  border-radius: 9px;
  background: transparent;
  color: var(--paper);
  font-size: .9rem;
  text-decoration: none;
}
.briefing-actions button:hover, .briefing-actions a:hover { background: #b8e6cd1a; }
.briefing-card :focus-visible { outline: 2px solid var(--mint); outline-offset: 4px; }
.transcript {
  margin-top: 20px;
  padding: clamp(20px, 5vw, 38px);
  border: 1px solid #d5dfd3;
  border-radius: 20px;
  background: #fffefa;
}
.transcript h2 { margin: 0 0 12px; font: normal 1.6rem Georgia; }
#script { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 68ch; line-height: 1.7; }
</style>
<main><header>VoxNews</header><section id="picker"><h1>What interests you today?</h1>
<p>Choose at least 5 categories for your briefing.</p>
<form><div id="choices"></div><footer><button disabled>Save interests</button>
<output id="count">0 selected · Choose 5 more</output></footer></form><p role="status"></p></section>
<section id="failed" hidden>
<h1 id="failure-title" tabindex="-1">Could not prepare your briefing</h1>
<p id="failure-detail" role="status"></p>
<footer><button id="retry" type="button">Try again</button>
<button id="change" type="button">Change categories</button></footer>
</section>
<section id="briefing" aria-labelledby="briefing-title" hidden>
  <div class="briefing-card">
    <h1 id="briefing-title" tabindex="-1">Your daily briefing</h1>
    <p id="stage-status" class="stage" role="status" aria-atomic="true"></p>
    <div class="waveform" aria-hidden="true" data-animated="false"></div>
    <audio id="news-player" preload="metadata" hidden></audio>
    <div class="audio-controls" role="group" aria-label="Briefing playback" hidden>
      <button class="play-button" type="button" aria-label="Play briefing"></button>
      <div>
        <input class="audio-seek" type="range" min="0" value="0" step="any" aria-label="Playback position">
        <div class="audio-times" aria-hidden="true"><span id="elapsed">0:00</span><span id="duration">0:00</span></div>
      </div>
    </div>
    <div class="briefing-actions">
      <button type="button" id="toggle-transcript" aria-controls="transcript" aria-expanded="false" hidden>Show transcript</button>
      <a id="download-audio" download="VoxNews-briefing.wav" hidden>Download WAV</a>
      <button type="button" id="retry-audio" hidden>Retry audio</button>
    </div>
  </div>
  <article class="transcript" id="transcript" aria-labelledby="transcript-title" hidden>
    <h2 id="transcript-title">Transcript</h2>
    <div id="script"></div>
  </article>
</section></main>
<script>
const form=document.querySelector('form'), choices=document.querySelector('#choices'),
button=form.querySelector('button'), statusLine=document.querySelector('#picker [role=status]');
const picker=document.querySelector('#picker'), failed=document.querySelector('#failed'),
failureDetail=document.querySelector('#failure-detail');
const briefing=document.querySelector('#briefing'), briefingTitle=document.querySelector('#briefing-title'),
card=document.querySelector('.briefing-card'), stageStatus=document.querySelector('#stage-status'),
waveform=document.querySelector('.waveform'), transcript=document.querySelector('#transcript'),
transcriptToggle=document.querySelector('#toggle-transcript'), scriptText=document.querySelector('#script');
const player=document.querySelector('#news-player'), controls=document.querySelector('.audio-controls'),
playButton=document.querySelector('.play-button'), seek=document.querySelector('.audio-seek'),
elapsed=document.querySelector('#elapsed'), duration=document.querySelector('#duration'),
download=document.querySelector('#download-audio'), retryAudio=document.querySelector('#retry-audio');

const waveHeights = [8, 14, 23, 36, 56, 76, 48, 28, 42, 66, 88, 70, 53, 33, 49, 73,
  97, 80, 57, 35, 23, 39, 61, 78, 50, 32, 47, 35, 22, 14, 8];
waveHeights.forEach((height, index) => {
  const bar = document.createElement('span');
  bar.style.setProperty('--height', `${height}%`);
  bar.style.setProperty('--delay', `${index * -0.1}s`);
  waveform.append(bar);
});

function setStage(phase, message) {
  card.dataset.phase = phase;
  waveform.dataset.animated = phase === 'writing' || phase === 'narrating';
  if (stageStatus.textContent !== message) stageStatus.textContent = message;
}

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
  briefing.hidden=false;
  setStage('writing', 'Writing your briefing…');
  briefingTitle.focus();
  let errorMessage;
  try {
    const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected())});
    const body=await response.text();
    if (response.ok) {
      scriptText.textContent=body;
      transcriptToggle.hidden=false;
      narrate(body);
      return;
    }
    errorMessage=body;
  } catch {errorMessage='Could not prepare your briefing. Please try again.'}
  setStage('script-error', '');
  briefing.hidden=true;
  failed.hidden=false;
  failureDetail.textContent=errorMessage;
  button.disabled=false;
  document.querySelector('#failure-title').focus();
}
async function narrate(script) {
  retryAudio.hidden = true;
  setStage('narrating', 'Transcript ready. Generating audio…');
  try {
    const response = await fetch('/narrate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({script})
    });
    if (!response.ok) {
      audioFailed('Could not generate the audio.');
      return;
    }
    player.src = URL.createObjectURL(await response.blob());
  } catch {
    audioFailed('Could not load the audio.');
  }
}

function audioFailed(message) {
  const source = player.getAttribute('src');
  if (source) {
    player.removeAttribute('src');
    player.load();
    URL.revokeObjectURL(source);
  }
  controls.hidden = true;
  download.hidden = true;
  download.removeAttribute('href');
  retryAudio.hidden = false;
  setStage('audio-error', message);
}

function formatTime(seconds) {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function updatePosition() {
  if (!Number.isFinite(player.duration) || player.duration <= 0) return;
  seek.value = player.currentTime;
  seek.style.setProperty('--progress', `${100 * player.currentTime / player.duration}%`);
  elapsed.textContent = formatTime(player.currentTime);
  seek.setAttribute('aria-valuetext', `${elapsed.textContent} of ${duration.textContent}`);
}

function updatePlayButton() {
  const playing = !player.paused && !player.ended;
  playButton.classList.toggle('is-playing', playing);
  playButton.setAttribute('aria-label', playing ? 'Pause briefing' : 'Play briefing');
}

player.addEventListener('loadedmetadata', () => {
  if (!Number.isFinite(player.duration) || player.duration <= 0) {
    audioFailed('Could not play the generated audio.');
    return;
  }
  seek.max = player.duration;
  duration.textContent = formatTime(player.duration);
  updatePosition();
  download.href = player.src;
  controls.hidden = false;
  download.hidden = false;
  setStage('ready', 'AI-generated narration');
});
player.addEventListener('error', () => audioFailed('Could not play the generated audio.'));
player.addEventListener('timeupdate', updatePosition);
for (const event of ['play', 'pause', 'ended']) player.addEventListener(event, updatePlayButton);

playButton.onclick = async () => {
  if (!player.paused && !player.ended) {
    player.pause();
    return;
  }
  try {
    await player.play();
    setStage('ready', 'AI-generated narration');
  } catch (error) {
    if (error.name !== 'AbortError' && !controls.hidden) {
      setStage('ready', 'AI-generated narration. Playback could not start.');
    }
  }
};
seek.oninput = () => {
  player.currentTime = seek.valueAsNumber;
  updatePosition();
};
transcriptToggle.onclick = () => {
  transcript.hidden = !transcript.hidden;
  transcriptToggle.setAttribute('aria-expanded', String(!transcript.hidden));
  transcriptToggle.textContent = transcript.hidden ? 'Show transcript' : 'Hide transcript';
};
retryAudio.onclick = () => {
  transcriptToggle.focus();
  narrate(scriptText.textContent);
};

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
        if self.path == "/narrate":
            if self.headers.get_content_type() != "application/json":
                return self.send_error(415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 * 1024:
                    return self.send_error(400)
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(payload.get("script"), str):
                    return self.send_error(400)
                audio = generate_news_audio(DIRECTORY, expected_script=payload["script"]).read_bytes()
            except (ValueError, OSError, RuntimeError) as error:
                self.log_error("Could not generate news audio: %s", error)
                return self.reply(500, "Could not generate the audio. You can still read the transcript.")
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
            return
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
