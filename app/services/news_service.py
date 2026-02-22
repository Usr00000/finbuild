from typing import Optional, Dict, Any
from datetime import date
import httpx
from fastapi import HTTPException

from app.clients.newsapi_client import fetch_newsapi_articles
from app.core.cache import cache_get, cache_set
from app.core.config import CACHE_TTL_SECONDS


async def get_news_payload(
    q: Optional[str],
    from_date: Optional[date],
    language: str,
) -> Dict[str, Any]:
    """
    Business logic for /news:
    - caching
    - calling the client
    - returning stable JSON response
    """
    cache_key = (q, from_date, language)
    cached = cache_get(cache_key)
    if cached:
        cached["cache"] = {"hit": True, "ttl_seconds": CACHE_TTL_SECONDS}
        return cached

    mode = "search" if q else "default"

    try:
        articles = await fetch_newsapi_articles(q=q, from_date=from_date, language=language)
    except httpx.HTTPStatusError as e:
        # Convert external API errors into clean HTTP responses
        status = e.response.status_code if e.response else 502
        if status == 401:
            raise HTTPException(status_code=401, detail="News API key rejected (401).")
        if status == 429:
            raise HTTPException(status_code=429, detail="Rate limit hit (429). Try again later.")
        raise HTTPException(status_code=502, detail=f"News provider error: {status}")
    except Exception:
        raise HTTPException(status_code=502, detail="Unexpected error contacting news provider.")

    payload = {
        "mode": mode,
        "query": q,
        "from_date": from_date,
        "language": language,
        "count": len(articles),
        "articles": articles,
        
        "cache": {"hit": False, "ttl_seconds": CACHE_TTL_SECONDS},
    }

    cache_set(cache_key, payload, ttl_seconds=CACHE_TTL_SECONDS)
    return payload

# "disclaimer": "Educational/informational only. Not financial advice.",