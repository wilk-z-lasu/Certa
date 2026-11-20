"""Reusable, local categorization of Newstex source articles."""

from collections.abc import Mapping

from .geography import classify_regions
from .topic_rules import (
    BROAD_SECTIONS,
    COMPILED_TOPICS,
    NEWSTEX_TOPIC,
    OTHER,
    SECTION_TOPIC,
    STOCK_EXCERPT,
    TOPICS,
    normalize_tag,
    span,
)


def validate_article(article: object) -> None:
    """Validate the fields consumed by this stage, allowing absent taxonomies."""
    if not isinstance(article, Mapping):
        raise ValueError("article must be a JSON object")

    for field in ("$id", "permalink", "language"):
        value = article.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")

    for field in ("headline", "excerpt"):
        value = article.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string when present")
    if not any((article.get(field) or "").strip() for field in ("headline", "excerpt")):
        raise ValueError("article must have a headline or excerpt")

    for field in ("provider_categories", "categories"):
        values = article.get(field)
        if values is not None and (not isinstance(values, list) or any(not isinstance(value, str) for value in values)):
            raise ValueError(f"{field} must be an array of strings when present")


def metadata_signals(tags: list[str], mapping: dict[str, str], rule: str, field: str) -> dict[str, list[dict]]:
    evidence = {}
    for index, tag in enumerate(tags):
        if topic := mapping.get(normalize_tag(tag)):
            evidence.setdefault(topic, []).append({"rule": rule, "field": field, "index": index})
    return evidence


def classify_topics(headline: str, excerpt: str, provider_tags: list[str], categories: list[str]) -> tuple[dict, list[str]]:
    evidence = {}
    review = []
    lead = excerpt[:400]
    for topic, rules in COMPILED_TOPICS.items():
        for name, pattern in rules.items():
            if match := pattern.search(headline):
                evidence.setdefault(topic, []).append(span(f"topic.{name}", "headline", match))
                continue
            lead_pattern = STOCK_EXCERPT if name == "stocks_and_funds" else pattern
            if match := lead_pattern.search(lead):
                evidence.setdefault(topic, []).append(span(f"topic.{name}", "excerpt", match))

    publisher = metadata_signals(provider_tags, SECTION_TOPIC, "topic.publisher_section", "provider_categories")
    broad = metadata_signals(provider_tags, BROAD_SECTIONS, "topic.broad_section", "provider_categories")
    newstex = metadata_signals(categories, NEWSTEX_TOPIC, "topic.newstex_code", "categories")

    for topic, matches in publisher.items():
        if topic == OTHER and evidence and OTHER not in evidence:
            review.append("publisher_section_disagrees_with_text")
            continue
        if topic not in evidence and evidence.keys() - publisher.keys():
            review.append("publisher_section_disagrees_with_text")
        evidence.setdefault(topic, []).extend(matches)

    for topic, matches in broad.items():
        if topic in evidence:
            evidence[topic].extend(matches)

    if not evidence:
        evidence = dict(broad)
        for topic, matches in newstex.items():
            evidence.setdefault(topic, []).extend(matches)
        if evidence:
            review.append("topic_from_weak_metadata")
        else:
            evidence = {OTHER: [{"rule": "topic.no_supported_topic"}]}
            review.append("no_supported_topic")

    return {topic: evidence[topic] for topic in TOPICS if topic in evidence}, sorted(set(review))


def categorize_article(article: Mapping) -> dict:
    """Return stable topic and region labels with references to their inputs."""
    validate_article(article)
    headline = article.get("headline") or ""
    excerpt = article.get("excerpt") or ""
    provider_tags = article.get("provider_categories") or []
    topics, topic_review = classify_topics(headline, excerpt, provider_tags, article.get("categories") or [])
    regions, region_review = classify_regions(headline, excerpt, provider_tags)
    review_reasons = topic_review + region_review
    return {
        "article_id": article["$id"],
        "permalink": article["permalink"],
        "language": article["language"],
        "topics": list(topics),
        "regions": sorted(regions) if regions else ["unknown"],
        "evidence": {"topics": topics, "regions": {code: regions[code] for code in sorted(regions)}},
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
    }
