The Liquid Briefing: dataset for the Sourcera challenge track
MAIN AI Hackathon, Maastricht, 20 to 21 November 2026
Data provided by Newstex

LICENCE TERMS (you agreed to these in the sign-up form)
- Use this data only for the MAIN AI Hackathon 2026.
- Do not republish article text, in your demo, repository or anywhere else.
  Short quotes and links to the source article are fine.
- Do not share these files with anyone outside your team.
- Delete all copies after the event. We will email you to confirm.

WHAT IS IN HERE
One JSONL file per feed. Each line is one article as a JSON object.

  zacks.jsonl         Zacks Investment Research, English. A sample of
                      1,000 articles from 28 July to 18 November 2026.
  invezz_en.jsonl     Invezz, English, from 13 November 2026
  invezz_de.jsonl     Invezz, German, from 13 November 2026
  invezz_nl.jsonl     Invezz, Dutch, from 13 November 2026
  ibtimes_uk.jsonl    International Business Times UK, English, from 13 November 2026
  actionforex.jsonl   ActionForex, English, from 13 November 2026

1,740 articles in total, as of 19 November 2026.

See IDEAS_AND_TIPS.txt for project directions and facts about the data.

USEFUL FIELDS
  headline             Title of the article
  date                 Publication time (ISO 8601, UTC)
  language             en, de or nl
  source               Author
  excerpt              Short summary
  text_content         Full article text, plain text
  html_content         Full article text, HTML
  categories           Newstex categories (missing on a few articles)
  provider_categories  The publisher's own categories (missing on a few articles)
  company_tickers      Tickers Newstex tagged in the article (may be empty)
  permalink            Link to the original article. Use it as the source link.
  publication.name     Name of the outlet
  $id                  Unique article ID

Reading a file in Python:

  import json
  articles = [json.loads(line) for line in open("invezz_en.jsonl", encoding="utf-8")]

QUESTIONS
Find the Sourcera team at the event, or email kariko@sourcera.news.
