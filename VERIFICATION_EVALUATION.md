# Claim verification evaluation

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
