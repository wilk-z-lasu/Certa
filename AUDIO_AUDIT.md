# Daily narration and claim audit

The app reads the same checked sentences it displays in the transcript. Click **Generate audio**, then use the player or the timestamped list. The introduction discloses synthetic narration. Each claim in the transcript has a **Claim evidence** link that opens that claim's source log, including for a reopened edition.

## Replay on the pitch laptop

Run from the repository root in a regular Windows user session with FFmpeg and ffprobe on PATH. With the prepared catalogue in `output/event-overviews.sqlite3`, start the app in one PowerShell window.

```powershell
$env:CERTA_API_REQUESTS_PAUSED = '1'
$env:CERTA_NARRATION = 'offline'
python app.py --port 8430
```

In another window, run the audit against that server. It creates a fresh browser session and records both preset editions and a new English wildcard who prioritizes crypto and follows technology.

```powershell
python -m certa.audit_audio --date 2026-11-19 --output output/audio-audit
```

Within each listener folder, `briefing.wav` is the consecutive playback of the verified app segments. `manifest.json` has their measured intervals and audio hashes, `briefing.json` has the saved edition and composition timings, and `claim-audit.json` lists evidence URLs and checked source locations. `quality.json` reports the probed playback duration, words per minute and elapsed segment rendering time. The audit checks that a saved edition reopens unchanged, the replay is a cache hit, the downloaded bytes match their hashes and the claim evidence links expand the correct rows. It checks publisher spans against the local licensed feed and compares supported official observations with the bundled release pack. Keep recordings and generated receipts under ignored `output/`.

The 19 November pitch-machine run used Windows speech with no paid requests. The timing below is for the rendered WAVs.

| Listener | Claims | Playback | Script words/minute | Story order |
| --- | ---: | ---: | ---: | --- |
| Macro morning | 4 | 0:54.12 | 114 | Euro area inflation, Bank of England, UK inflation, Bitcoin |
| Tech & economy | 15 | 2:34.62 | 114 | Nvidia, Apple services, Intel litigation and Outlook before other market news |
| Crypto and technology wildcard | 5 | 1:05.17 | 107 | Bitcoin before four technology updates |

FFprobe matched the WAV durations to the app's segment timelines within 0.01 seconds. FFmpeg measured peaks from −3.5 to −2.9 dBFS across the recordings. The longest pauses detected at −45 dBFS were under 0.86 seconds.

The pitch machine uses Microsoft Zira Desktop for English and a project-local eSpeak NG release for German and Dutch. The app checks for a matching Windows desktop voice first, then the project-local eSpeak NG, then eSpeak NG on PATH. If no matching voice is present, the app leaves the verified transcript available. A saved recording can play without the original engine, tools or credentials if its segments still match the checked transcript and their audio hashes.

Two additional fresh wildcard profiles exercised eSpeak NG through the app. The German edition ran 68.00 seconds and the Dutch edition ran 62.15 seconds, with four verified claims each. All downloaded segments matched their checksums and replayed from cache.

To set up German and Dutch on a second Windows x64 machine, run the following from the repository root. Windows Installer extracts the official package into the ignored `output/tools` directory. This leaves the machine's installed programs and PATH unchanged. [eSpeak NG 1.52.0 release](https://github.com/espeak-ng/espeak-ng/releases/tag/1.52.0)

```powershell
$root = Join-Path (Get-Location) 'output/tools/espeak-ng'
New-Item -Path $root -ItemType Directory -Force | Out-Null
$msi = Join-Path $root 'espeak-ng.msi'
Invoke-WebRequest 'https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi' -OutFile $msi
$sha256 = '7F673C709EA5DD579D3B5EBB98688CC575328A6AB7438D2BC405B88CEDAEAFB9'
if ((Get-FileHash $msi -Algorithm SHA256).Hash -ne $sha256) { throw 'eSpeak NG checksum mismatch' }
$payload = Join-Path $root 'payload'
$extract = Start-Process msiexec.exe -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$payload`"" -WindowStyle Hidden -PassThru -Wait
if ($extract.ExitCode -ne 0) { throw "eSpeak NG extraction failed ($($extract.ExitCode))" }
```

The normal app's `auto` mode selects ElevenLabs with configured voice and credentials when paid requests are enabled. `offline` selects local speech only for new recordings. `elevenlabs` opts into hosted narration, subject to the payment pause. The isolated cloud-only demo uses ElevenLabs. To request a new rendering with changed settings for an existing edition, the narration endpoint accepts `refresh: true` and reuses unchanged audio segments.

## Three-claim audit

The sample below uses the 19 November 2026 Macro morning edition. The claim IDs in the replay output lead to the versioned evidence logs. The examples cover an official decision and two annual inflation figures.

| Playback interval | Claim | Licensed reporting | Official release |
| --- | --- | --- | --- |
| 0:14.97–0:21.53 | Euro area harmonised consumer price inflation was 4 percent year on year in October 2026. | Annual HICP at 4.0% for October. [ActionForex](https://www.actionforex.com/live-comments/661283-eurozone-inflation-confirmed-at-4-0-as-energy-surges-core-cpi-revised-higher/) | Euro area, October annual HICP, 4.0%. [Eurostat](https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-18112026-ap) |
| 0:27.48–0:32.93 | The Bank of England set its Bank Rate at 4 percent on 5 November 2026. | The reported increase took Bank Rate to 4.00% on 5 November. [ActionForex](https://www.actionforex.com/action-insight/market-overview/660977-canada-cpi-today-uk-cpi-wednesday-can-inflation-finally-break-gbp-cads-range/) | Majority decision in the opening policy summary, Bank Rate 4%. [Bank of England](https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/november-2026) |
| 0:36.71–0:43.12 | UK consumer price inflation was 3.6 percent year on year in October 2026. | Headline CPI, 3.6% year on year in October. [ActionForex](https://www.actionforex.com/live-comments/661264-uk-inflation-rises-to-3-6-as-fuel-prices-surge-core-cpi-holds-steady/) | Table 1, October CPI 12-month rate, 3.6%. [Office for National Statistics](https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/october2026) |
