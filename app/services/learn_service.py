from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.cache import cache_get, cache_set
from app.core.config import CACHE_TTL_SECONDS

GLOSSARY_PATH = Path("app/data/glossary.json")


class LearnServiceError(RuntimeError):
    pass


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _load_glossary_file() -> List[Dict[str, Any]]:
    if not GLOSSARY_PATH.exists():
        raise LearnServiceError(f"Glossary data file not found: {GLOSSARY_PATH}")
    try:
        with GLOSSARY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise LearnServiceError("Glossary file is not valid JSON.") from exc

    if not isinstance(data, list):
        raise LearnServiceError("Glossary JSON must be a list of term objects.")
    return data


def load_glossary() -> List[Dict[str, Any]]:
    cache_key = ("glossary", "all", "v1")
    cached = cache_get(cache_key)
    if cached:
        return cached["items"]

    items = _load_glossary_file()
    cache_set(cache_key, {"items": items}, ttl_seconds=CACHE_TTL_SECONDS)
    return items


def get_popular_terms(limit: int = 8) -> List[Dict[str, Any]]:
    items = load_glossary()
    ranked = sorted(items, key=lambda x: int(x.get("popularity", 0)), reverse=True)
    return ranked[:limit]


def lookup_term(query: str) -> Optional[Dict[str, Any]]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return None

    cache_key = ("glossary", "term", normalized_query)
    cached = cache_get(cache_key)
    if cached:
        return cached["term"]

    for item in load_glossary():
        term = _normalize(str(item.get("term", "")))
        aliases = [_normalize(str(a)) for a in item.get("aliases", []) if a]
        if normalized_query == term or normalized_query in aliases:
            cache_set(cache_key, {"term": item}, ttl_seconds=CACHE_TTL_SECONDS)
            return item

    # Fuzzy fallback: contains check across terms and aliases
    for item in load_glossary():
        term = _normalize(str(item.get("term", "")))
        aliases = [_normalize(str(a)) for a in item.get("aliases", []) if a]
        if normalized_query in term or any(normalized_query in a for a in aliases):
            cache_set(cache_key, {"term": item}, ttl_seconds=CACHE_TTL_SECONDS)
            return item

    cache_set(cache_key, {"term": None}, ttl_seconds=CACHE_TTL_SECONDS)
    return None


def get_related_terms(current_term: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
    related_names = [str(x).strip() for x in current_term.get("related", []) if str(x).strip()]
    if not related_names:
        return []

    lookup = {str(item.get("term", "")).lower(): item for item in load_glossary()}
    results: List[Dict[str, Any]] = []
    for name in related_names:
        hit = lookup.get(name.lower())
        if hit:
            results.append(hit)
        else:
            results.append({"term": name, "definition": "No local definition yet.", "aliases": [], "related": []})

    return results[:limit]
