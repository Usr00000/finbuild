from __future__ import annotations

import re
from typing import List


_GENERIC_STOP_TERMS = {
    "market",
    "company",
    "business",
    "price",
    "prices",
    "year",
    "years",
    "today",
    "week",
    "month",
    "people",
    "group",
    "report",
    "news",
    "article",
}
_NLP = None
_FINANCE_SUFFIX_WORDS = {
    "yield",
    "yields",
    "curve",
    "curves",
    "swap",
    "swaps",
    "spread",
    "spreads",
    "easing",
    "inflation",
    "earnings",
    "share",
    "shares",
    "debt",
    "default",
    "rate",
    "rates",
}
_FINANCE_SIGNAL_WORDS = {
    "profit",
    "bond",
    "interest",
    "rate",
    "rates",
    "yield",
    "yields",
    "inflation",
    "recession",
    "dividend",
    "investment",
    "ebitda",
    "earnings",
    "equity",
    "debt",
    "liquidity",
    "volatility",
    "revenue",
    "gdp",
    "roi",
    "eps",
    "ipo",
    "cpi",
    "etf",
    "p/e",
}
_KNOWN_FINANCE_ACRONYMS = {
    "GDP",
    "ROI",
    "EPS",
    "IPO",
    "CPI",
    "ETF",
    "EBITDA",
    "EBIT",
    "P/E",
}


def _normalize_candidate(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    cleaned = cleaned.strip(".,;:!?()[]{}\"'")
    return cleaned


def _is_reasonable_candidate(text: str) -> bool:
    if not text:
        return False
    if len(text) < 3:
        return False
    if text.lower() in _GENERIC_STOP_TERMS:
        return False
    if re.fullmatch(r"\d+", text):
        return False
    return True


def extract_candidate_terms(text: str, limit: int = 30) -> List[str]:
    """
    NLP candidate extraction using spaCy noun chunks + selected entities.
    Falls back to regex noun-phrase-like chunks when spaCy/model is unavailable.
    """
    normalized_text = (text or "").strip()
    if not normalized_text:
        return []

    candidates: List[str] = []

    spacy_candidates: List[str] = []
    try:
        import spacy  # type: ignore

        global _NLP
        if _NLP is None:
            try:
                _NLP = spacy.load("en_core_web_sm")
            except Exception:
                # Try a blank pipeline if the full model isn't installed.
                _NLP = spacy.blank("en")

        doc = _NLP(normalized_text)

        # Noun chunks are typically strong finance term candidates.
        if doc.has_annotation("DEP"):
            for chunk in doc.noun_chunks:
                c = _normalize_candidate(chunk.text)
                if _is_reasonable_candidate(c):
                    spacy_candidates.append(c)

        # Keep entity classes that often include finance concepts.
        for ent in doc.ents:
            if ent.label_ in {"ORG", "PRODUCT", "EVENT", "LAW", "MONEY", "GPE", "NORP"}:
                c = _normalize_candidate(ent.text)
                if _is_reasonable_candidate(c):
                    spacy_candidates.append(c)
    except Exception:
        pass

    candidates.extend(spacy_candidates)

    # Regex enrichment keeps feature usable without spaCy model and captures finance phrases/acronyms.
    for hit in re.findall(r"\b[A-Za-z][A-Za-z\-]{2,}(?:\s+[A-Za-z][A-Za-z\-]{2,}){0,4}\b", normalized_text):
        c = _normalize_candidate(hit)
        if _is_reasonable_candidate(c):
            words = c.split()
            if len(words) >= 2:
                # Prefer multi-word phrases ending in common finance suffix terms.
                if words[-1] in _FINANCE_SUFFIX_WORDS:
                    candidates.append(c)
                # Also include other multi-word candidates for broader coverage.
                candidates.append(c)
            else:
                candidates.append(c)

    # Capture uppercase finance abbreviations from original text (e.g., EBITDA, EPS, GDP, ROI).
    for acronym in re.findall(r"\b[A-Z]{2,10}\b", text or ""):
        if acronym in _KNOWN_FINANCE_ACRONYMS or _is_reasonable_candidate(acronym):
            candidates.append(acronym)

    # Capture slash acronyms such as P/E.
    for acronym in re.findall(r"\b[A-Z]{1,4}/[A-Z]{1,4}\b", text or ""):
        candidates.append(acronym)

    # Keep known single-word finance signals so local terms remain detectable.
    for token in re.findall(r"\b[A-Za-z][A-Za-z\-]{2,}\b", normalized_text):
        c = _normalize_candidate(token)
        if c in _FINANCE_SIGNAL_WORDS and _is_reasonable_candidate(c):
            candidates.append(c)

    # Capture common fixed finance phrases directly.
    fixed_phrases = [
        "quantitative easing",
        "bond yield",
        "bond yields",
        "yield curve",
        "earnings per share",
        "credit default swap",
    ]
    lower_text = normalized_text.lower()
    for phrase in fixed_phrases:
        if phrase in lower_text:
            candidates.append(phrase)

    # Preserve order, deduplicate, then prefer longer phrases.
    seen = set()
    deduped: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            deduped.append(c)

    ranked = sorted(deduped, key=len, reverse=True)
    return ranked[:limit]
