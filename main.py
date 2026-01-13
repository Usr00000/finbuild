from __future__ import annotations

import os
import time
from typing import Optional, Dict, Any, Tuple, List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# Load environment variables from .env into os.environ
load_dotenv()

app = FastAPI(title="FinBuild API", version="0.1.0")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSAPI_BASE_URL = os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2")

if not NEWSAPI_KEY:
    # Fail early with a clear message so you don't debug phantom errors later
    raise RuntimeError(
        "NEWSAPI_KEY is missing. Add it to backend/.env as NEWSAPI_KEY=YOUR_KEY_HERE"
    )

# -----------------------------
# Tiny in-memory TTL cache
# Key: (q, from_date, language)
# Value: (expiry_time_monotonic, cached_response_dict)
# -----------------------------
_CACHE: Dict[Tuple[Optional[str], Optional[str], str], Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 120  # 2 minutes (safe default for development)


@app.get("/health")
def health():
    return {"status": "ok", "service": "finbuild-backend"}


def _cache_get(key: Tuple[Optional[str], Optional[str], str]) -> Optional[Dict[str, Any]]:
    item = _CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.monotonic() > expires_at:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: Tuple[Optional[str], Optional[str], str], payload: Dict[str, Any]) -> None:
    _CACHE[key] = (time.monotonic() + CACHE_TTL_SECONDS, payload)


async def fetch_news_from_newsapi(
    q: Optional[str],
    from_date: Optional[str],
    language: str,
    page_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Calls NewsAPI and returns a list of normalized article dicts.

    We use:
    - /everything when q is provided (search mode)
    - /top-headlines when q is empty (default mode: business + general)
    """
    headers = {"X-Api-Key": NEWSAPI_KEY}
    timeout = httpx.Timeout(10.0, connect=5.0)

    # Default mode: general business/geopolitics-ish headlines
    if not q:
        url = f"{NEWSAPI_BASE_URL}/top-headlines"
        params = {
            "category": "business",
            "language": language,
            "pageSize": page_size,
        }
    else:
        # Search mode
        url = f"{NEWSAPI_BASE_URL}/everything"
        params = {
            "q": q,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": page_size,
        }
        if from_date:
            # Must be ISO date like 2026-01-01
            params["from"] = from_date

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params, headers=headers)

    # Handle common error states with clear messages
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="News API key rejected (401). Check NEWSAPI_KEY.")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Rate limit hit (429). Try again later.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"News API error: {resp.text}")

    data = resp.json()
    raw_articles = data.get("articles", [])

    # Normalize into your own stable schema
    normalized = []
    for a in raw_articles:
        normalized.append(
            {
                "title": a.get("title"),
                "source": (a.get("source") or {}).get("name"),
                "published_at": a.get("publishedAt"),
                "url": a.get("url"),
                "description": a.get("description"),
            }
        )

    return normalized


@app.get("/news")
async def get_news(
    q: Optional[str] = None,
    from_date: Optional[str] = None,  # e.g., 2026-01-01
    language: str = "en",
):
    """
    Real /news endpoint:
    - q optional (if missing → default business headlines)
    - from_date optional (only used in search mode)
    - language defaults to English
    - adds caching to reduce API calls
    """
    cache_key = (q, from_date, language)
    cached = _cache_get(cache_key)
    if cached:
        # Helpful for debugging
        cached["cache"] = {"hit": True, "ttl_seconds": CACHE_TTL_SECONDS}
        return cached

    mode = "search" if q else "default"

    articles = await fetch_news_from_newsapi(q=q, from_date=from_date, language=language)

    payload = {
        "mode": mode,
        "query": q,
        "from_date": from_date,
        "language": language,
        "count": len(articles),
        "articles": articles,
        "disclaimer": "Educational/informational only. Not financial advice.",
        "cache": {"hit": False, "ttl_seconds": CACHE_TTL_SECONDS},
    }

    _cache_set(cache_key, payload)
    return payload
