"""Build anchor-verified groups and stable event output records."""

from collections import defaultdict

from .event_candidates import conflicting_periods, fingerprint, matching_signature
from .luna import MODEL, PROMPT_VERSION
from .topic_rules import TOPICS


def form_groups(index, origins, comparisons, decisions):
    positive_neighbors = defaultdict(list)
    uncertain = set()
    for pair, decision in decisions.items():
        left, right = pair
        if decision.label == "same_event":
            positive_neighbors[right].append(left)
        elif decision.label == "uncertain":
            uncertain.update(pair)

    groups, assigned, missing, reviews = {}, {}, {}, {}
    for candidate in origins:
        possible_anchors = sorted({assigned[other] for other in positive_neighbors[candidate]})
        matches = []
        unresolved = False
        for anchor in possible_anchors:
            conflicts = any(
                conflicting_periods(index.articles[member], index.articles[candidate])
                or (
                    (decision := decisions.get((member, candidate))) is not None
                    and decision.label == "different_event"
                )
                for member in groups[anchor]
            )
            if conflicts:
                continue
            decision = decisions.get((anchor, candidate))
            if decision and decision.label == "same_event":
                matches.append(anchor)
            elif decision is None:
                pair = index.compare(anchor, candidate)
                if pair.within_window:
                    missing[pair.key] = pair
                unresolved = True
            elif decision.label == "uncertain":
                unresolved = True

        if len(matches) == 1 and not unresolved:
            anchor = matches[0]
        else:
            anchor = candidate
            if len(matches) > 1:
                reviews[candidate] = "multiple_matching_events"
            elif unresolved or candidate in uncertain:
                reviews[candidate] = "unconfirmed_event_match"
            elif possible_anchors:
                reviews[candidate] = "conflicting_event_match"
        groups.setdefault(anchor, []).append(candidate)
        assigned[candidate] = anchor

    # An uncertain comparison to an unrelated candidate does not block a
    # cluster that has since gained an independently confirmed member.
    reviews = {anchor: reason for anchor, reason in reviews.items() if len(groups[anchor]) == 1}
    shortlist = defaultdict(list)
    for pair in missing.values():
        if pair.key not in comparisons:
            shortlist[pair.right].append(pair)
    return groups, reviews, {
        pair.key: pair for pairs in shortlist.values()
        for pair in sorted(pairs, key=lambda pair: (-pair.score, pair.key))[:8]
    }


def stable_event_ids(groups, origins, articles, previous):
    available = {article.id: i for i, article in enumerate(articles)}
    previous_by_anchor = {}
    for event in previous:
        owner = available.get(event["anchor_article_id"])
        if owner is None:
            surviving = [available[s["article_id"]] for s in event.get("sources",[]) if s["article_id"] in available]
            if not surviving:
                continue
            owner = min(surviving)
        if owner in previous_by_anchor:
            raise ValueError("previous events share an anchor or surviving member")
        previous_by_anchor[owner] = event["event_id"]
    reserved = set(previous_by_anchor.values())
    for anchor, members in groups.items():
        carried = [previous_by_anchor[i] for i in sorted(i for member in members for i in origins[member]) if i in previous_by_anchor]
        event_id = carried[0] if carried else "evt_" + fingerprint(articles[anchor].id)[:24]
        if not carried and event_id in reserved:
            event_id = "evt_split_" + fingerprint(articles[anchor].id)[:24]
        yield anchor, event_id, carried[1:]


def event_records(groups, origins, reviews, origin_reviews, articles, decisions, previous, model=MODEL, prompt_version=None):
    review_candidates = defaultdict(list)
    for (left, right), decision in sorted(decisions.items()):
        for anchor, other in ((left, right), (right, left)):
            if anchor in reviews and decision.label != "different_event":
                review_candidates[anchor].append({
                    "article_id": articles[other].id, **decision.as_record(),
                })
    for anchor, event_id, superseded in stable_event_ids(groups, origins, articles, previous):
        sources, topics = [], set()
        reasons = [reviews[anchor]] if anchor in reviews else []
        for origin in groups[anchor]:
            canonical = articles[origin]
            origin_id = "origin_" + fingerprint(canonical.id)[:24]
            for i in origins[origin]:
                article = articles[i]
                topics.update(article.topics)
                if i == anchor:
                    grouping = {"method": "anchor"}
                elif i == origin:
                    same_signature = matching_signature(
                        articles[anchor], article,
                        round(abs((article.published - articles[anchor].published).total_seconds()) / 3600, 3),
                    )
                    grouping = {
                        "method": "occurrence_signature" if same_signature else "luna",
                        "matched_article_id": articles[anchor].id,
                        **decisions[(anchor, origin)].as_record(),
                    }
                else:
                    if article.body_hash and article.body_hash == canonical.body_hash:
                        method = "exact_copy"
                    elif article.language == canonical.language:
                        method = "near_copy"
                    else:
                        method = "invezz_thumbnail_translation" if model == "occurrence-rules" else "invezz_translation"
                    grouping = {"method": method, "matched_article_id": canonical.id}
                origin_uncertain = i in origin_reviews
                if origin_uncertain:
                    reasons.append("unconfirmed_translation")
                sources.append({
                    "article_id": article.id, "permalink": article.permalink,
                    "language": article.language, "published_at": article.published.isoformat(),
                    "reporting_origin_id": origin_id, "origin_needs_review": origin_uncertain,
                    "grouping": grouping,
                })

        status = "needs_review" if reasons else "grouped" if len(sources) > 1 else "singleton"
        yield {
            "event_id": event_id, "anchor_article_id": articles[anchor].id,
            "topics": [topic for topic in TOPICS if topic in topics],
            "status": status, "review_reasons": sorted(set(reasons)),
            "superseded_event_ids": superseded, "sources": sources,
            "review_candidates": review_candidates[anchor][:8],
            "grouping_model": model, "prompt_version": prompt_version or PROMPT_VERSION,
        }
