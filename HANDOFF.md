# VoxNews handoff — November 21

Cloud-only mode is implemented. Paid OpenAI requests are paused to protect the user's reported remaining $3. Resume paid work only with a funded key. The request already in flight at interruption may still have been billed. No new paid requests were initiated during cache-only finalization.

**Current state**

- The app runs at `http://127.0.0.1:50488/`. `/api/runtime` confirms `cloud_only=true` and `api_requests_paused=true`.
- The bare key was normalized to `OPENAI_API_KEY=…` and authenticated successfully. It remains in ignored `.env` with owner-only permissions. Never commit or paste its value.
- Demo inference uses OpenAI, including `text-embedding-3-small`, GPT-6 Luna for classification/grouping/extraction, and GPT-6.2 Astra for review/overviews/composition. Ollama, local E5, cached local overviews and offline writer fallback are blocked.
- Cloud data is isolated in `output/cloud-demo/`; listener history is in `user_data/cloud-demo/`. User settings were carried over. Earlier local-model results remain archived separately.
- All 1,740 source articles were imported. The seven-day November 19 window contains 811 articles and 616 event records. Cloud embeddings and grouping are complete and cached.
- Fourteen event checks completed, publishing 27 approved statements. Twenty-six selected events are explicitly deferred by the API pause. The final snapshot has zero failed events.
- Cache-only finalization made zero new classification, embedding, grouping or verification API calls. These zero-cost replay metrics do not represent the earlier interrupted cloud run's billing.
- Seventy non-audio regression tests pass, along with static and whitespace checks. Tests make no paid requests.

**Inflation and dates**

The dataset's 3.6% is UK headline CPI. The 2.8% is core CPI excluding energy, food, alcohol and tobacco. The 0.5% is the month-on-month CPI change. All refer to October 2026. November 16/18 identify publication dates of reporting; the Bank Rate statement describes a November 5 decision.

New cloud records explain headline and core CPI explicitly. New transcripts say “Reporting published on 16 November 2026.” Archived editions keep their original rendering. The default lookback is seven days. `--lookback-days 1` restricts article publication to the selected UTC day; it does not change dates of events or measurement periods described in an article.

**Inspect without spending credits**

```sh
python3 tests/check_backend.py
python3 app.py --cloud-only --port 50500
```

Use 50500 if the existing server occupies 50488. Browsing the catalogue and evidence works; generating a new final briefing is blocked by the credit pause.

`output/cloud-demo/backend-audit/draft-preview.md` and `draft-preview.json` contain a 21-claim draft with cloud provenance. `inflation-check.json` records the source checks. This is an approved-claim draft preview, not a composition-model result or narrated briefing. Creating it made no API requests.

The current run is saved in `output/cloud-demo/days/2026-11-19/report.json` and `verification.json`. Preserve the caches to avoid paying for completed work again.

These generated files and caches are local and ignored by Git. A teammate on another machine must use this checkout or receive the `output/cloud-demo/` folder through the team's authorized file transfer. The folder includes licensed source material and belongs only in the hackathon team's permitted environment. Do not transfer `.env` or put generated source data in Git. Without the caches, the resume command starts a new paid build.

**Resume when funded**

Put the funded teammate's `OPENAI_API_KEY` in their own ignored `.env`, set `VOXNEWS_API_REQUESTS_PAUSED=0`, then run:

```sh
python3 -m voxnews.demo --date 2026-11-19 --model-events 40
python3 app.py --cloud-only --port 50500
```

Restart the server after changing credentials or pause settings. Environment values loaded at startup take precedence. Preparation reuses cloud caches and completes the deferred event-wide checks, overview batches and translation reviews. The 40-event limit is intentional; every event in the dataset has not been verified.

Then test actual cloud-composed deliveries through the app, audit three claims and compare listener profiles. Final cloud-composition HTTP checks were not run before the budget pause. The earlier *local-model* HTTP results are separate and must not be presented as cloud verification. ElevenLabs testing remains deferred at the user's request.

**Known evaluation work**

The cloud grouping sample has four correct positive matches, two missed positives, four correct negatives and one pair outside the seven-day window. The missed matches are the US producer-price release and the Microsoft/Outlook outage. All six positive pairs were retained as candidates. Inspect hosted grouping descriptors and decision confidence; the hosted payload currently emphasizes extracted features. Consider adding bounded headline/lead context, then evaluate final memberships again. Changed inputs/models require newly checked event revisions. The earlier local-model perfect sample score is not the cloud result. The official answer key remains unavailable.

The API pause is enforced before OpenAI transports and uncached claim calls. Cached responses remain usable. Missing checks are deferred and their claims cannot be served. No new narration was generated or tested during this work.
