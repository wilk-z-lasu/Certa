# The Liquid Briefing

**Sourcera** · Challenge track · MAIN AI Hackathon 2026

Maastricht · 20 to 21 November 2026 · Track partner **Sourcera** · Data partner **Newstex**

> **How might AI turn a day of news into a personal audio briefing that fits each listener, and that they can trust?**

Teams get a week of real business and finance news. They group it into stories, decide what matters to a given listener, and turn it into an audio briefing for that person. Every number and claim in the audio has to trace back to the article it came from.

## What teams build

- **Make sense of the pile:** group articles into stories, merge duplicate coverage, extract the key facts and numbers.
- **Fit the listener:** the same news gives a clearly different briefing for a different person (length, depth, language or style).
- **Make it trustworthy:** every claim in the audio is linked to its source article.
- **Make it scale:** a newsroom gets thousands of articles a day. Sending all of them through a frontier model works for a demo but is too slow and too expensive to run daily. Use cheaper steps (embeddings, small models, rules) where they do the job, and keep the large model for what needs it.

## What we provide

| Item | Details |
|---|---|
| **News dataset** | One week of articles from Zacks, Invezz (English, German, Dutch), IBTimes UK and ActionForex, licensed for the event by Newstex. For use during the hackathon only; deleted afterwards. |
| **Official releases** | Public releases from the same week (central banks, statistics offices) to check the reporting against. |
| **Listener profiles** | Four profiles to build for, plus a wildcard handed out during the pitch. |
| **Answer key** | A key of the week's stories and facts, so the jury can check accuracy objectively. |
| **Support** | The Sourcera team is around during the build for questions about the data and newsroom workflows. |

## Judging

| Points | Criterion | What the jury looks at |
|---:|---|---|
| 25 | **Trust and accuracy** | Three claims from the audio, checked against their source articles. Numbers are right, nothing is invented, sources that disagree are flagged, and the briefing informs without giving investment advice. |
| 20 | **Fit to the listener** | Two listeners get clearly different briefings: different stories, order, depth, length or language, not just a different voice. Tested live with the wildcard listener. |
| 20 | **Making sense of the news** | Articles about the same event end up in one story, duplicates are merged, the extracted facts are correct, and the most important stories come first. Checked against the answer key. |
| 15 | **Scalability and cost** | The reported cost for the full dataset and the estimate at ten times the volume. Credit for using cheap steps where they work and the large model only where it is needed. |
| 10 | **Listening experience** | Would you listen to it tomorrow morning? Written for the ear, a clear structure, good pacing and a sensible length. |
| 10 | **Path to product** | Who would pay (publisher, listener or advertiser), how it fits into a newsroom's daily work, and how the synthetic voice is disclosed to listeners. |

## Deliverables

1. **Working prototype** — Generates audio briefings from the dataset for at least two listener profiles, with every claim linked to its source article.
2. **Presentation** — Problem, who pays, and what it costs to run the full dataset and ten times the volume.
