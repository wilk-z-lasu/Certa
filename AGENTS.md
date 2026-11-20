# Project overview: Personal Audio News Briefings You Can Trust

## What we are building

Build a trustworthy, personalized audio news briefing from source articles. The system should identify the important stories, combine coverage of the same event, verify the facts it uses, and turn the result into a clear spoken briefing that fits the listener. It should be practical to run at scale and have a credible path into a newsroom or other product.

Treat accuracy and listener trust as core product requirements. Do not invent details, silently resolve conflicts between sources, or turn reporting into investment advice. Keep claims traceable to their source articles, and make synthetic narration clear to listeners.

## Evaluation criteria

Use these six criteria to guide product and engineering decisions. The percentages are their evaluation weights.

1. **Trust and accuracy — 25%**
   Check three claims from the audio against their source articles. Numbers must be right, nothing may be invented, disagreements among sources must be flagged, and the briefing must inform without giving investment advice.
2. **Fit to the listener — 20%**
   Two listeners should receive clearly different briefings. Differences may include story selection, order, depth, length, or language; changing only the voice is not enough. Test live with the wildcard listener.
3. **Making sense of the news — 20%**
   Articles about the same event should become one story, duplicates should be merged, extracted facts should be correct, and the most important stories should come first. Check against the answer key.
4. **Scalability and cost — 15%**
   Report the cost for the full dataset and estimate cost at ten times the volume. Use inexpensive steps where they work and reserve the large model for tasks that need it.
5. **Listening experience — 10%**
   Write for the ear, with a clear structure, good pacing, and a sensible length. The intended experience is one a listener would choose tomorrow morning.
6. **Path to product — 10%**
   Explain who would pay (publisher, listener, or advertiser), how the briefing fits into a newsroom's daily work, and how synthetic voice is disclosed to listeners.

## Guidance for agents

- Read the existing implementation and data before making assumptions; the repository may still be a starting point.
- Preserve provenance from source article through extracted facts, story grouping, script, and audio so claims can be checked.
- Prefer structured, auditable intermediate results over unsupported prose. Keep uncertainty and source disagreement visible.
- Personalization must affect editorial choices or delivery (such as selection, order, depth, length, or language), not only voice characteristics.
- When changing the pipeline, consider answer-key evaluation, per-stage cost, full-dataset cost, and a 10x volume estimate.
- Keep spoken copy concise and natural. Clearly separate factual reporting from analysis, and do not provide investment recommendations.
- Document assumptions and limitations that affect trust, evaluation, operations, or product readiness.
