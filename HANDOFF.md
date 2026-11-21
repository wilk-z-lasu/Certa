# Certa pitch handoff

## On the pitch laptop

Open [the presentation](pitch/Certa%20Pitch.pptx) and the [recorded pitch](output/pitch/Certa.html). The HTML embeds audio and evidence references. The prepared editions support playback, transcript comparison and claim inspection from disk. Publisher and official-release links require network access. Use the local app for the live wildcard.

```powershell
$env:CERTA_PROVIDER = 'openai'
$env:CERTA_API_REQUESTS_PAUSED = '1'
$env:CERTA_NARRATION = 'offline'
python -m certa.daily --offline --date 2026-11-19
python app.py --port 50488
```

The Windows launcher [Start-Certa.cmd](Start-Certa.cmd) also starts this app. On the pitch laptop, English uses Windows speech and German and Dutch use project-local eSpeak NG. All three were rendered through the application with paid requests paused. FFmpeg and ffprobe are on PATH.

1. In the app, choose **Maya** for technology or **Ellis** for rates and inflation. **Noor** listens in Dutch and **Jonas** in German. The standalone recordings retain their original edition labels, including **Macro morning** and **Tech & economy**.
2. Open **Show transcript** and three **Claim evidence** entries. Each entry follows a sentence to the exact source passage and immutable event revision. Official figures also link to the dated observation used for verification.
3. Select **Add user**, enter the jury wildcard's name, and set the briefing date, language, area, topics, target minutes, detail and optional topic weights. Click **Create listener**, **Get briefing**, then **Generate audio**.
4. Use **Daily check-in** to demonstrate feedback that shapes the next briefing. Reopen a delivered date to show that its text and citations remain fixed.

See the [audio audit](AUDIO_AUDIT.md), [measured cost report](pitch/cost-report.json) and [rebuild commands](README.md#rebuild-the-recorded-pitch-and-cost-report). Use the report to distinguish preparation from per-listener delivery and measured figures from the 10× projections.

## Evidence and scope

The full-feed benchmark processed 1,740 articles into 1,540 events and 15 approved claims. Five matched official values. Ten use attributed reporting clauses, including outages, earnings, a shareholder allegation, IPO pricing, a factory plan and a traded Bitcoin threshold. Topic overlap does not guarantee coverage, particularly for a narrow time or regional filter. All six positive and five negative manual development pairs matched final memberships. The official story key and organizer listener profiles were unavailable on this checkout. Walk through the supplied example listeners and enter the real wildcard live. Treat the manual sample as development evidence. [Grouping evaluation](EVENT_GROUPING_EVALUATION.md)

The proposed customer is a publisher. Editors import licensed feeds, inspect held claims and conflicting reports, and publish a shared checked catalogue. Listener settings and feedback control selection and presentation. Corrections create new catalogue revisions while preserving evidence in past editions. The commercial proposition still needs customer validation.

## Optional hosted path

Keep cloud secrets in the ignored `.env.demo`, never in `.env` for the local pitch. Launch in a separate shell with a funded OpenAI key and an explicit unpause only when the team authorizes charges. ElevenLabs is separately billed and needs its own key and voice ID for cloud audio. The hosted app uses port 50500, `output/cloud-demo/` and `user_data/cloud-demo/`. Existing authorized caches can reduce repeat charges.

```powershell
python -m certa.demo --date 2026-11-19 --model-events 40
python app.py --cloud-only --port 50500
```

Earlier hosted work stopped at the available budget. Its saved draft and caches do not establish full verification, final cloud composition or ElevenLabs playback. The updated grouping path adds strong release and outage signatures ahead of model review. Those matches were verified locally and the cloud route was exercised without provider requests. The previous hosted output remains a historical result. Current hosted end-to-end verification remains open.

Keep the input feeds, cached source records, generated pitch assets, transcripts and audio inside the team's authorized environment. Delete licensed inputs, derived records and team copies at the end of the permitted period.
