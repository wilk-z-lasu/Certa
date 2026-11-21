# Claim verification evaluation

## Cloud-only handoff and credit pause

The cloud-only build was interrupted at the user’s request to preserve remaining credits. Cached work was finalized with zero new API calls. It publishes 27 approved statements from 14 completed checks, with 26 further checks explicitly deferred and zero failed events. Source checks confirm the new headline/core CPI labels and publication-date formatting. Final cloud composition has not been tested. See [HANDOFF.md](HANDOFF.md) for the exact state, cache paths, grouping limitations and resume commands. The local-model measurements below describe earlier runs.

## Final local text run, November 21

The final `event-check-7` run imported all six feeds and accounted for 1,740 articles, 1,498 reporting origins and 1,464 events. A 115-day evaluation window includes the long Zacks date range. The normal preparation default remains seven days. The run explicitly limited model checking to 40 of 1,162 eligible event revisions. Thirty-seven completed and three were quarantined for invalid model output. The catalogue exposes 76 approved statements across 29 events. Other material remains internal and cannot supply listener text. The 302 events with unresolved grouping remain outside listener retrieval.

The shared producer-price event retained six approved statements drawn from ten reviewed passages, with approved coverage in seven editorial sections. Headlines and detailed drafts can select different subsets from the same stored revision. The local overview editor retains every approved claim. This measures retained source-backed breadth and does not imply that every source passage or every event has been verified.

| Live HTTP listener | Statements | Events | Transcript words | Model |
| --- | ---: | ---: | ---: | --- |
| English, UK, detailed, three-minute target | 10 | 4 | 195 | local 4B |
| English, euro area, headlines, one-minute target | 3 | 3 | 82 | local 4B |
| Dutch, general, standard, two-minute target | 9 | 4 | 197 | local 4B |

All three flows used actual local-model composition, passed the immutable draft/event/source/cutoff/caveat audit, opened evidence links, returned the same saved edition on repeat requests, and applied repeated feedback only once. Each profile advanced from version 1 to 2. The source audit covers 22 delivered statements across these live editions. The model receives only selectable claim aliases, an explicit allowed-ID schema and eligible coverage references. An integration regression covers the earlier identifier confusion. The current non-audio suite passes 61 tests. Saved text examples and audit results are under `output/backend-audit/`.

Three numeric statements from the actual English delivery were manually compared to article passages and official observations. Bank Rate was 4 percent on November 5. UK CPI was 3.6 percent year on year and 0.5 percent month on month in October. The monthly claim retains its preceding country/month context. Exact references are saved in `output/backend-audit/manual-claim-audit.json`. This is a text audit. ElevenLabs and listening checks remain deferred, including mocked ElevenLabs tests. Transcript lengths can fall short of the requested target and actual narration duration is unmeasured.

The final preparation replay took 88.778 seconds, reused 775 grouping decisions and 120 individual claim reviews, and made no new individual-review calls. Retries remain necessary for held classifier and model responses. An unchanged publication replay reused all 1,464 dossiers in 0.593 seconds. The original full-feed execution took 2,598.707 seconds and already reused some sample decisions. That earlier execution preceded the event-wide review and later source-audit corrections. These runs are separate development measurements, not a cold-versus-warm controlled benchmark.

The final cached preparation used 21,615 additional input/output tokens. The three successful writers used 14,720 tokens and took 23.104, 12.780 and 15.202 seconds respectively. Stage reports and the full-feed cost projection are under `output/full-model-run/`, including `cost-final.json`. Local model API fees were zero. The 10× report assumes the same routing, coverage fraction, revision frequency and cache mix. It excludes hardware, electricity, fixed subscriptions and speech. It does not estimate the cost of checking every event or establish a hosted-provider price. Hosted inference, the official answer key, organizer listener profiles and speech measurements remain unavailable.

## Daily backend audit, November 21

The current backend has separate immutable source imports, dated event catalogues, listener profile versions, personal drafts and final text. The documented offline preparation commands were rerun on November 17 and 18. All 1,740 source records were accounted for on each import and neither import added a source version. The respective date windows contained 644 and 806 articles. The later build reused 634 unchanged dossiers and retained both daily snapshots.

Three custom listener examples were run through saved preferences, a day-one delivery, daily feedback and a day-two delivery against the actual dataset. English with UK coverage received one claim followed by four new claims. English with euro-area coverage and headline depth received one followed by two. Dutch with general coverage received one followed by four. All profile versions changed from 1 to 2 after feedback. Every delivered sentence passed the immutable event revision, source span and cutoff audit. Generated examples and their audit results are under `output/backend-audit/`. These examples use deterministic composition so that the daily storage and feedback checks require no credentials.

The regression suite exercises the daily HTTP actions, isolation between listeners, composition leases, concurrent requests, a preference change during generation, historical source revisions, missing coverage, changed figures, daily feedback, repeat submissions and undo. A broad-event regression preserves five checked statements from the lead and later context, then creates one-claim and five-claim drafts from the same stored overview revision. An overview response that drops checked context is rejected.

Live local-model evaluation is separate from these deterministic checks. The 0.8B grouping model passed the targeted manual grouping reference. Its extraction role produced frequent malformed responses during broader checking, so the local extraction default now uses the installed 4B model. Extraction and review use separate prompts, source checks and caches. Local API fees are zero and hardware costs are excluded. The hosted provider path still requires credentials. ElevenLabs calls, mocked ElevenLabs tests and listening review are deferred at the user's request. The earlier recordings and measurements below describe an older Windows-voice replay.

The manual source audit found model-approved errors involving an annual basis added to an unqualified price change, invented causality, missing attribution, a heading interpreted as an observation and an incorrect investment owner. Regression checks now cover these failures. The paired reviewer probe accepted three correct statements, rejected one incorrect statement and accepted two incorrect statements. Source-scope checks reject the remaining two known errors. The probe results are saved in `output/editorial-evaluation/reviewer-probe.json`. This is a development check and provides no holdout accuracy estimate. The later audit also caught an award giver recast as its recipient, a changed family pronoun, an added country acronym and forecasts with changed temporal scope. Source checks now cover these patterns and remove supporting references that fail the checks. These conservative guards may hold valid paraphrases and do not establish a general accuracy rate. A source-only claim now records `official_state=not_checked`. A malformed translation is recorded and excluded for its language while checked wording in other languages remains available.

The November 20 replay processed 1,740 articles through the local reporting-origin handoff. It used six public releases, including the actual ONS Table 1 CSV. Of the 1,498 reporting origins, three contained claims that passed the deterministic rules. Together they supplied five verified figures. The other 1,495 origins produced no approved claims in this run. The two example briefings draw on these five figures.

| Full-corpus measure | Result |
|---|---:|
| Feed languages | 1,500 EN · 120 DE · 120 NL |
| Approved claims | 5 EN · 0 DE · 0 NL |
| Official observations after ONS CSV import | 60 across 6 releases |
| Cold verification wall time | 1.69 s |
| Cold load / rules and triage / model routing / conflict handling and storage | 0.315 / 1.302 / 0.002 / 0.072 s |
| Warm replay | 0.73 s, 1,740 rule-cache hits |
| Paid extraction and review calls | 0 |
| Verification-model cost at 1× / 10× under the same rules-only policy | $0 / $0 |
| Listener output | Headlines, 2 claims in 16.8 s · Rates, 5 claims in 36.9 s |

The 10× model-cost estimate assumes the same routing policy and 10× the new event revisions. Grouping, hardware and hosted speech costs are separate. Both WAVs used the installed English Windows voice. The live paid path needs an API key to measure its acceptance rate, latency and cost. A deterministic transport test exercises extraction, escalation, evidence validation, token accounting, cache reuse, and a stronger model agreeing with an incorrect article figure. The official answer key was unavailable. These results measure the narrow automatic path and its coverage.

## Trace from audio to source

Times refer to the Rates WAV. Each transcript sentence carries an event revision, claim ID, article permalink, Unicode evidence offsets, official release version, and official locator.

| Audio start | Observation | Article | Official check |
|---|---|---|---|
| 2.91 s | Bank of England decision of November 5, Bank Rate 4% | [ActionForex policy recap](https://www.actionforex.com/action-insight/market-overview/660977-canada-cpi-today-uk-cpi-wednesday-can-inflation-finally-break-gbp-cads-range/) | [BoE majority decision, opening paragraph](https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/november-2026) |
| 8.84 s | Euro-area HICP, October 2026, 4% year on year | [ActionForex euro-area report](https://www.actionforex.com/live-comments/661283-eurozone-inflation-confirmed-at-4-0-as-energy-surges-core-cpi-revised-higher/) | [Eurostat overview, euro-area aggregate](https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-18112026-ap) |
| 15.89 s | UK CPI, October 2026, 3.6% year on year | [ActionForex UK report](https://www.actionforex.com/live-comments/661264-uk-inflation-rises-to-3-6-as-fuel-prices-surge-core-cpi-holds-steady/) | [ONS Table 1, October row, CPI 12-month rate](https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/october2026) |
| 22.76 s | UK core CPI, October 2026, 2.8% year on year | Same UK report, core CPI sentence | Same ONS bulletin, Table 3, core CPI 12-month column |
| 29.78 s | UK CPI, October 2026, 0.5% month on month | Same UK report, monthly CPI sentence | Same ONS bulletin, Table 1, CPI 1-month column |

The final two UK claims carry the preceding context span establishing the country and month. Rules reject a country or period carried across an unrelated sentence. The BoE example distinguishes the majority decision from the separate rate proposed by a dissenter. The Eurostat bulletin's published timestamp was 10:00 UTC on November 18. The source article followed at 11:20 UTC. The corrected German release uses a conservative availability time of midnight following the correction date. [Destatis correction](https://www.destatis.de/EN/Press/2026/11/PE26_392_611.html)

## Coverage checks

The RSS discovery run found 43 release candidates dated November 13 through 19 in the available feeds. ONS supplied 19, Destatis 8, CBS 7, the ECB 6, and BoE 3. Candidate counts depend on feed retention. Only reviewed observations or imported table cells enter factual verification.

The regression suite swaps annual and monthly rates, CPI and CPIH, the reference month, and forecasts and actuals. It also covers conflicting reports, official corrections, release cutoffs, a genuinely reported number that changes with a revision, multilingual decimal commas, a shared reporting origin across translations, invented citation IDs, and edits to approved scripts. The German and Dutch automatic passes use controlled test articles. Corpus coverage in those languages still needs live extraction and an editorial audit.
