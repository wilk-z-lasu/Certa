# Event grouping evaluation

## Rules-only full-feed run

```powershell
python -m certa.daily --offline --date 2026-11-19 --lookback-days 366 --output-dir output/grouping-evaluation
python -m certa.evaluate grouping output/grouping-evaluation/days/2026-11-19/events.jsonl
```

The full window contains 1,740 unique article memberships, 1,548 reporting origins, and 1,540 events (100 grouped, 1,440 singletons). The 366-day lookback includes older Zacks rows. It is an evaluation window. The briefing uses its configured editorial window. The rules-only run made zero model calls.

All six positives and all five negatives in the bundled manual development reference matched their expected final memberships. In particular, ActionForex and Invezz matched on the country, producer price indicator, October reporting period, and same-day publication. The Outlook match used explicit service-outage statements linking the same company and product within hours. The two cross-month US CPI articles, the Canadian and UK CPI articles, and the two reports of distinct Intel corporate developments stayed separate.

The hosted path uses the same strong occurrence signatures ahead of model review and includes the derived descriptors when sending other pairs to the grouping model. No hosted rerun was made for this evaluation, and the official answer key is unavailable. The manual pairs guided development and cannot establish holdout performance, full-corpus precision or recall, or how the model handles the remaining pairs.

The local run collapsed 188 German and Dutch publisher variants based on a shared non-placeholder thumbnail URL unique in each corresponding feed within the window, matching byline, close publication time and compatible reporting periods. This is a conservative publication metadata heuristic. It does not independently verify origin or translation fidelity. Reused or inconclusive signals leave articles separate. The model route still uses its own embedding-backed translation match.

The full rules-only catalogue approved 15 claims. Five matched dated official values and 10 were article-attributed developments from bounded reporting clauses. The latter include service outages, a shareholder allegation, an IPO pricing report, company earnings, a factory plan attributed to Reuters, and a traded Bitcoin price distinct from a forward target in the same lead. The catalogue records source URLs and clause offsets and offers fixed English, German and Dutch wording. The admitted formats provide selective coverage and do not attempt general article verification.

## Local-model final memberships, November 20

The completed full-feed run also preserves every article ID exactly once. It produces 1,464 events, consisting of 1,087 singletons, 302 cases held for grouping review and 75 grouped events. All six positive and five negative manual reference pairs still match their labels in this full output. The final replay reuses 775 cached decisions. The score is saved under `output/full-model-run/grouping-score.json`. These development references provide no full-corpus or holdout accuracy estimate.

The backend integration sample contains 22 source articles from all six feeds and 20 reporting origins. E5 candidate selection and the installed `qwen3.5:0.8b-mlx` grouping model produced 15 events. Final memberships matched all six labeled positive pairs and all five labeled negative pairs in `examples/manual-event-reference.json`. The positive pairs include the Outlook outage, US producer prices, Intel lawsuit and Deutsche Bank leak. The negative examples include distinct occurrences involving the same company and releases from different countries or months.

These are targeted manual references used during development. The official answer key and a separate holdout evaluation remain unavailable. The evaluation can be rerun with `python3 -m certa.evaluate grouping output/editorial-evaluation/run/days/2026-11-19/events.jsonl`. The older candidate and hosted-cost estimates below describe earlier runs.

## Full-corpus candidate run

| Measure | Result |
| --- | ---: |
| Source articles accounted for | 1,740 |
| Reporting origins after local copy and translation checks | 1,498 |
| Additional articles linked to those origins | 242 |
| Plausible translation matches flagged for review | 0 |
| Candidate pairs after combining each article's shortlist | 8,575 |
| Initial Luna batches at 24 pairs per batch | 358 |
| Local load and embedding time | 33.83 s |
| Local shortlist time | 1.06 s |
| Total local candidate run time | 34.94 s |
| Estimated local time at 10× volume over the same dates | 445 s |

The time projection scales encoding and other local work linearly and comparisons within each date window quadratically. The local model was the official E5-small ONNX model on CPU. The candidate run made zero Luna requests.

## Manual review

The official answer key was unavailable. This targeted sample uses one-based lines in the original JSONL feeds. It measures whether the candidate stage surfaced the matching articles. A shortlisted pair still needs an event decision.

| Expected match | Source rows | Candidate result |
| --- | --- | --- |
| October US producer-price release | ActionForex 3 and Invezz EN 15 | Shortlisted |
| Intel shareholder lawsuit | IBTimes UK 161 and Invezz EN 47 | Shortlisted |
| Microsoft email outage | IBTimes UK 4 and Invezz EN 4 | Shortlisted |
| Deutsche Bank records leak | IBTimes UK 237 and 265 and Invezz EN 99 | All three pairs shortlisted |

Candidate recall was **6/6** for these pairs. The German and Dutch versions of the possible Tesla–SpaceX merger, the Outlook outage, the German factory investment, and the optical-equipment stock report each shared an origin with their English counterpart. The initial similarity threshold missed two Outlook translations. Matching outage and product features now allow a lower threshold for that kind of strongly supported match.

| Expected distinct occurrences | Source rows | Candidate result |
| --- | --- | --- |
| Intel lawsuit and a later Nvidia stake reduction | Invezz EN 47 and 103 | Shortlisted |
| Canadian and UK CPI releases | ActionForex 14 and 32 | Shortlisted |
| US CPI releases in different months | Zacks 409 and 679 | Outside the window |
| Nvidia chief executive departure and a Senate summons | Invezz EN 29 and IBTimes UK 10 | Outside the shortlist |
| Possible Tesla–SpaceX merger and a factory investment | Invezz EN 2 and 75 | Outside the window |

The live evaluation should measure pairwise precision and recall from final event IDs, including these same-entity and same-indicator negatives. A review singleton counts as a missed match when its labeled counterpart belongs to the same event. Final grouping precision, recall, and editorial review volume require live Luna decisions.

## Replay and cost

A full-corpus integration replay used real embeddings and a simulated transport that returned `uncertain` for every pair. It preserved all 1,740 article IDs exactly once. A second run reused all 8,575 cached decisions, invoked the transport zero times, and produced byte-identical JSONL. The simulated output and cache were temporary. The synthetic unit tests also cover positive merges, conflicting matches, API retries, and late arrivals.

The shell had no `OPENAI_API_KEY`, so measured live Luna latency, token usage, and billed cost are unavailable. Initial requests totaled about 4.44 million characters of descriptors, instructions, and schema. At four characters per input token and 50 output tokens per pair including reasoning, that projects roughly 1.11 million input tokens and 429,000 output tokens. At standard rates on November 20, 2026, the initial pass would cost about **$0.33**, or **$3.25** at 10× pair volume. Anchor checks and retries can increase the total. Cached inputs or decisions can lower it. [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
