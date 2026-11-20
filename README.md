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
