# VoxNews

## Categorize the source feeds

From the repository root, run with Python 3.9 or newer.

```powershell
python -m voxnews.categorize --input-dir liquid-briefing-data --output output/categories.jsonl
python -m unittest discover -s tests -v
```

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
