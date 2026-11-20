# VoxNews build plan

Build a personalized daily audio news briefing whose factual claims can be checked against the articles that support them. This backlog starts with the hackathon MVP, then covers work needed for a running product.

The repository currently contains the challenge brief and article dataset; there is no application implementation yet. All tasks below are open. Requirements come from [the challenge brief](Sourcera-Track-Description.md), [project instructions](AGENTS.md), and [dataset notes](liquid-briefing-data/README.txt).

## How to use this backlog

- Work through the dependencies shown on each task. Check a task off only when its completion condition is met.
- **P0:** required for the complete MVP, including preferences, daily feedback, and evidence tracking.
- **P1:** evaluation and delivery tasks required before presenting the prototype.
- **P2:** product work after the MVP.
- Save evaluation results and known limitations alongside the implementation. A checked task means its behavior has been demonstrated, not just that code exists.

## MVP: foundation and article processing

- [ ] **F01 · P0 · Establish the runnable application.** Choose and document the application stack, storage, model and speech providers, configuration, and a command to run locally. **Done when:** a teammate can start the application from documented setup steps without committing credentials.

- [ ] **F02 · P0 · Define the records passed between stages.** Define article, story, claim/evidence, listener profile, briefing, and daily feedback records with stable IDs and processing versions. Preserve the chain `article → claim → story → script segment → audio segment`, plus the profile version used for each briefing. **Depends on:** F01. **Done when:** example records demonstrate all links and can be stored and loaded.

- [ ] **F03 · P0 · Import and validate the dataset.** Load all six JSONL feeds; preserve article IDs, source permalinks, publication, language, dates, and source text for internal processing. Report invalid records and missing fields; make reimports safe without duplicating records. **Depends on:** F02. **Done when:** an import report accounts for every input record and repeating the import adds no duplicates.

- [ ] **F04 · P0 · Define the briefing's date window.** Use an explicit briefing date and configurable lookback period; treat older articles as dated context. Account for the much longer Zacks date range. **Depends on:** F03. **Done when:** a historical daily run uses only information available by its cutoff and labels older context correctly.

- [ ] **F05 · P0 · Respect the dataset's usage terms.** Keep full article text in internal processing; expose source links and permitted short excerpts in the demo. Document deletion of dataset copies and derived artifacts containing licensed text after the event. **Depends on:** F03. **Done when:** the demo does not republish article bodies and the cleanup procedure identifies stored copies and outputs.

## MVP: content classification and story grouping

- [ ] **C01 · P0 · Define a shared topic taxonomy.** Start with economy and central banks, companies and stocks, currencies, crypto, technology and AI, politics and world, and other news. Allow multiple topics per article, with separate language, geography, and entity fields. **Depends on:** F02. **Done when:** each topic has a description and representative labeled examples.

- [ ] **C02 · P0 · Classify articles consistently.** Map publisher categories into the taxonomy, then use article text and an inexpensive classifier where tags are missing or ambiguous. Store the classification method and uncertainty. Do not use the supplied POSITIVE/NEGATIVE tags as trust signals. **Depends on:** F03, C01. **Done when:** a reviewed sample across all feeds and languages has recorded errors and corrections, and uncertain classifications remain identifiable.

- [ ] **C03 · P0 · Merge duplicate and translated coverage.** Detect exact copies and near duplicates, including English, German, and Dutch versions of the same Invezz article. Retain every source link and identify shared reporting origins. **Depends on:** C02. **Done when:** translations and copies count as one reporting origin when assessing corroboration.

- [ ] **C04 · P0 · Group articles about the same event.** Use time, entities, and semantic similarity to create story groups across outlets and languages. Keep distinct events involving the same company separate. **Depends on:** F04, C03. **Done when:** reviewed examples include a merged event across outlets and two separate events about the same entity, with traceable group membership.

- [ ] **C05 · P0 · Rank editorial importance.** Rank stories using recency, event significance, and breadth of impact before applying listener preferences. Prevent duplicate volume or the size of the Zacks feed from dominating the ranking. **Depends on:** C04. **Done when:** each selected story has an inspectable ranking explanation and repeated coverage does not create repeated briefing items.

## MVP: claim evidence and trustworthiness

Trust ratings describe the evidence supporting individual claims. They do not certify that an article, publisher, or claim is true. Store evidence states and reasons rather than an unexplained numerical trust score.

- [ ] **T01 · P0 · Extract claims with evidence.** Extract factual claims, figures, units, currencies, dates, attribution, and whether a statement is reporting, allegation, forecast, or analysis. Attach each claim to article IDs, permalinks, and internal supporting passages or offsets. **Depends on:** F02, C04. **Done when:** a reviewer can locate the exact source support for every extracted claim in a sample story.

- [ ] **T02 · P0 · Assign explainable evidence states.** Use `supported` for a claim supported by one reporting origin, `corroborated` for agreement across independent origins, `disputed` for conflicting evidence, and `unsupported` when no adequate source support exists. Record supporting and contradicting evidence and a reason; conflict takes precedence over agreement. **Depends on:** C03, T01. **Done when:** examples exercise all four states and copied or translated reports cannot inflate corroboration.

- [ ] **T03 · P0 · Check numbers and official releases.** Compare extracted values and their dates, units, and context with the cited passages; use relevant official releases when available. Distinguish revisions, reporting periods, estimates, and actual results. **Depends on:** T01. **Done when:** mismatched values are flagged and source support is distinguished from external verification; unavailable releases remain a documented limitation.

- [ ] **T04 · P0 · Handle conflicts and insufficient evidence.** Preserve disagreements instead of selecting a convenient value. Exclude unsupported claims; allow disputed claims only with explicit attribution and an audible explanation of the disagreement. **Depends on:** T02, T03. **Done when:** conflicting figures remain visible in the evidence view and the script either explains the conflict or omits the claim.

- [ ] **T05 · P0 · Provide a claim inspection view.** Show each briefing claim, evidence state, explanation, source links, and any disagreement, accessible from its story or transcript segment. **Depends on:** T04. **Done when:** a reviewer can trace three selected spoken claims to their supporting articles without searching the dataset manually.

## MVP: listener preferences and personalization

- [ ] **L01 · P0 · Build structured listener setup.** Collect topics to hear more or less about, preferred language, target duration, and desired depth. Provide editable defaults and avoid requiring financial holdings or other unnecessary personal data. **Depends on:** C01, F02. **Done when:** a new listener can save a complete profile through a short form.

- [ ] **L02 · P0 · Save editable, versioned profiles.** Persist each listener's choices with timestamps and distinguish explicit settings from changes learned through feedback. **Depends on:** L01. **Done when:** reloading retains preferences and each briefing can identify the exact profile version used.

- [ ] **L03 · P0 · Personalize story selection and delivery.** Combine editorial importance with topic preferences, then fit selection and depth to the requested language and duration. Provide a short reason for including each story. Preferences must not weaken evidence requirements or remove necessary uncertainty. **Depends on:** C05, T04, L02. **Done when:** the same news produces clearly different story selection, order, depth, length, or language for two contrasting profiles.

- [ ] **L04 · P0 · Handle sparse coverage.** Produce a shorter briefing or offer clearly labeled adjacent coverage when there is insufficient relevant, supported news; do not fill the duration with invented material. **Depends on:** L03. **Done when:** an unusual topic profile can receive a useful result with the coverage limitation explained.

## MVP: script, audio, and listening interface

- [ ] **B01 · P0 · Generate scripts from eligible claims.** Write a concise introduction, ordered stories, transitions, and closing using the selected claims. Keep factual statements linked to claim IDs, retain attribution, distinguish analysis and forecasts, and avoid investment recommendations. **Depends on:** L03, L04. **Done when:** every factual script statement has source support and a review finds no invented details or investment advice.

- [ ] **B02 · P0 · Validate the final script before narration.** Recheck factual statements, spoken numbers, translated wording, and disagreements against their evidence. Block narration when a statement lacks support; preserve the validation result with the script. **Depends on:** B01, T03, T04. **Done when:** a deliberately introduced unsupported statement or changed figure prevents audio generation.

- [ ] **B03 · P0 · Generate and store audio.** Narrate the validated script with clear pronunciation, pacing, and a spoken synthetic-voice disclosure. Record the script version and connect audio segments to stories and claims. **Depends on:** B02. **Done when:** playable audio matches the validated script, has a measured duration, and retains provenance.

- [ ] **B04 · P0 · Build the daily briefing screen.** Provide playback, a transcript, story navigation, access to evidence and source links, and profile editing. Show the briefing date and synthetic narration disclosure. **Depends on:** B03, T05, L02. **Done when:** a listener can complete setup, hear a briefing, and inspect a claim in one application flow.

## MVP: daily feedback and adjustment

- [ ] **D01 · P0 · Add a quick daily check-in.** Ask whether the briefing was useful, whether its length and depth fit, and which topics should receive more or less coverage. Add the check-in to the briefing screen after listening or on return, allow skipping, and associate answers with that listener's briefing. **Depends on:** B04. **Done when:** a listener can submit a short check-in or skip it without blocking playback.

- [ ] **D02 · P0 · Apply feedback to the next briefing.** Update topic weights, duration, and depth automatically when the answers request those changes. Apply explicit choices directly, bound relative adjustments to supported settings, and do not infer topic preferences from a usefulness rating alone. Missing feedback leaves the profile unchanged. **Depends on:** D01, L02. **Done when:** a saved check-in changes the next briefing's relevant selection or delivery while leaving evidence requirements intact.

- [ ] **D03 · P0 · Make adjustments visible and reversible.** Show a brief explanation such as “More technology stories and a shorter briefing tomorrow,” save the feedback and profile change history, and allow the listener to edit or undo the adjustment. Avoid applying a submitted response twice. **Depends on:** D02. **Done when:** the listener can inspect and reverse a change and a repeated submission does not compound it.

- [ ] **D04 · P0 · Demonstrate the daily cycle.** Run consecutive historical briefing dates, retain listening history, and distinguish new events or material updates from previously covered stories. **Depends on:** F04, B04, D03. **Done when:** day one's feedback visibly affects day two and an unchanged story is not presented as a new event.

## MVP: evaluation, cost, and presentation

- [ ] **E01 · P1 · Evaluate grouping and extraction.** Obtain the supplied answer key and compare story grouping, duplicate handling, important-story ranking, and extracted facts against it. Use a clearly labeled manual reference sample until the official key is available. **Depends on:** C05, T04. **Done when:** results and representative failures are recorded; manual review is not presented as an official answer-key result.

- [ ] **E02 · P1 · Audit claims from the actual audio.** Check at least three spoken claims against their source articles, including a numeric claim; inspect conflict handling and the full provenance chain. **Depends on:** B04. **Done when:** the audit records the spoken wording, source support, exact values and context, and any limitations, with all discovered unsupported statements corrected before the demo.

- [ ] **E03 · P1 · Evaluate listener fit and feedback.** Demonstrate two contrasting profiles, accept a new wildcard profile without code changes, and demonstrate a daily check-in changing the following briefing. Exercise missing feedback, sparse coverage, undo, and repeated submissions. **Depends on:** D04. **Done when:** the comparison explains observable editorial differences and the feedback scenarios behave as specified.

- [ ] **E04 · P1 · Review the listening experience.** Listen to complete briefings in the supported demo languages, checking pacing, pronunciation, understandable numbers, structure, and requested versus actual duration. **Depends on:** B04. **Done when:** target durations and acceptable tolerances are documented and any remaining listening issues are recorded.

- [ ] **E05 · P1 · Measure processing cost and scale.** Record model, token, speech, latency, retry, and cache usage by stage; reuse shared article processing across listeners. Report measured full-dataset cost and a 10× volume estimate with article volume, listener count, audio minutes, provider rates, and pricing date stated. **Depends on:** F01, B03. **Done when:** the report separates measured costs from projections and explains which stages use rules, embeddings, inexpensive models, or larger models.

- [ ] **E06 · P1 · Prepare a repeatable demo and product pitch.** Document the run sequence, two profiles, claim audit, feedback cycle, and wildcard setup. Explain the proposed payer, newsroom workflow, synthetic voice disclosure, costs, and current limitations. **Depends on:** E01–E05. **Done when:** another teammate can reproduce the demo and the presentation covers both challenge deliverables.

## After the MVP: product readiness

- [ ] **P01 · P2 · Validate the customer and payer.** Test publisher, listener, and advertiser propositions with prospective users; select the first customer segment, pricing hypothesis, and pilot success measures. **Depends on:** E06. **Done when:** documented customer evidence supports a pilot proposal and its unit economics.

- [ ] **P02 · P2 · Integrate a newsroom review workflow.** Add editorial review, corrections, source-policy management, and approval before publication where required. Propagate corrections into affected claims, scripts, audio, and listener notices. **Depends on:** T05, P01. **Done when:** an editor can trace and correct a published briefing through an auditable workflow.

- [ ] **P03 · P2 · Build reliable daily operations.** Add licensed live ingestion, scheduling by listener timezone, incremental processing, job retries, failure reporting, and monitoring for stale news, missing evidence, failed audio, latency, and cost. **Depends on:** E05, P01. **Done when:** a pilot can run on consecutive days, recover from a failed stage, and report incomplete runs accurately.

- [ ] **P04 · P2 · Add account and privacy controls.** Isolate listener data, define retention for profiles and feedback, provide export and deletion, and secure internal source text and evidence. Establish content rights for use beyond the event. **Depends on:** P01. **Done when:** pilot users have working account controls and documented permissions and retention rules cover stored data and generated outputs.

- [ ] **P05 · P2 · Evaluate personalization over time.** Measure usefulness, listening completion, coverage diversity, profile drift, and correction rates; add per-story feedback only after validating the daily check-in. Preserve explicit listener control and shared trust requirements. **Depends on:** D04, P03, P04. **Done when:** a pilot review shows whether adjustments improve listener fit and identifies unwanted narrowing or repeated preference changes.

## MVP acceptance and defaults

The MVP is ready when all P0 tasks work together and all P1 evaluation and delivery tasks are complete. The six judging criteria remain the priority order: trust and accuracy (25%), listener fit (20%), sense-making (20%), scalability and cost (15%), listening experience (10%), and path to product (10%).

- Classification uses a normalized taxonomy; existing publisher tags are inputs, with text-based fallback.
- Trust is explained per claim through evidence states, source independence, and visible disagreements. Source agreement alone does not establish truth.
- Listener setup is structured. Daily feedback automatically changes the next briefing, with visible, editable, reversible updates.
- The MVP uses an in-application daily check-in and historical dates to demonstrate adaptation; production scheduling belongs to P03.
- Official releases, supplied listener profiles, and the answer key are mentioned in the challenge brief but are not currently present in the repository. Track their availability and label substitute evaluation material.
- Stack and provider selection belongs to F01. Actual prices and supported speech languages must be checked when providers are selected.
