from __future__ import annotations

import difflib
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from fastapi import HTTPException

from app.core.cache import cache_get, cache_set
from app.core.config import CACHE_TTL_SECONDS
from app.services.news_service import get_news_payload

LEARNING_CONTENT_PATH = Path("app/data/learning_content.json")
POPULAR_CONCEPT_KEYS = [
    "inflation",
    "interest rate",
    "stock",
    "bond",
    "dividend",
    "market cap",
    "recession",
    "savings",
    "investment",
    "profit",
]
LEARNING_NEWS_TTL_SECONDS = max(CACHE_TTL_SECONDS, 600)


class LearningContentError(RuntimeError):
    pass


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def load_learning_content() -> Dict[str, Dict[str, Any]]:
    cache_key = ("learning-content", "all", "v1")
    cached = cache_get(cache_key)
    if cached:
        return cached["content"]

    if not LEARNING_CONTENT_PATH.exists():
        raise LearningContentError(f"Learning content file not found: {LEARNING_CONTENT_PATH}")

    try:
        with LEARNING_CONTENT_PATH.open("r", encoding="utf-8") as f:
            content = json.load(f)
    except json.JSONDecodeError as exc:
        raise LearningContentError("Learning content JSON is invalid.") from exc

    if not isinstance(content, dict):
        raise LearningContentError("Learning content must be a JSON object keyed by concept.")

    normalized: Dict[str, Dict[str, Any]] = {}
    for key, concept in content.items():
        if not isinstance(concept, dict):
            continue
        normalized[_normalize(key)] = concept

    cache_set(cache_key, {"content": normalized}, ttl_seconds=CACHE_TTL_SECONDS)
    return normalized


def suggest_similar_terms(term: str, limit: int = 5) -> List[str]:
    query = _normalize(term)
    if not query:
        return []

    content = load_learning_content()
    keys = list(content.keys())

    starts_or_contains = [k for k in keys if query in k or k in query]
    close = difflib.get_close_matches(query, keys, n=limit, cutoff=0.5)

    seen = set()
    merged: List[str] = []
    for item in starts_or_contains + close:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged[:limit]


def get_concept(term: str) -> Optional[Dict[str, Any]]:
    query = _normalize(term)
    if not query:
        return None

    cache_key = ("learning-concept", query, "v1")
    cached = cache_get(cache_key)
    if cached:
        return cached["concept"]

    content = load_learning_content()

    # Exact key match first
    concept = content.get(query)
    if concept:
        payload = {"key": query, **concept}
        cache_set(cache_key, {"concept": payload}, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    # Exact match against term field
    for key, item in content.items():
        if _normalize(str(item.get("term", ""))) == query:
            payload = {"key": key, **item}
            cache_set(cache_key, {"concept": payload}, ttl_seconds=CACHE_TTL_SECONDS)
            return payload

    return None


def get_popular_concepts() -> List[Dict[str, str]]:
    content = load_learning_content()
    popular: List[Dict[str, str]] = []
    for key in POPULAR_CONCEPT_KEYS:
        concept = content.get(_normalize(key))
        if concept:
            popular.append({"key": _normalize(key), "term": str(concept.get("term", key.title()))})
    return popular


def get_related_concepts_for_text(title: str, description: str, limit: int = 5) -> List[Dict[str, Any]]:
    text = _normalize(f"{title} {description}")
    if not text:
        return []

    content = load_learning_content()
    scored: List[Dict[str, Any]] = []

    for key, concept in content.items():
        term = _normalize(str(concept.get("term", "")))
        related_terms = [_normalize(str(t)) for t in concept.get("related_terms", []) if str(t).strip()]
        keywords = [_normalize(str(k)) for k in concept.get("news_keywords", []) if str(k).strip()]

        score = 0
        matched: List[str] = []

        if term and term in text:
            score += 5
            matched.append(term)

        for token in related_terms + keywords:
            if token and token in text:
                score += 2
                matched.append(token)

        if score > 0:
            scored.append(
                {
                    "key": key,
                    "term": concept.get("term", key),
                    "score": score,
                    "matches": list(dict.fromkeys(matched))[:3],
                }
            )

    ranked = sorted(scored, key=lambda c: (int(c["score"]), str(c["term"]).lower()), reverse=True)
    return ranked[:limit]


def link_finance_terms_in_text(text: str, panel_target_id: str = "#article-learning-panel") -> tuple[str, List[Dict[str, str]]]:
    """
    Convert known finance terms found in text into HTMX-enabled links.
    Matching is case-insensitive and longer phrases are matched first.
    Returns (html_with_links, matched_concepts).
    """
    if not text:
        return "", []

    content = load_learning_content()
    # term map: normalized term -> canonical concept payload
    term_map: Dict[str, Dict[str, str]] = {}
    for key, concept in content.items():
        term = str(concept.get("term", "")).strip()
        if not term:
            continue
        normalized_term = _normalize(term)
        if normalized_term:
            term_map[normalized_term] = {"key": key, "term": term}

    if not term_map:
        return html.escape(text), []

    # Longer phrases first to prioritize terms like "interest rate" over "rate".
    sorted_terms = sorted(term_map.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in sorted_terms) + r")(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )

    lower_text = text.lower()
    parts: List[str] = []
    last = 0
    matched_keys: set[str] = set()

    for match in pattern.finditer(lower_text):
        start, end = match.span()
        matched_slice = text[start:end]
        normalized_hit = _normalize(matched_slice)
        concept = term_map.get(normalized_hit)
        if not concept:
            continue

        parts.append(html.escape(text[last:start]))
        q_param = quote_plus(concept["term"])
        link_html = (
            f'<a class="article-term-link" href="/learn" '
            f'hx-get="/partials/learn/concept?q={q_param}" '
            f'hx-target="{html.escape(panel_target_id)}" '
            f'hx-swap="innerHTML">{html.escape(matched_slice)}</a>'
        )
        parts.append(link_html)
        matched_keys.add(concept["key"])
        last = end

    parts.append(html.escape(text[last:]))

    matched_concepts = [
        {"key": content[key].get("key", key), "term": str(content[key].get("term", key))}
        for key in sorted(matched_keys)
    ]
    return "".join(parts), matched_concepts


def score_article_relevance(article: Dict[str, Any], keywords: List[str], term: str) -> int:
    title = (article.get("title") or "").lower()
    description = (article.get("description") or "").lower()
    normalized_term = _normalize(term)

    score = 0

    if normalized_term and normalized_term in title:
        score += 4
    if normalized_term and normalized_term in description:
        score += 3

    for raw_kw in keywords:
        kw = _normalize(raw_kw)
        if not kw:
            continue
        if kw in title:
            score += 3
        if kw in description:
            score += 2

    return score


def _build_relevance_reason(article: Dict[str, Any], keywords: List[str], term: str) -> str:
    title = (article.get("title") or "").lower()
    description = (article.get("description") or "").lower()
    matched: List[str] = []

    for raw_kw in [term] + keywords:
        kw = _normalize(raw_kw)
        if kw and (kw in title or kw in description):
            matched.append(kw)

    unique = list(dict.fromkeys(matched))
    if not unique:
        return "This article is relevant because it is close to the concept theme."

    if len(unique) == 1:
        return f"This article is relevant because it mentions {unique[0]}."

    preview = ", ".join(unique[:2])
    return f"This article is relevant because it mentions {preview}."


async def get_related_news_for_concept(concept: Dict[str, Any], language: str = "en") -> List[Dict[str, Any]]:
    concept_key = _normalize(str(concept.get("key", "")))
    news_keywords = [str(k) for k in concept.get("news_keywords", []) if str(k).strip()]

    cache_key = ("learning-news", concept_key, language, "v2")
    cached = cache_get(cache_key)
    if cached:
        return cached["articles"]

    from_date = date.today() - timedelta(days=14)
    to_date = date.today()

    candidates_by_url: Dict[str, Dict[str, Any]] = {}

    # Exactly one upstream news call per concept search.
    concept_term = str(concept.get("term", "")).strip()
    primary_keywords = [k for k in news_keywords[:2] if k]
    query_parts = [concept_term] + primary_keywords
    query = " OR ".join([part.strip() for part in query_parts if part.strip()])
    if not query:
        query = concept_key

    try:
        payload = await get_news_payload(
            q=query,
            from_date=from_date,
            to_date=to_date,
            language=language,
            page=1,
        )
    except HTTPException:
        payload = {"articles": []}
    except Exception:
        payload = {"articles": []}

    for article in payload.get("articles", []):
        url = article.get("url") or f"{article.get('title')}|{article.get('published_at')}"
        if url not in candidates_by_url:
            candidates_by_url[url] = article

    candidates = list(candidates_by_url.values())
    concept_term = str(concept.get("term", ""))

    for article in candidates:
        score = score_article_relevance(article, news_keywords, concept_term)
        article["relevance_score"] = score
        article["relevance_reason"] = _build_relevance_reason(article, news_keywords, concept_term)

    ranked = sorted(
        candidates,
        key=lambda a: (int(a.get("relevance_score", 0)), str(a.get("published_at") or "")),
        reverse=True,
    )

    best = [a for a in ranked if int(a.get("relevance_score", 0)) > 0][:3]
    cache_set(cache_key, {"articles": best}, ttl_seconds=LEARNING_NEWS_TTL_SECONDS)
    return best


def mark_quiz(concept_key: str, submitted_answers: Dict[str, str]) -> Dict[str, Any]:
    normalized_key = _normalize(concept_key)
    content = load_learning_content()
    concept = content.get(normalized_key)
    if not concept:
        raise LearningContentError("Concept not found for quiz marking.")

    questions = concept.get("quiz", [])
    if not isinstance(questions, list) or not questions:
        raise LearningContentError("Quiz is not configured for this concept.")

    results = []
    score = 0

    for idx, q in enumerate(questions):
        selected_raw = submitted_answers.get(f"answer_{idx}")
        selected_index: Optional[int] = None
        if selected_raw is not None:
            try:
                selected_index = int(selected_raw)
            except ValueError:
                selected_index = None

        correct_index = int(q.get("answer_index", -1))
        is_correct = selected_index == correct_index
        if is_correct:
            score += 1

        options = q.get("options", [])
        selected_text = options[selected_index] if selected_index is not None and 0 <= selected_index < len(options) else None
        correct_text = options[correct_index] if 0 <= correct_index < len(options) else None

        results.append(
            {
                "question": q.get("question", ""),
                "selected_index": selected_index,
                "selected_text": selected_text,
                "correct_index": correct_index,
                "correct_text": correct_text,
                "is_correct": is_correct,
                "was_skipped": selected_index is None,
                "explanation": q.get("explanation", ""),
            }
        )

    return {
        "concept_key": normalized_key,
        "score": score,
        "total": len(questions),
        "results": results,
    }
