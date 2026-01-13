from typing import Optional, List, Dict, Any

import httpx

from app.core.config import NEWSAPI_KEY, NEWSAPI_BASE_URL


async def fetch_newsapi_articles(
    q: Optional[str],
    from_date: Optional[str],
    language: str,
    page_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Fetch raw articles from NewsAPI and normalize them into FinBuild's schema.
    """
    headers = {"X-Api-Key": NEWSAPI_KEY}
    timeout = httpx.Timeout(10.0, connect=5.0)

    if not q:
        url = f"{NEWSAPI_BASE_URL}/top-headlines"
        params = {
            "category": "business",
            "language": language,
            "pageSize": page_size,
        }
    else:
        url = f"{NEWSAPI_BASE_URL}/everything"
        params = {
            "q": q,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": page_size,
        }
        if from_date:
            params["from"] = from_date

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params, headers=headers)

    return _handle_and_normalize(resp)


def _handle_and_normalize(resp: httpx.Response) -> List[Dict[str, Any]]:
    # Common error handling
    if resp.status_code == 401:
        raise httpx.HTTPStatusError("Unauthorized (401): API key rejected", request=resp.request, response=resp)
    if resp.status_code == 429:
        raise httpx.HTTPStatusError("Too Many Requests (429): rate limit hit", request=resp.request, response=resp)
    resp.raise_for_status()

    data = resp.json()
    raw_articles = data.get("articles", [])

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
