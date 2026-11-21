# Categorization evaluation

## Backend integration, November 21

Daily preparation now persists source classifications alongside immutable article versions before event grouping. Ambiguous labels may receive a bounded review from the configured small model. Candidate labels must first have a source-text match, and accepted decisions retain passage offsets and model/prompt identifiers. Invalid decisions remain flagged. The current full-dataset model run uses this route. The tables below describe the earlier rules-only baseline and its manual sample.

Listening language and geographic relevance remain separate. Published event regions require an approved claim whose wording and supporting source passage establish the country. A publisher name or a translated article's language cannot establish a local match. The listener draft prioritizes eligible local claims and reports sparse local coverage explicitly.

## Full dataset

The CLI processed 1,740 unique source IDs in 1.41 seconds on the development machine with Python 3.13.2. The two full runs produced identical JSONL bytes. At 10× article volume, with the same feed mix and throughput, the estimate is 14.1 seconds. Both runs used $0 in model API calls. Runtime includes parsing, classification, and writing the handoff.

Each article received at least one topic and 334 received multiple topics. Across the dataset, 354 articles had review flags (20.3%) and 1,567 had unknown geography (90.1%). A validation pass checked the article IDs, languages, permalinks, and 3,034 references to source text offsets or metadata indices. The synthetic tests also cover malformed rows, duplicate IDs, and preservation of the previous output on failure.

| Feed | Rows | E | C | F | K | T | P | O | Review | Unknown region |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ActionForex | 36 | 31 | 5 | 5 | 1 | 6 | 2 | 3 | 7 (19.4%) | 8 (22.2%) |
| IBTimes UK | 298 | 1 | 14 | 0 | 5 | 33 | 99 | 160 | 129 (43.3%) | 267 (89.6%) |
| Invezz DE | 120 | 7 | 67 | 1 | 16 | 51 | 3 | 7 | 32 (26.7%) | 101 (84.2%) |
| Invezz EN | 166 | 17 | 123 | 5 | 27 | 73 | 10 | 9 | 24 (14.5%) | 136 (81.9%) |
| Invezz NL | 120 | 9 | 87 | 1 | 15 | 48 | 5 | 6 | 20 (16.7%) | 99 (82.5%) |
| Zacks | 1,000 | 74 | 817 | 1 | 10 | 149 | 9 | 93 | 142 (14.2%) | 956 (95.6%) |

E economy and central banks, C companies and stocks, F currencies, K crypto, T technology and AI, P politics and world, O other news.

## Manual review

Six articles per feed were manually labeled from the headline and excerpt, with three for tuning and three reserved for a final check. The sample includes missing and broad publisher tags, translated Invezz coverage, and English-language reporting with Dutch or German relevance. It is a targeted 36-article sample. The official answer key is absent from the checkout.

Sample references use one-based lines in each original JSONL feed. Each entry gives the expected topic and region sets. `?` represents `unknown`.

| Feed | Tuning labels | Held-out labels |
| --- | --- | --- |
| `actionforex` | 1 E/DE, 3 E/US, 4 EF/JP+US | 2 E/?, 8 E/JP, 10 EF/CA+GB |
| `ibtimes_uk` | 2 OP/US, 3 O/?, 4 T/global | 10 PT/CN+US, 141 O/?, 212 PT/CN+NL |
| `invezz_de` | 3 T/?, 24 CK/?, 85 CPT/CN+US | 1 CT/?, 35 P/US, 65 C/DE |
| `invezz_en` | 4 T/?, 15 E/US, 105 CPT/CN+US | 2 CT/?, 75 C/DE, 166 C/? |
| `invezz_nl` | 3 T/?, 24 CK/?, 85 CPT/CN+US | 1 CT/?, 35 P/US, 65 C/DE |
| `zacks` | 1 CT/?, 4 EO/US, 151 CE/US | 3 C/?, 480 CP/CN+US, 646 EO/US |

The tuning set improved from 14/18 to 18/18 exact topic and region matches. The first held-out run matched both label sets on 14/18 articles, with 16/18 exact topic sets and 15/18 exact region sets. The following corrections were made after reading those results.

| Review case | Error and correction |
| --- | --- |
| Invezz EN 4 | A passing stock mention added a company topic to a software outage. Excerpt-only stock matches now require a market action or a specific market term. |
| Invezz EN 105 and DE 85 | Missing subject patterns caused regional labels to differ across translations. Company and equipment phrases now support both affected countries across the three versions. |
| Zacks 4 | The classifier missed the personal finance angle of a monetary policy story. The rule now recognizes household budgeting language. |
| ActionForex 2 | A fallback FX tag displaced the actual macroeconomic subject. The text rule now recognizes trade balances swinging to a deficit or surplus. |
| IBTimes UK 212 | A company name between the country adjective and the export restrictions prevented `NL` from matching. The rule now handles that construction. |
| Zacks 480 and 646 | The classifier missed countries named together in trade talks and the national retirement program. Both now have geographic rules. |

After those corrections, the rerun on the original held-out set matched both sets on 17/18 articles. This rerun measures regression coverage after tuning. Zacks 480 still receives an extra technology tag because the excerpt lists a semiconductor sector alongside other sectors.

A full-output spot check also found nine false `global` tags from a stock exchange segment name. The rule now requires a recognized worldwide impact phrase. The spot check prompted an additional country-subject rule that aligns tags across three versions of a story about a bank.

## Limitations

Geography is conservative and most feeds have sparse location coverage in headline and excerpt. The run yielded nine German tags and one Dutch tag. The topic rules can pick up incidental mentions and the location rules can miss implicit or body-only geography. `unknown` should be excluded from country-specific selection. Topic and region labels describe editorial relevance. Evidence offsets let reviewers inspect the classification against the original article.
