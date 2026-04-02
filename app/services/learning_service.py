from __future__ import annotations

import difflib
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, quote_plus

import httpx
from fastapi import HTTPException

from app.core.cache import cache_get, cache_set
from app.core.config import CACHE_TTL_SECONDS
from app.services.nlp_service import extract_candidate_terms
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
WIKI_VALIDATE_TTL_SECONDS = max(CACHE_TTL_SECONDS, 1800)
WIKI_TIMEOUT = httpx.Timeout(6.0, connect=3.0)
WIKI_HEADERS = {
    "User-Agent": "FinBuild/1.0 (educational-learning-module; contact: local-app)",
    "Accept": "application/json",
}
FINANCE_SIGNAL_TERMS = {
    "market",
    "stock",
    "stocks",
    "share",
    "shares",
    "bond",
    "bonds",
    "yield",
    "yields",
    "revenue",
    "earnings",
    "profit",
    "investment",
    "gdp",
    "roi",
    "inflation",
    "interest",
    "rate",
    "rates",
    "economy",
    "economic",
    "capital",
    "returns",
    "return",
    "valuation",
    "margin",
    "dividend",
    "portfolio",
    "debt",
    "asset",
    "assets",
    "fiscal",
    "monetary",
    "ebitda",
    "eps",
    "ipo",
    "cpi",
    "etf",
    "quantitative",
    "easing",
    "credit",
    "swap",
    "default",
}
KNOWN_FINANCE_ACRONYMS = {"GDP", "ROI", "EPS", "IPO", "CPI", "ETF", "P/E", "EBITDA", "EBIT"}
NOISE_PHRASES = {"behind the scenes", "murder rate"}
NOISE_TOKENS = {"murder"}
FINANCE_ACRONYM_WIKI_TITLES = {
    "GDP": "Gross_domestic_product",
    "ROI": "Return_on_investment",
    "EPS": "Earnings_per_share",
    "IPO": "Initial_public_offering",
    "CPI": "Consumer_price_index",
    "ETF": "Exchange-traded_fund",
    "P/E": "Price%E2%80%93earnings_ratio",
    "EBITDA": "EBITDA",
    "EBIT": "EBIT",
}


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

    # Fast path: normalized key match.
    concept = content.get(query)
    if concept:
        payload = {"key": query, **concept}
        cache_set(cache_key, {"concept": payload}, ttl_seconds=CACHE_TTL_SECONDS)
        return payload

    # Fallback: match by concept term label.
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


def _resolve_local_concept_by_term(term: str) -> Optional[Dict[str, Any]]:
    return get_concept(term)


def _collect_local_terms_found_in_text(text: str) -> List[Dict[str, str]]:
    """
    Find local concept terms directly in the snippet using word boundaries.
    This keeps core terms linkable even when NLP candidates are noisy.
    """
    content = load_learning_content()
    lower_text = (text or "").lower()
    if not lower_text:
        return []

    matches: List[Dict[str, str]] = []
    for key, concept in content.items():
        term = str(concept.get("term", "")).strip()
        normalized_term = _normalize(term)
        if not normalized_term:
            continue
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(normalized_term) + r"(?![A-Za-z0-9])",
            flags=re.IGNORECASE,
        )
        if pattern.search(lower_text):
            matches.append(
                {
                    "key": key,
                    "term": term or normalized_term,
                }
            )

    # Match longer phrases first (e.g. "interest rate" before "rate").
    return sorted(matches, key=lambda m: len(_normalize(m["term"])), reverse=True)


def _should_validate_non_local_candidate(candidate: str, original_text: str) -> bool:
    """
    Decide whether a non-local candidate is worth a Wikipedia lookup.
    """
    normalized = _normalize(candidate)
    if not normalized:
        return False
    words = normalized.split()
    if len(words) >= 2:
        return True

    # Keep uppercase acronyms from the source text.
    acronym_pattern = re.compile(rf"\b{re.escape(candidate)}\b")
    if candidate.isupper() and acronym_pattern.search(original_text):
        return True

    # Keep a small list of one-word finance signals.
    finance_signals = {
        "profit",
        "revenue",
        "bond",
        "yield",
        "yields",
        "inflation",
        "recession",
        "dividend",
        "ebitda",
        "earnings",
        "equity",
        "debt",
        "liquidity",
        "volatility",
    }
    return normalized in finance_signals


def _normalize_acronym(term: str) -> str:
    return (term or "").strip().upper().replace(".", "")


def _is_known_finance_acronym(term: str) -> bool:
    normalized = _normalize_acronym(term)
    known = {a.replace(".", "") for a in KNOWN_FINANCE_ACRONYMS}
    return normalized in known


def _contains_finance_signal(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    tokens = set(re.findall(r"[a-z0-9/]+", normalized))
    strong_signals = FINANCE_SIGNAL_TERMS - {"rate", "rates", "return", "returns", "capital"}
    return any(signal in tokens or signal in normalized for signal in strong_signals)


def _is_obvious_noise_candidate(term: str) -> bool:
    normalized = _normalize(term)
    if normalized in NOISE_PHRASES:
        return True
    tokens = set(re.findall(r"[a-z0-9/]+", normalized))
    return any(token in NOISE_TOKENS for token in tokens)


def _is_finance_relevant_candidate(term: str, context_text: str) -> bool:
    if _is_obvious_noise_candidate(term):
        return False
    if _is_known_finance_acronym(term):
        return True
    normalized = _normalize(term)
    if not normalized:
        return False
    if _contains_finance_signal(normalized):
        return True
    return False


def _is_finance_relevant_wiki_payload(payload: Dict[str, Any], context_text: str) -> bool:
    if not payload.get("valid"):
        return False
    title = str(payload.get("title", ""))
    summary = str(payload.get("summary", ""))
    combined = f"{title} {summary}"
    if _is_obvious_noise_candidate(title):
        return False
    if _is_known_finance_acronym(str(payload.get("term", ""))):
        return True
    if _contains_finance_signal(combined):
        return True
    return False


def _preferred_wiki_titles_for_term(term: str) -> List[str]:
    normalized = _normalize(term)
    candidates: List[str] = []
    acronym = _normalize_acronym(term)
    mapped = FINANCE_ACRONYM_WIKI_TITLES.get(acronym)
    if mapped:
        candidates.append(mapped)

    for variant in _candidate_variants(normalized):
        if not variant:
            continue
        candidates.append(variant.replace(" ", "_"))

    seen = set()
    ordered: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _rank_nlp_candidates(candidates: List[str], original_text: str) -> List[str]:
    """
    Rank candidates so high-signal finance terms are checked first.
    """
    preferred = {
        "quantitative easing",
        "bond yield",
        "bond yields",
        "yield curve",
        "ebitda",
        "earnings per share",
        "credit default swap",
        "gdp",
        "roi",
        "revenue",
        "eps",
        "ipo",
        "cpi",
        "etf",
        "p/e",
    }
    original_upper = original_text or ""

    def _score(candidate: str) -> tuple[int, int, int]:
        normalized = _normalize(candidate)
        words = normalized.split()
        is_preferred = 1 if normalized in preferred else 0
        is_acronym = 1 if candidate.isupper() and len(candidate) >= 3 and candidate in original_upper else 0
        # Shorter phrases are often cleaner than long fragments.
        compactness = -len(words)
        return (is_preferred, is_acronym, compactness)

    return sorted(candidates, key=_score, reverse=True)


def _extract_text_from_html_paragraph(page_html: str) -> str:
    first_p = re.search(r"<p>(.*?)</p>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if not first_p:
        return ""
    raw = re.sub(r"<[^>]+>", " ", first_p.group(1))
    cleaned = re.sub(r"\s+", " ", raw).strip()
    return html.unescape(cleaned)


async def _validate_with_wiki_page_fallback(term: str) -> Dict[str, Any]:
    """
    Fallback when Wikipedia API endpoints fail.
    Uses the public /wiki page and extracts a short summary paragraph.
    """
    if not _normalize(term):
        return {"valid": False, "term": term, "title": term, "summary": "", "url": ""}

    for page_title in _preferred_wiki_titles_for_term(term):
        page_url = f"https://en.wikipedia.org/wiki/{quote(page_title)}"
        try:
            async with httpx.AsyncClient(
                timeout=WIKI_TIMEOUT,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; FinBuildBot/1.0; +https://example.com/bot)",
                    "Accept": "text/html",
                },
                follow_redirects=True,
            ) as client:
                resp = await client.get(page_url)
            if resp.status_code != 200:
                continue

            final_url = str(resp.url)
            # Skip non-article namespaces.
            if any(marker in final_url for marker in ("/wiki/Special:", "/wiki/Help:", "/wiki/File:")):
                continue

            page_html = resp.text or ""
            title_match = re.search(r"<title>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
            raw_title = title_match.group(1).strip() if title_match else term
            title = raw_title.replace(" - Wikipedia", "").strip()
            summary = _extract_text_from_html_paragraph(page_html)
            if not _contains_finance_signal(f"{title} {summary}") and not _is_known_finance_acronym(term):
                continue

            return {
                "valid": True,
                "term": term,
                "title": title or variant,
                "summary": summary,
                "url": final_url,
            }
        except Exception:
            continue

    return {"valid": False, "term": term, "title": term, "summary": "", "url": ""}


async def validate_term_with_wikipedia(term: str) -> Dict[str, Any]:
    """
    Validate a term against Wikipedia with caching.
    """
    normalized_term = _normalize(term)
    if not normalized_term:
        return {"valid": False, "term": term, "title": term, "summary": "", "url": ""}

    cache_key = ("wiki_validate", normalized_term)
    cached = cache_get(cache_key)
    if cached:
        return cached["payload"]

    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(term.strip())}"
    payload: Dict[str, Any] = {"valid": False, "term": term, "title": term, "summary": "", "url": ""}
    try:
        async with httpx.AsyncClient(timeout=WIKI_TIMEOUT, headers=WIKI_HEADERS) as client:
            resp = await client.get(summary_url)
        if resp.status_code == 200:
            data = resp.json()
            summary = str(data.get("extract", "")).strip()
            title = str(data.get("title", term)).strip() or term
            canonical_url = (
                (data.get("content_urls") or {})
                .get("desktop", {})
                .get("page", "")
            )
            # Use direct summary pages unless they are disambiguation pages.
            if summary and data.get("type") != "disambiguation":
                payload = {
                    "valid": True,
                    "term": term,
                    "title": title,
                    "summary": summary,
                    "url": canonical_url,
                }

            if not payload["valid"]:
                # Fallback to search API, then resolve the top title.
                search_url = "https://en.wikipedia.org/w/api.php"
                search_params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": term,
                    "utf8": "1",
                    "format": "json",
                    "srlimit": 1,
                }
                async with httpx.AsyncClient(timeout=WIKI_TIMEOUT, headers=WIKI_HEADERS) as client:
                    search_resp = await client.get(search_url, params=search_params)
                if search_resp.status_code == 200:
                    search_data = search_resp.json()
                    hits = ((search_data.get("query") or {}).get("search") or [])
                    if hits:
                        top_title = str(hits[0].get("title", "")).strip()
                        if top_title:
                            summary_url_2 = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(top_title)}"
                            async with httpx.AsyncClient(timeout=WIKI_TIMEOUT, headers=WIKI_HEADERS) as client:
                                summary_resp_2 = await client.get(summary_url_2)
                            if summary_resp_2.status_code == 200:
                                data2 = summary_resp_2.json()
                                summary2 = str(data2.get("extract", "")).strip()
                                if summary2:
                                    payload = {
                                        "valid": True,
                                        "term": term,
                                        "title": str(data2.get("title", top_title)).strip() or top_title,
                                        "summary": summary2,
                                        "url": (
                                            (data2.get("content_urls") or {})
                                            .get("desktop", {})
                                            .get("page", "")
                                        ),
                                    }
    except Exception:
        payload = {"valid": False, "term": term, "title": term, "summary": "", "url": ""}

    if not payload.get("valid"):
        fallback_payload = await _validate_with_wiki_page_fallback(term)
        if fallback_payload.get("valid"):
            payload = fallback_payload

    cache_set(cache_key, {"payload": payload}, ttl_seconds=WIKI_VALIDATE_TTL_SECONDS)
    return payload


def _candidate_variants(term: str) -> List[str]:
    """
    Add simple plural/singular variants for matching.
    Example: "bond yields" -> ["bond yields", "bond yield"].
    """
    t = (term or "").strip()
    if not t:
        return []
    variants = [t]
    words = t.split()
    if words:
        last = words[-1]
        if len(last) > 3 and last.lower().endswith("s"):
            singular_words = words[:-1] + [last[:-1]]
            variants.append(" ".join(singular_words))
    # De-duplicate while keeping order.
    seen = set()
    out: List[str] = []
    for v in variants:
        nv = _normalize(v)
        if nv and nv not in seen:
            seen.add(nv)
            out.append(v)
    return out


async def get_concept_with_fallback(term: str) -> Optional[Dict[str, Any]]:
    """
    Return local concept data first, then Wikipedia-backed fallback.
    """
    local = get_concept(term)
    if local:
        payload = dict(local)
        payload["source"] = "local"
        return payload

    wiki = await validate_term_with_wikipedia(term)
    if not wiki.get("valid"):
        return None

    summary = str(wiki.get("summary", "")).strip()
    first_sentence = summary.split(".")[0].strip() + "." if "." in summary else summary
    wiki_term = str(wiki.get("title") or term).strip()
    normalized_key = _normalize(wiki_term)

    return {
        "key": normalized_key,
        "term": wiki_term,
        "short_definition": first_sentence or f"{wiki_term} is a finance-related term.",
        "beginner_explanation": summary or f"{wiki_term} appears in finance news and market discussions.",
        "simple_example": f"You might see {wiki_term} mentioned when explaining market moves or company performance.",
        "why_it_matters": f"Understanding {wiki_term} helps connect financial news to practical decisions.",
        "related_terms": [],
        "news_keywords": [wiki_term],
        "quiz": [],
        "source": "wikipedia",
        "wikipedia_url": wiki.get("url", ""),
    }


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


async def link_finance_terms_in_text(
    text: str,
    panel_target_id: str = "#article-learning-panel",
    max_terms: int = 8,
    context_text: Optional[str] = None,
) -> tuple[str, List[Dict[str, str]]]:
    """
    Turn detected finance terms into HTMX links in snippet text.
    Returns (linked_html, matched_concepts).
    """
    if not text:
        return "", []

    accepted: Dict[str, Dict[str, str]] = {}
    accepted_keys: set[str] = set()
    finance_context = f"{context_text or ''} {text}"

    # Phase 1: link local curated terms found directly in text.
    local_hits = _collect_local_terms_found_in_text(text)
    for hit in local_hits:
        normalized_hit = _normalize(hit["term"])
        if normalized_hit and normalized_hit not in accepted:
            if hit["key"] in accepted_keys:
                continue
            accepted[normalized_hit] = {"key": hit["key"], "term": hit["term"]}
            accepted_keys.add(hit["key"])
        if len(accepted) >= max_terms:
            break

    # Phase 2: add non-local candidates from NLP + Wikipedia validation.
    raw_candidates = extract_candidate_terms(text, limit=40)
    for candidate in _rank_nlp_candidates(raw_candidates, text):
        normalized_candidate = _normalize(candidate)
        if not normalized_candidate or normalized_candidate in accepted:
            continue

        for variant in _candidate_variants(candidate):
            if _is_obvious_noise_candidate(variant):
                continue

            # Prefer local curated concepts when available.
            local_concept = _resolve_local_concept_by_term(variant)
            if local_concept:
                local_key = str(local_concept.get("key", normalized_candidate))
                if local_key in accepted_keys:
                    continue
                accepted[normalized_candidate] = {
                    "key": local_key,
                    "term": str(local_concept.get("term", variant)),
                }
                accepted_keys.add(local_key)
                break

            # Then try Wikipedia-backed fallback for non-local terms.
            if not _should_validate_non_local_candidate(variant, text):
                continue
            if not _is_finance_relevant_candidate(variant, finance_context):
                continue
            wiki = await validate_term_with_wikipedia(variant)
            if wiki.get("valid") and _is_finance_relevant_wiki_payload(wiki, finance_context):
                wiki_term = str(wiki.get("title", variant))
                wiki_key = _normalize(wiki_term)
                if wiki_key in accepted_keys:
                    continue
                accepted[normalized_candidate] = {
                    "key": wiki_key,
                    "term": wiki_term,
                }
                accepted_keys.add(wiki_key)
                break

        if len(accepted) >= max_terms:
            break

    if not accepted:
        return html.escape(text), []

    # Link longer phrases first.
    sorted_terms = sorted(accepted.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in sorted_terms) + r")(?![A-Za-z0-9])",
        flags=re.IGNORECASE,
    )

    lower_text = text.lower()
    parts: List[str] = []
    last = 0
    matched_keys: set[str] = set()
    used_terms: set[str] = set()

    for match in pattern.finditer(lower_text):
        start, end = match.span()
        matched_slice = text[start:end]
        normalized_hit = _normalize(matched_slice)
        if normalized_hit in used_terms:
            continue
        concept = accepted.get(normalized_hit)
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
        used_terms.add(normalized_hit)
        last = end

    parts.append(html.escape(text[last:]))

    matched_concepts: List[Dict[str, str]] = []
    seen_keys: set[str] = set()
    for value in accepted.values():
        key = value.get("key")
        if key in matched_keys and key not in seen_keys:
            matched_concepts.append(value)
            seen_keys.add(key)
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

    # Keep this to one upstream news call per concept search.
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
