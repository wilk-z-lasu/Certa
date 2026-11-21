# VoxNews

## Run the daily backend

Use Python 3.10 or newer. From the repository root, these commands import all six feeds and prepare two historical days using the bundled official observations. The dates are the last included UTC calendar days. Each window ends at midnight the following day.

```sh
python3 -m voxnews.daily --offline --date 2026-11-17
python3 -m voxnews.daily --offline --date 2026-11-18
python3 app.py --port 50488
```

The offline backend uses Python's standard library and SQLite. To enable model processing on macOS or Linux, create an environment, install the embedding dependencies and download the pinned E5 files once.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-events.txt
mkdir -p output/e5-small
curl --fail --location --output output/e5-small/tokenizer.json https://huggingface.co/intfloat/multilingual-e5-small/resolve/ccc66d3/tokenizer.json
curl --fail --location --output output/e5-small/model.onnx https://huggingface.co/intfloat/multilingual-e5-small/resolve/ccc66d3/onnx/model.onnx
```

Open the printed address. Choose November 17, economy and central banks, English, and UK coverage. Save the preferences and open the briefing. Select **Claim evidence** beside a sentence to inspect its event revision, article and official source. In **Daily check-in**, ask for a shorter briefing and more currency news. Return to **Change interests** and select November 18. Previously delivered claims stay in the first edition. The profile history and immutable draft identify which settings shaped each day. Another browser profile or private window gives a second listener their own history. Try Dutch narration with euro-area coverage, or enter the wildcard listener's settings directly. Audio generation requires an explicit click.

The offline preparation uses exact-copy grouping and verified official figures. Without a writer key or local provider, composition uses ordered approved sentences. A model run also performs multilingual embedding, small-model grouping, claim extraction, larger-model review and event overview creation. Install `requirements-events.txt` and obtain the pinned E5 files as described under **Group articles into events**. For local inference, start Ollama with the models listed below, then use these commands in the same shell.

```sh
export VOXNEWS_PROVIDER=ollama
python3 -m voxnews.daily --date 2026-11-18 --lookback-days 7 --model-events 40
python3 app.py --port 50488
```

The 40-event limit budgets extraction and review of eligible event revisions. Events containing eligible claims also pass through the overview editor. Omitting the limit reviews all eligible candidates. Invalid model outputs are held and reported in the run's verification summary. Each rerun reuses decisions tied to the relevant inputs, model and prompt. For hosted inference set `VOXNEWS_PROVIDER=openai` and use an untracked `.env` or shell environment. The provider roles can be overridden independently.

Shared event overviews retain broad source coverage before listener preferences are applied. The pipeline indexes the full articles, then samples the leads of reporting origins and passages across nine editorial facets, including background, mechanisms, reactions, implications and uncertainty. Bounded extraction and review requests preserve their exact source offsets. The event overview editor must retain all approved claims. Stored `overview_coverage` records show which facets have source passages and which have approved wording. `examined_passages` records the actual reviewed ranges. Remaining source material stays in the internal dossier for inspection. Selection for headlines, standard or detailed delivery happens in the listener draft.

Before publication, the larger model also compares the event's checked claims together for conflicting accounts, incompatible timing and missing attribution. Each issue must cite the affected claims and their supplied evidence. Flagged claims stay available in the source inspector and are excluded from listener drafts. An event that exceeds the local review window stays pending for a provider with a larger context window. A failed translation is held for its language while the valid English record and other reviewed translations remain available.

If other checked facts from an event with unresolved reporting are selected, the final transcript includes a localized uncertainty caveat. Transcript validation requires that caveat alongside the selected wording and source links.

Source-supported forecasts, allegations and analysis can supply context when their wording preserves explicit attribution and uncertainty. Their kind stays attached to the shared record and listener draft, and the spoken wording labels it. They are checked as reports of a position rather than established outcomes. Investment recommendations are excluded. Translated prose retains the publisher attribution and passes separate checks for meaning, numeric value, scale, currency, units and dates.

| Model role | Variable | Local default | Hosted default |
| --- | --- | --- | --- |
| Topic review and event grouping | `VOXNEWS_GROUPING_MODEL` | qwen3.5:0.8b-mlx | gpt-6-luna |
| Claim extraction | `VOXNEWS_EXTRACTION_MODEL` | qwen3.5:4b-mlx | gpt-6-luna |
| Evidence review and overview | `VOXNEWS_REVIEW_MODEL` | qwen3.5:4b-mlx | gpt-6.2-astra |
| Daily composition | `VOXNEWS_COMPOSITION_MODEL` | qwen3.5:4b-mlx | gpt-6.2-astra |

The local models must be installed under the configured names. For hosted use, select model IDs available to your account. The writer chooses and orders cited claims. The renderer supplies the reviewed wording, date, section transitions and disclosure in the listener's language. Missing coverage can produce a short edition or no edition. An audio failure leaves the text available. Segment generation uses ElevenLabs and `ffprobe` for measured durations.

### Records, inspection and cleanup

The source store is `output/sources.sqlite3`. Each import retains the complete original records, feed membership and classification. Frozen source files in `output/imports/` make earlier citations resolvable after a correction. `output/days/YYYY-MM-DD/` holds the verification snapshot and stage report. `output/event-overviews.sqlite3` stores date-specific membership and immutable dossiers. Set `VOXNEWS_OVERVIEW_DB` to serve a different catalogue. The default lookback is seven days. A date must have its own published catalogue. Earlier dates can be replayed after later catalogues have been built.

`user_data/listeners.sqlite3` contains browser-specific profile versions, daily feedback, drafts and final text. `GET /api/profile` lists that listener's settings, history and delivered dates. A repeat request for the same day returns its original edition. Segmented audio, when generated, is stored in `user_data/listeners/`. The earlier single-listener interface remains at `/picker`.

The evaluation CLI compares final event memberships against labeled pairs and traces saved transcript sentences back to their immutable source editions.

```sh
python3 -m voxnews.evaluate grouping output/days/2026-11-18/events.jsonl
python3 -m voxnews.evaluate transcript --edition EDITION_ID
```

Generate the measured preparation and listener cost report with the following command. Add `--briefing` for each saved example or final briefing JSON. For hosted projections, supply `--prices` with actual per-million input, cached-input and output prices keyed by model ID, plus `--rates-date YYYY-MM-DD`. Unpriced hosted usage stays unknown. The two projections scale new article volume and listener count separately. Local inference has zero model API fees. Hardware, electricity and subscription costs need separate accounting. Speech measurements and listening review are pending the deferred ElevenLabs verification.

```sh
python3 -m voxnews.cost output/days/2026-11-19/report.json
```

The proposed initial payer is a publisher offering a personalized morning briefing to subscribers. Editors import the licensed feeds, inspect held events and source disagreements, and publish the day's shared catalogue. Listener setup and feedback then shape drafts from those saved event revisions. A correction creates a new revision, while earlier editions retain their original evidence. The validated introduction discloses synthetic narration in the listening language. This publisher proposition is a product hypothesis that still needs customer validation.

Use the grouping command after a model run. Supply `--reference PATH` to evaluate a separate reference file in the format under `examples/`. The bundled reference is a targeted manual sample. For end-of-event deletion, remove the original licensed feeds, all generated output directories including SQLite databases, cached model decisions and frozen imports, local listener data and media, exported bundles, and team copies or backups. Retain licensed material only within the authorized team and event period.

## Run the hackathon demo offline

Copy [the demo ZIP](output/voxnews-offline-demo.zip) to the presentation computer, extract the entire archive, and open **index.html** in a browser. The two recordings, transcripts, per-sentence evidence, searchable event catalogue and claim source logs work from disk. Only links out to publishers and official releases require internet access. The presentation computer needs no Python, Ollama, model weights, GPU or API key.

The bundle is a fixed snapshot for playback and evidence inspection. The headlines recording has two claims in about 17 seconds. The rates recording has five in about 37 seconds. Live editing and listener-specific research selection use the Python commands below.

## Categorize the source feeds

From the repository root, run with Python 3.9 or newer.

```powershell
python -m voxnews.categorize --input-dir liquid-briefing-data --output output/categories.jsonl
python tests/check_backend.py
```

The backend check command covers classification, grouping, verification, broad event dossiers, text delivery and feedback. The ElevenLabs adapter test is deferred by default and can be selected later with `--include-audio`. The backend checks exercise no ElevenLabs requests.

The CLI writes one record per article and prints counts by feed and overall timing. It accepts JSONL feeds with the Newstex article fields and reports bad rows and duplicate IDs with file and line numbers. The destination is replaced after the complete run succeeds. To use the classifier from Python, call `voxnews.categorization.categorize_article(article)` with a decoded article object.

## Topic taxonomy

| Topic ID | Editorial scope | Example label |
| --- | --- | --- |
| `economy_central_banks` | Macroeconomic data, economic activity, trade balances, and monetary policy | A central bank keeps its policy rate steady. |
| `companies_stocks` | Company activity, earnings, equities, and investment funds | A manufacturer reports quarterly earnings and its shares rise. |
| `currencies` | Exchange rates, currency markets, and FX intervention | The yen rises against the dollar after an intervention warning. |
| `crypto` | Cryptoassets, exchanges, stablecoins, and blockchain finance | A crypto exchange introduces a new stablecoin. |
| `technology_ai` | AI, computing, cybersecurity, and technology infrastructure or products | A software outage disrupts cloud email. |
| `politics_world` | Elections, government decisions, public regulation, and international affairs | Two governments negotiate a new trade agreement. |
| `other_news` | Culture, sport, personal finance, and other subjects outside the main beats | A boxing tournament announces its finalists. |

Articles can receive several tags. For example, a central bank decision that moves the yen can receive both `economy_central_banks` and `currencies`. A provisional `other_news` catch-all carries the `no_supported_topic` review reason. `POSITIVE` and `NEGATIVE` tags are ignored.

## JSONL handoff

- `article_id` is the original `$id`. Use it to join to the input article. `permalink` and `language` are preserved verbatim.
- `topics` and `regions` are arrays. Region values include country codes, `global` for explicit worldwide scope, and `unknown` when geographic evidence is insufficient. The country rules cover AU, CA, CH, CN, DE, FR, GB, IL, IN, IR, JP, KR, MX, NL, NZ, RU, TW, UA, and US. A eurozone-wide article may have `unknown` for its country-level geography.
- `evidence` maps labels to the matched rules. Text references contain `field`, `start`, and `end`. The offsets are zero-based Unicode character offsets with an exclusive end, so `article[field][start:end]` recovers the match locally. Metadata references use the zero-based `index` in the original tag array. The `unknown` region has no evidence entry.
- `needs_review` and `review_reasons` expose weak topic evidence, disagreements with publisher sections, and unconfirmed publisher location hints. Topic rules use the headline and up to 400 excerpt characters. Geographic rules use the headline and up to 450 excerpt characters. The handoff contains no headline, excerpt, or body text.

Generated files in `output/` are local. See the [categorization evaluation](CATEGORIZATION_EVALUATION.md) for the per-feed results, manual review, and limitations.

## Group articles into events

Install the grouping dependencies and download the official multilingual E5 tokenizer and ONNX weights once. The downloads contain model files only. Embedding inference runs on the local CPU.

```powershell
python -m pip install -r requirements-events.txt
New-Item -ItemType Directory -Force -Path output/e5-small
curl.exe -fL -o output/e5-small/tokenizer.json https://huggingface.co/intfloat/multilingual-e5-small/resolve/ccc66d3/tokenizer.json
curl.exe -fL -o output/e5-small/model.onnx https://huggingface.co/intfloat/multilingual-e5-small/resolve/ccc66d3/onnx/model.onnx
```

With `OPENAI_API_KEY` set in the shell, run the stage against the categorization output. For local candidate inspection without the API, use `--candidates-only` with a separate output path.

```powershell
python -m voxnews.group_events --output output/events.jsonl
python -m voxnews.group_events --candidates-only --output output/event-candidates.jsonl
```

- All feed dates are included by default. For the challenge week use `--from 2026-11-13 --before 2026-11-20`. The start is inclusive and the end is exclusive. Dates without a time use midnight UTC.
- Each event row has one event ID, the union of its source topics, and one entry per source article. Source entries preserve the original ID, permalink, language, timestamp, reporting-origin ID, and how the article joined the event. A downstream category view can filter the same event rows by topic without duplicating their identities.
- Events can be `grouped`, `singleton`, or `needs_review`. The last status covers uncertain event matches and uncertain translation origins. Reporting-origin IDs link exact copies and confirmed Invezz translations. Establishing independent corroboration still requires reviewing the reporting and claim evidence.
- Use `--previous output/events.jsonl` to carry forward stable IDs when adding late or newly published articles. If previously separate events join, the retained event lists the superseded IDs. The CLI replaces the output only after a complete run.
- The Responses API receives derived comparisons only, with `store=false`. Article text, source IDs, permalinks, and author names stay local. Cache entries in `output/luna-decisions.sqlite3` retain validated verdicts by model, prompt version, and feature fingerprint. Cache hits can be replayed without an API key. Remove local corpus artifacts after the event according to the dataset terms.

The CLI prints counts, elapsed time, and an estimate based on reported Luna token use. See the [event grouping evaluation](EVENT_GROUPING_EVALUATION.md) for the candidate results and the status of live-model verification.

## Verify claims and listen to their evidence

Verify grouped events against their source articles and dated official releases. The bundled pack supports offline replay. Choose the same source window used for event grouping.

```powershell
python -m voxnews.verify --events output/events.jsonl --before 2026-11-20
python -m voxnews.trust_briefing --profile headlines --out-dir output/trust-headlines
python -m voxnews.trust_briefing --profile rates --out-dir output/trust-rates
```

Open the generated `index.html`. Each sentence has a playback button and expandable article and official evidence. The headlines profile selects up to two events. The rates profile leads with policy decisions and includes more detail. Use `--region GB` to select a region or `--language de` or `--language nl` for localized numeric claims. Add `--wav` on Windows with pywin32 and an installed voice for that language to export audio with sentence timestamps. The HTML also supports browser speech.

For an offline run using the earlier candidate-stage handoff, substitute `--origins output/event-candidates.jsonl` for `--events output/events.jsonl`. This keeps confirmed translations together and treats each reporting origin as its own provisional event. A run without either input groups only identical bodies. The summary identifies which mode ran.

### Official sources and article claims

1. List the agencies and their release calendars with `python -m voxnews.official_releases sources`. RSS discovery works for ONS, BoE, Destatis, CBS and the ECB. The registry also links Eurostat, Bundesbank and DNB catalogues.
2. Find dated release candidates, then open the linked bulletin or decision. The calendars and feed titles are discovery aids. The evidence is a specific observation or paragraph in the published release.
3. Import the organizers' releases as reviewed JSONL records using the format in [the bundled release pack](voxnews/official/observations.jsonl). Each observation contains geography, measure, reference period, comparison basis, decimal percent and table cell or paragraph location. Supply the issuer, dated HTTPS URL, stable release ID, vintage and timezone-aware availability time. A correction gets a new availability time and a complete replacement set of observations for that release ID. The registry limits each issuer to its domains and series.

```powershell
python -m voxnews.official_releases discover --from 2026-11-13 --before 2026-11-20 --output output/release-candidates.jsonl
python -m voxnews.official_releases archive
python -m voxnews.official_releases import-ons --release-id uk-cpi-2026-10 --output output/ons-release.jsonl
python -m voxnews.verify --origins output/event-candidates.jsonl --pack output/ons-release.jsonl --before 2026-11-20
```

The archive caches official bytes by URL and SHA-256. Use `--refresh` to fetch again and retain changed content. The ONS importer reads the actual Table 1 CSV headers and checks its cells against the curated pack before writing an expanded pack, including the other issuers. Other agencies currently use reviewed observations. A repeated `--pack` argument combines distinct packs. RSS endpoints carry recent entries only, so use the agency archives or supplied releases for an older week.

### Model routing and costs

Rules check article passages and official cells first. The verifier compares the release available at reporting time with the one available at the briefing cutoff. It holds conflicts, missing releases, preliminary figures, and unmatched revisions. An event with insufficient grouping evidence is held. The final script uses approved wording and claim IDs. The JSON snapshot includes held claims and the reasons.

To enable Luna extraction and stronger review, set `OPENAI_API_KEY` and supply a review model available to that account. This example budgets ten unresolved or audit events. `--audit-every 20` places a reproducible sample of automatic passes in the review queue.

```powershell
python -m voxnews.verify --events output/events.jsonl --before 2026-11-20 --model-events 10 --review-model $env:VOXNEWS_REVIEW_MODEL --audit-every 20
```

The model packet contains at most one short excerpt per selected article, up to 22 words each and six excerpts per event. The small model proposes claims and flags forecasts, advice, and ambiguous evidence. The reviewer must cite numbered passages. Official figures also require a matching official cell and a percent value present in the article evidence. Unresolved or disputed claims stay out of the script. Reviewed English reporting can enter with publisher attribution. Other-language narration currently uses the numeric templates.

SQLite caches rules and validated model responses. The `verified_event` table preserves event revisions referenced by older transcripts. Each listener reads the resulting snapshot, so generating another profile incurs zero verification-model calls. Full article bodies stay local. Delete the licensed feeds and derived local outputs after the event as required by the [dataset terms](liquid-briefing-data/README.txt).

To price live use, pass `--prices` with a JSON object keyed by each model ID. Each entry takes numeric `input`, `cached` and `output` rates in USD per million tokens. Missing prices or token counts produce an unknown cost. The summary reports extraction and review separately, measured wall time by stage, and a 10× model-cost projection with its assumptions. [Full-corpus results and claim audit](VERIFICATION_EVALUATION.md)

## Build and inspect event overviews

The overview consumes a saved verification snapshot, category handoff and the matching licensed feeds. The build, editor and export use the Python standard library. With the prepared hackathon inputs, run these commands from the repository root.

```powershell
python -m voxnews.overview build --verified output/overview-demo/verification.json --db output/offline-demo/event-overviews.sqlite3
python -m voxnews.overview serve --db output/offline-demo/event-overviews.sqlite3
```

Open `http://127.0.0.1:8173/` on the editor machine. Each dossier covers available developments, background, mechanisms, figures, timeline, implications, reactions, uncertainty and outlook. The editor can select depth, topic, preferred source language and focus. Language selection prioritizes available source evidence in that language. For example, to inspect the producer-price event and retain its evidence for a script writer, run the following in another shell.

```powershell
python -m voxnews.overview show --db output/offline-demo/event-overviews.sqlite3 --event us-producer-prices --depth technical --focus figures --format markdown --output output/ppi-writer.md
python -m voxnews.overview list --db output/offline-demo/event-overviews.sqlite3 --disputes
```

Every item has a stable claim ID, evidence role and source log. Article references include permalink, edition hash and exact character range. Official evidence identifies the release version and cell or paragraph. Conflicting figures, possible disagreements, revisions and challenges reported by one outlet carry distinct flags. Disputed material remains in the editor packet with its evidence even when the chosen length or focus would otherwise omit it. Internal writer packets can include exact source passages and stay with the team.

The demo handoff covers 1,740 articles in 1,493 events across seven topics. It uses reporting-origin groups plus four editorially reviewed joins. Further coverage of the same story can remain in separate groups. Of 70,172 research items, five have approved wording. The 26 flags in this snapshot are challenges reported within articles. The rules also detect certain cross-source disagreements when sufficient comparable evidence is present. The automated tests include two publishers reporting different quarterly revenue figures.

To regenerate the browser bundle, use the same verification snapshot and the recorded briefing directories. The exporter checks the spoken script against its approved evidence, checks WAV duration and sentence timing, then packages the source logs and audio. Generated outputs live in `output/` and must be copied separately from a source checkout.

```powershell
python -m voxnews.overview export-demo --db output/offline-demo/event-overviews.sqlite3 --verified output/overview-demo/verification.json --briefing output/trust-headlines --briefing output/trust-rates --output output/voxnews-offline-demo.zip
```

Building and reading overviews from the saved handoffs makes zero model calls. The separate `synthesize` command is the only overview operation that contacts Ollama. It requires an explicitly selected installed model on the enrichment machine. Generating new upstream event groups or live model reviews has the separate dependencies documented above.
## Personalized news audio

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the project’s `.env`, then run `python3 generate_news_audio.py` to narrate `user_data/script.md`. The app uses the same renderer in `md_to_speech.py` when it displays a newly generated script. Listener preferences shape the script, and ElevenLabs narrates it with the configured voice.

Listen in the app or open `user_data/news.wav`. The companion `news.manifest.json` records the script hashes, voice and model, request IDs, and measured duration. The renderer reuses the saved WAV when the script, voice, and model match.

## Markdown to speech with ElevenLabs

`md_to_speech.py` converts a Markdown file to an MP3 with ElevenLabs Text to Speech. It uses Python's standard library, so no Python packages are needed.

### Set up

1. Create an ElevenLabs API key and choose a voice in your ElevenLabs account.
2. Copy `.env.example` to `.env` and set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`.
3. Run the converter with Python 3.10 or newer:

```powershell
Copy-Item .env.example .env
# Edit .env and replace the example values.
python .\md_to_speech.py .\briefing.md
```

For a first run, use `examples\speech-sample.md` as the input.

By default this creates `briefing.mp3` and `briefing.manifest.json` beside the input file. The manifest records the input and spoken-text SHA-256 hashes, voice/model settings, generation time, and any request IDs returned by ElevenLabs.

### Options

```powershell
python .\md_to_speech.py .\briefing.md --output .\audio\morning.mp3
python .\md_to_speech.py .\briefing.md --voice-id VOICE_ID --model-id eleven_multilingual_v2
python .\md_to_speech.py .\long-briefing.md --keep-segments
```

The default model is `eleven_multilingual_v2`; override it with `ELEVENLABS_MODEL_ID` or `--model-id`. Markdown headings, lists, emphasis, and links are made readable for speech. Link labels are spoken and raw URLs are omitted. Code and math blocks are skipped. Text is split into chunks of up to 4,500 characters at paragraph or sentence boundaries. For one combined MP3 from a long document, install FFmpeg; otherwise use `--keep-segments` and play the numbered MP3 files in order.

The converter narrates the Markdown text; it does not fact-check or rewrite it. For the briefing pipeline, pass only the final validated script to speech generation, include the required synthetic-voice disclosure in that script, and keep claim-to-source links in the application records. The sidecar manifest fingerprints the input but does not replace claim-level provenance.

Both commands use the [ElevenLabs Text to Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert/).
