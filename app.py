"""Run with python3 app.py and open the printed local URL."""
import json
import re
import sqlite3
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from build_preai import NoCoverage, category_options, database_path, make_draft, preferences
from generate_script import ScriptError, compose_draft, save_briefing
from md_to_speech import generate_news_audio
from certa import daily_web
from certa import providers
from certa.editions import picker_options
from certa.listeners import people, persona_profile, storage
from certa.topic_rules import TOPIC_LABELS

DIRECTORY = Path(__file__).resolve().parent / "user_data"
# The CLI and legacy audio route also use the latest script in this directory.
BRIEFING_FILES = Lock()


PAGE = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Certa · Your daily briefing</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f5ee;color:#193b36;font:1rem/1.5 system-ui}
[hidden]{display:none!important}
main{max-width:900px;margin:auto;padding:clamp(20px,5vw,60px)}
header{border-bottom:2px solid;padding-bottom:12px;font:bold 1.45rem Georgia}
h1{font:normal clamp(2.3rem,6vw,4rem)/1.05 Georgia;margin:40px 0 12px}
#choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,175px),1fr));gap:10px;margin:25px 0}
#choices label{background:white;border:1px solid #a9b8ac;border-radius:8px;padding:12px;display:flex;align-items:center;gap:8px;cursor:pointer}
#choices label:has(:checked){background:#dbecd9;border-color:#27664d}input{accent-color:#27664d}
#choices label:has(:disabled){background:#efefe8;color:#526761;cursor:default}
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
.listener-picker, .preference-fields, .topic-weights {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr)); gap: 12px;
}
.listener-picker {
  align-items: end; margin: 0 0 20px; padding: 16px; border: 1px solid #d5dfd3;
  border-radius: 14px; background: #fffefa;
}
.listener-actions { display: flex; flex-wrap: wrap; align-items:center; gap:8px; }
.listener-picker dialog { max-width: min(26rem,90vw); padding: 20px; border: 1px solid #b4bfb8; border-radius: 12px; }
.listener-picker dialog p { margin-bottom: 16px; overflow-wrap: anywhere; }
.listener-picker dialog::backdrop { background: #10251d66; }
.listener-picker p { grid-column: 1 / -1; margin: 0; }
.listener-picker p:empty { display: none; }
.preference-fields { margin-bottom: 16px; }
.preference-fields label, .listener-picker label, .topic-weights label { display: grid; gap: 5px; min-width: 0; }
.preference-fields select, .preference-fields input, .listener-picker select,
.listener-picker input, .topic-weights input {
  width: 100%; min-width: 0; padding: 10px; border: 1px solid #a9b8ac; border-radius: 8px;
  background: white; color: inherit; font: inherit;
}
#picker fieldset { min-width: 0; padding: 0; border: none; }
#picker legend, .listener-picker label, .preference-fields label { font-weight: 600; }
#picker #choices { margin-top: 10px; }
.topic-weights { padding-block: 12px; }
#picker :focus-visible { outline: 3px solid #27664d; outline-offset: 3px; }
</style>
<main><header>Certa</header><section id="picker"><h1>What interests you today?</h1>
<!--TOPIC_FORM-->
</section>
<section id="failed" hidden>
<h1 id="failure-title" tabindex="-1">Could not prepare your briefing</h1>
<p id="failure-detail" role="status"></p>
<footer><button id="retry" type="button">Try again</button>
<button id="change" type="button">Edit preferences</button></footer>
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
      <a id="download-audio" download="Certa-briefing.wav" hidden>Download WAV</a>
      <button type="button" id="retry-audio" hidden>Retry audio</button>
      <button type="button" id="listen" hidden>Generate audio</button>
      <button type="button" id="edit">Change interests</button>
    </div>
    <section id="daily-audio" hidden><audio controls></audio><ol></ol></section>
  </div>
  <article class="transcript" id="transcript" aria-labelledby="transcript-title" hidden>
    <h2 id="transcript-title">Transcript</h2>
    <div id="script"></div>
  </article>
  <details id="check-in" hidden><summary>Daily check-in</summary>
  <form id="feedback-form">
    <label>Was this useful? <select name="useful"><option value="">Skip question</option><option value="yes">Yes</option><option value="no">No</option></select></label>
    <label>Next briefing length <select name="length"><option value="same">Keep length</option><option value="less">Shorter</option><option value="more">Longer</option></select></label>
    <label>Next briefing depth <select name="depth"><option value="same">Keep depth</option><option value="less">Less detail</option><option value="more">More detail</option></select></label>
    <label>More about <select name="more"><option value="">Choose topic</option></select></label>
    <label>Less about <select name="less"><option value="">Choose topic</option></select></label>
    <button>Save feedback</button><button type="button" id="skip-feedback">Skip today</button>
    <button type="button" id="undo-feedback">Undo adjustment</button><p role="status"></p>
  </form></details>
</section></main>
<script>
const form=document.querySelector('form'), choices=document.querySelector('#choices'),
button=form.querySelector('button[type=submit]');
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
const region=document.querySelector('#region'), language=document.querySelector('#language');
let currentBriefing=null;
function updateCount(){
  const n=selected().length;
  document.querySelector('#count').textContent=n+' selected';
  button.disabled=n===0 || form.dataset.adding==='true';
}
choices.onchange=updateCount;
const daily=form.dataset.daily==='true';
const persona=form.elements.namedItem('persona');
const day=document.querySelector('#day');
if(!daily) region.onchange=language.onchange=()=>form.submit();
async function post(path, payload){
  if(persona?.value && !path.startsWith('/api/people')) path+='?'+new URLSearchParams({persona:persona.value});
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!response.ok) throw Error(await response.text());
  return response.json();
}
function settings(){
  const weights={};
  for(const field of form.querySelectorAll('[data-weight]')) weights[field.dataset.weight]=Number(field.value);
  return {topics:selected(), region:region.value||null, language:language.value, minutes:Number(form.minutes.value),
          depth:form.depth.value, weights, version:Number(form.dataset.version)};
}
async function saveProfile(){
  const profile=await post('/api/profile',settings());
  form.dataset.version=profile.version;
  return profile;
}
if(daily){
  const chooser=document.querySelector('#persona-chooser');
  chooser.onchange=()=>{
    const params=new URLSearchParams({date:day.value});
    if(chooser.value) params.set('persona',chooser.value);
    else params.set('persona','');
    window.location.assign('/?'+params);
  };
  const newName=document.querySelector('#new-listener');
  const add=document.querySelector('#add-listener');
  const remove=document.querySelector('#remove-listener');
  const removalDialog=document.querySelector('#remove-dialog');
  const confirmRemoval=document.querySelector('#confirm-remove');
  const cancel=document.querySelector('#cancel-listener');
  const save=document.querySelector('#save-profile');
  const listenerStatus=document.querySelector('#listener-status');
  function setAdding(adding){
    form.dataset.adding=adding;
    newName.hidden=!adding;
    cancel.hidden=!adding || !chooser.options.length;
    remove.hidden=adding || !chooser.options.length;
    save.disabled=adding;
    add.textContent=adding?'Create listener':'Add user';
    updateCount();
  }
  if(!chooser.options.length){
    chooser.disabled=true;
    setAdding(true);
    listenerStatus.textContent='Create a listener to get a briefing.';
  }
  remove.onclick=()=>{
    document.querySelector('#remove-question').textContent='Remove '+chooser.selectedOptions[0].textContent+' from your listener list?';
    removalDialog.showModal();
  };
  document.querySelector('#cancel-remove').onclick=()=>removalDialog.close();
  confirmRemoval.onclick=async()=>{
    confirmRemoval.disabled=true;
    try{
      await post('/api/people/remove',{id:chooser.value});
      window.location.replace('/?'+new URLSearchParams({date:day.value}));
    }catch(e){
      removalDialog.close(); listenerStatus.textContent=e.message;
    }finally{confirmRemoval.disabled=false;}
  };
  cancel.onclick=()=>{ window.location.reload(); };
  newName.querySelector('input').onkeydown=event=>{
    if(event.key==='Enter'){event.preventDefault(); add.click();}
  };
  add.onclick=async()=>{
    if(newName.hidden){
      setAdding(true);
      listenerStatus.textContent='Enter a name and set preferences below.';
      newName.querySelector('input').focus();
      return;
    }
    const input=newName.querySelector('input');
    if(!input.value.trim()){listenerStatus.textContent='Enter a listener name.'; input.focus(); return;}
    if(!selected().length){listenerStatus.textContent='Choose at least one topic.'; return;}
    if(!form.reportValidity()) return;
    chooser.disabled=add.disabled=cancel.disabled=true;
    try{
      const person=await post('/api/people',{name:input.value,settings:settings()});
      window.location.assign('/?'+new URLSearchParams({persona:person.id,date:day.value}));
    }catch(e){listenerStatus.textContent=e.message; chooser.disabled=!chooser.options.length; add.disabled=cancel.disabled=false;}
  };
  save.onclick=async()=>{
    if(!form.reportValidity()) return;
    try{await saveProfile(); statusMessage('Preferences saved.');}catch(e){statusMessage(e.message);}
  };
  const feedback=document.querySelector('#feedback-form');
  for(const topic of choices.querySelectorAll('input')){
    for(const field of [feedback.more,feedback.less]) field.add(new Option(topic.parentNode.textContent,topic.value));
  }
  async function submitFeedback(answers,undo=false){
    try{
      const profile=await post('/api/feedback'+(undo?'/undo':''),{edition:currentBriefing.edition,answers});
      feedback.querySelector('[role=status]').textContent=undo?'Adjustment undone.':(answers.skip?'Check-in skipped.':profile.reason);
      form.dataset.version=profile.version;
      form.minutes.value=profile.minutes; form.depth.value=profile.depth;
      for(const box of choices.querySelectorAll('input')) box.checked=profile.topics.includes(box.value);
      for(const w of form.querySelectorAll('[data-weight]')) w.value=profile.weights[w.dataset.weight]||0;
      updateCount();
    }catch(e){feedback.querySelector('[role=status]').textContent=e.message;}
  }
  feedback.onsubmit=e=>{e.preventDefault();submitFeedback({useful:feedback.useful.value||null,length:feedback.elements.namedItem('length').value,
    depth:feedback.depth.value,more:feedback.more.value?[feedback.more.value]:[],less:feedback.less.value?[feedback.less.value]:[]});};
  document.querySelector('#skip-feedback').onclick=()=>submitFeedback({skip:true});
  document.querySelector('#undo-feedback').onclick=()=>submitFeedback(null,true);
}
function statusMessage(text){document.querySelector('#picker-status').textContent=text;}
function renderTranscript(result){
  scriptText.replaceChildren();
  if(!result.spoken_segments) scriptText.append(document.createTextNode(result.script.split('\n\n')[0]));
  for(const segment of result.spoken_segments||result.segments){
    const p=document.createElement('p');
    p.append(document.createTextNode(segment.text+' '));
    const seen=new Set();
    for(const source of segment.sources||[]){
      if(seen.has(source.url)) continue;
      seen.add(source.url);
      const link=document.createElement('a');
      link.href=source.url; link.textContent=source.label;
      p.append(link, document.createTextNode(' '));
    }
    if(segment.claim_id && segment.event_id && segment.revision){
      const a=document.createElement('a'); a.textContent='Claim evidence';
      const claim=encodeURIComponent(segment.claim_id);
      a.href='/evidence/'+encodeURIComponent(segment.event_id)+'/'+encodeURIComponent(segment.revision)+'?claim='+claim+'#c'+claim;
      p.append(a);
    }
    scriptText.append(p);
  }
};
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
    if(daily){
      const profile=await saveProfile();
      currentBriefing=await post('/api/briefing',{date:day.value,version:profile.version});
      renderTranscript(currentBriefing);
      const name=document.querySelector('#persona-chooser').selectedOptions[0]?.textContent;
      briefingTitle.textContent=(name||'Your daily briefing')+' · '+currentBriefing.date;
      transcript.hidden=false; transcriptToggle.hidden=false;
      transcriptToggle.setAttribute('aria-expanded','true'); transcriptToggle.textContent='Hide transcript';
      document.querySelector('#check-in').hidden=false;
      document.querySelector('#listen').hidden=false;
      setStage('ready',currentBriefing.profile_version===profile.version?'Transcript ready':
        'Saved transcript loaded. Your new preferences apply to the next edition.'); return;
    }
    const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({topics:selected(), region:region.value || null, language:language.value})});
    if (response.ok) {
      currentBriefing=await response.json();
      renderTranscript(currentBriefing);
      transcriptToggle.hidden=false;
      narrate(currentBriefing);
      return;
    }
    errorMessage=await response.text();
  } catch(e) {errorMessage=e.message||'Could not prepare your briefing. Please try again.'}
  setStage('script-error', '');
  briefing.hidden=true;
  failed.hidden=false;
  failureDetail.textContent=errorMessage;
  button.disabled=false;
  document.querySelector('#failure-title').focus();
}
async function narrate(result) {
  retryAudio.hidden = true;
  setStage('narrating', 'Transcript ready. Generating audio…');
  try {
    if(daily){
      const manifest=await post('/api/narration',{edition:result.edition});
      if(currentBriefing!==result) return;
      const section=document.querySelector('#daily-audio'), media=section.querySelector('audio'), list=section.querySelector('ol');
      list.replaceChildren(); section.hidden=false;
      let index=0;
      const play=i=>{
        index=i; media.src=manifest.segments[i].url;
        media.play().catch(()=>{if(currentBriefing===result) audioFailed('Could not start playback.');});
      };
      manifest.segments.forEach((part,i)=>{
        const li=document.createElement('li'), choice=document.createElement('button');
        choice.type='button'; choice.textContent=formatTime(part.start_seconds)+' · '+part.text;
        choice.onclick=()=>play(i); li.append(choice); list.append(li);
      });
      media.src=manifest.segments[0].url;
      media.onended=()=>{if(index+1<manifest.segments.length) play(index+1);};
      media.onerror=()=>{if(currentBriefing===result) audioFailed('Could not load the audio segment.');};
      setStage('ready','Synthetic narration · '+formatTime(manifest.duration)); return;
    }
    const response = await fetch('/narrate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({edition:result.edition, script:result.script})
    });
    if(currentBriefing!==result) return;
    if (!response.ok) {
      audioFailed('Could not generate the audio.');
      return;
    }
    const audio=await response.blob();
    if(currentBriefing===result) player.src = URL.createObjectURL(audio);
  } catch(e) {
    if(currentBriefing===result) audioFailed(daily && e.message ? e.message : 'Could not load the audio.');
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
  if(daily){
    const section=document.querySelector('#daily-audio');
    section.querySelector('audio').pause();
    section.hidden=true;
  }
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
  narrate(currentBriefing);
};
document.querySelector('#listen').onclick=()=>{document.querySelector('#listen').hidden=true;narrate(currentBriefing);};

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
document.querySelector('#edit').onclick=()=>{
  currentBriefing=null;
  const dailyAudio=document.querySelector('#daily-audio');
  dailyAudio.querySelector('audio').pause(); dailyAudio.hidden=true;
  document.querySelector('#check-in').hidden=true; document.querySelector('#feedback-form').reset();
  document.querySelector('#feedback-form [role=status]').textContent='';
  player.pause();
  const url=player.getAttribute('src');
  if(url){player.removeAttribute('src'); player.load(); URL.revokeObjectURL(url);}
  controls.hidden=download.hidden=transcript.hidden=transcriptToggle.hidden=retryAudio.hidden=true;
  transcriptToggle.setAttribute('aria-expanded','false');
  transcriptToggle.textContent='Show transcript';
  briefing.hidden=true; picker.hidden=false; updateCount(); region.focus();
};
updateCount();
</script></html>"""


LANGUAGE_NAMES = {"en": "English", "nl": "Nederlands", "de": "Deutsch"}
REGION_NAMES = {
    "AU": "Australia", "CA": "Canada", "CH": "Switzerland", "CN": "China", "DE": "Germany",
    "EA": "Euro area", "FR": "France", "GB": "United Kingdom", "IL": "Israel", "IN": "India",
    "IR": "Iran", "JP": "Japan", "KR": "South Korea", "MX": "Mexico", "NL": "Netherlands",
    "NZ": "New Zealand", "RU": "Russia", "TW": "Taiwan", "UA": "Ukraine", "US": "United States",
}


def picker_page(options, region, language, selected, profile=None, listeners=(), persona=None):
    def option(value, label, current):
        return f'<option value="{escape(value)}"{" selected" if value == current else ""}>{escape(label)}</option>'

    languages = "".join(option(code, label, language) for code, label in LANGUAGE_NAMES.items())
    regions = option("", "All regions", region or "") + "".join(
        option(code, REGION_NAMES.get(code, code), region) for code in options["regions"])
    daily = "dates" in options
    profile = profile or {}
    choices = []
    count = 0
    for topic in options["topics"]:
        enabled = daily or topic["events"] > 0
        checked = enabled and topic["id"] in selected
        count += int(checked)
        state = " disabled" if not enabled else " checked" if checked else ""
        choices.append(f'<label><input type="checkbox" name="topic" value="{escape(topic["id"])}"{state}>'
                       f'{escape(topic["label"])}</label>')
    message = "" if any(t["events"] for t in options["topics"]) else (
        "No approved reporting for this area and language. Try another selection.")
    extra = save = details = ""
    if daily:
        personas = "".join(option(person["id"], person["name"], persona or "") for person in listeners)
        chooser = (f'<div class="listener-picker"><label>Listener <select id="persona-chooser">{personas}</select></label>'
                   '<label id="new-listener" hidden>Name <input type="text" maxlength="60" autocomplete="off"></label>'
                   '<div class="listener-actions"><button type="button" id="add-listener">Add user</button>'
                   '<button type="button" id="remove-listener">Remove persona</button>'
                   '<button type="button" id="cancel-listener" hidden>Cancel</button>'
                   '</div><p id="listener-status" role="status"></p>'
                   '<dialog id="remove-dialog" aria-labelledby="remove-question"><p id="remove-question"></p>'
                   '<div class="listener-actions"><button type="button" id="cancel-remove" autofocus>Cancel</button>'
                   '<button type="button" id="confirm-remove">Remove</button></div></dialog></div>')
        dates = "".join(option(d,d,options["date"]) for d in options["dates"])
        depths = "".join(option(d,d.title(),profile.get("depth","standard")) for d in ("headlines","standard","detailed"))
        extra = f'<label>Briefing date <select name="date" id="day">{dates}</select></label>'
        weights = "".join(f'<label>{escape(label)} <input data-weight="{t}" name="weight_{t}" type="number" min="-2" max="2" value="{profile.get("weights",{}).get(t,0)}"></label>'
                          for t,label in TOPIC_LABELS.items())
        details = (f'<div class="preference-fields"><label>Minutes <input name="minutes" type="number" min="1" max="10" required value="{profile.get("minutes",3)}"></label>'
                   f'<label>Detail <select name="depth">{depths}</select></label>'
                   f'</div><details><summary>Topic priority (−2 to +2)</summary><div class="topic-weights">{weights}</div></details>')
        if language in {"de","nl"} and not region:
            details += '<p>Suggested local coverage: ' + ("Germany" if language=="de" else "Netherlands") + '. Choose it under Coverage area or keep All regions.</p>'
        save = '<button type="button" id="save-profile">Save preferences</button>'
        details += ('<p>The briefing date is the reporting cutoff. It may include earlier articles. '
                    'Publication dates are labeled separately from event dates and data periods such as October.</p>')
        if providers.cloud_only():
            details += '<p>Cloud-only demo · OpenAI</p>'
            if providers.requests_paused() or not providers.api_key():
                details += '<p>Cached news and saved editions are available. To generate a new briefing, configure a key and enable OpenAI requests on the pitch machine.</p>'
    selector = f'<input type="hidden" name="persona" value="{escape(persona or "")}">{chooser}' if daily else ""
    form = f"""<form method="get" data-daily="{str(daily).lower()}" data-version="{profile.get("version",0)}">
{selector}
<div class="preference-fields">{extra}
<label>Briefing language <select id="language" name="language">{languages}</select></label>
<label>Coverage area <select id="region" name="region">{regions}</select></label></div>
<fieldset><legend>Choose one or more topics</legend><div id="choices">{"".join(choices)}</div></fieldset>
{details}
<footer><button type="submit"{"" if count else " disabled"}>Get briefing</button>{save}
<output id="count">{count} selected</output></footer></form><p id="picker-status" role="status">{message}</p>"""
    return PAGE.replace("<!--TOPIC_FORM-->", form)


class Picker(BaseHTTPRequestHandler):
    def reply(self, code, body, kind="text/plain"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "listener_cookie", None):
            self.send_header("Set-Cookie", self.listener_cookie)
        if getattr(self, "expire_legacy_listener", False):
            self.send_header("Set-Cookie", "voxlistener=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
        self.send_header("Content-Length", str(len(data)))
        try:
            self.end_headers()
            self.wfile.write(data)
        except ConnectionError:
            # A browser can leave the page while a catalogue or briefing is loading.
            pass

    def do_GET(self):
        url = urlsplit(self.path)
        if providers.cloud_only() and url.path in {"/", "/picker", "/categories", "/api/runtime"}:
            from certa.demo import status
            runtime = status()
            if url.path == "/api/runtime":
                return self.reply(200, json.dumps(runtime), "application/json")
            if not runtime["ready"]:
                return self.reply(503, '<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<title>Certa cloud demo</title><main><h1>Cloud-only demo</h1><p>'
                    + escape(runtime["message"]) + '</p></main></html>', "text/html")
        if url.path.startswith(("/api/","/evidence/")):
            return daily_web.respond(self,DIRECTORY)
        if url.path not in {"/", "/picker", "/categories"}:
            return self.send_error(404)
        params = parse_qs(url.query, keep_blank_values=True)
        region = params.get("region", [None])[0] or None
        language = params.get("language", ["en"])[0]
        try:
            if url.path == "/":
                browser = daily_web.identity(self)
                with storage(DIRECTORY) as db:
                    listeners = people(db, browser, include_legacy=True)
                    visible_ids = [p["id"] for p in listeners]
                    requested = params.get("persona", [None])[0]
                    persona = requested if requested in visible_ids else next(iter(visible_ids), None)
                    profile = persona_profile(db, browser, persona or None) if listeners else {}
                    profile = profile or {}
                if "language" not in params:
                    language = profile.get("language","en")
                if "region" not in params:
                    region = profile.get("region")
                preferences(list(TOPIC_LABELS),region,language)
                day = params.get("date",[None])[0]
                options = picker_options(database_path(),day,region,language)
                pending = dict(profile)
                if "minutes" in params:
                    pending["minutes"] = max(1,min(10,int(params["minutes"][0])))
                    pending["depth"] = params.get("depth",["standard"])[0]
                    pending["weights"] = {t:max(-2,min(2,int(params.get("weight_"+t,["0"])[0]))) for t in TOPIC_LABELS}
                topics = params.get("topic",[] if "language" in params else profile.get("topics",[]))
                return self.reply(200,picker_page(options,region,language,topics,pending,listeners,persona),"text/html")
            options = category_options(database_path(), region, language)
        except ValueError as error:
            return self.reply(400, str(error))
        except (sqlite3.Error, OSError) as error:
            return self.catalogue_unavailable(error)
        if url.path == "/categories":
            return self.reply(200, json.dumps(options), "application/json")
        self.reply(200, picker_page(options, region, language, params.get("topic", [])), "text/html")

    def do_POST(self):
        if self.path.startswith("/api/"):
            return daily_web.respond(self,DIRECTORY,post=True)
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
                directory = DIRECTORY
                if "edition" in payload:
                    edition = payload["edition"]
                    if not isinstance(edition, str) or not re.fullmatch(r"[0-9a-f]{64}", edition):
                        return self.send_error(400)
                    directory = DIRECTORY / "briefings" / edition
                    if not (directory / "script.md").is_file():
                        directory = DIRECTORY / "listeners" / daily_web.identity(self) / edition
                    if not (directory / "script.md").is_file():
                        return self.reply(404, "Unknown briefing edition.")
                with BRIEFING_FILES:
                    audio = generate_news_audio(directory, expected_script=payload["script"]).read_bytes()
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
            payload = json.loads(self.rfile.read(length))
            if isinstance(payload, list):
                selection = preferences(payload)
            elif isinstance(payload, dict):
                selection = preferences(payload.get("topics"), payload.get("region"), payload.get("language", "en"))
            else:
                return self.reply(400, "Expected a topic selection.")
        except ValueError as error:
            return self.reply(400, str(error))
        try:
            draft = make_draft(database_path(), selection)
        except NoCoverage as error:
            return self.reply(422, str(error))
        except (sqlite3.Error, OSError, ValueError) as error:
            return self.catalogue_unavailable(error)
        try:
            profile = selection if providers.cloud_only() else (DIRECTORY / "UserInfo.md").read_text(encoding="utf-8")
            briefing = compose_draft(draft, profile)
            with BRIEFING_FILES:
                edition = save_briefing(DIRECTORY, draft, briefing)
        except ScriptError as error:
            return self.reply(422, str(error))
        except (OSError, UnicodeError) as error:
            self.log_error("Could not generate script.md: %s", error)
            return self.reply(500, "Could not write your briefing script. Please retry.")
        if isinstance(payload, list):
            return self.reply(200, briefing["script"])
        self.reply(200, json.dumps({**briefing, "edition": edition}), "application/json")

    def catalogue_unavailable(self, error):
        self.log_error("Cannot read event catalogue: %s", error)
        self.reply(503, "The event catalogue is unavailable. Prepare it with the listener setup steps in README.md.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=0,help="Local listening port; default chooses an available port")
    parser.add_argument("--cloud-only",action="store_true",help="Use the isolated cloud-only demo")
    args=parser.parse_args()
    if args.cloud_only:
        from certa.demo import configure
        configure()
        DIRECTORY = DIRECTORY / "cloud-demo"
    else:
        providers.load_environment()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Picker) as server:
        print(f"Open http://127.0.0.1:{server.server_port} in your browser.", flush=True)
        server.serve_forever()
