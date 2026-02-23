from typing import Optional, List, Dict, Any
from datetime import date, timedelta
import re
import httpx

from app.core.config import NEWSAPI_KEY, NEWSAPI_BASE_URL


async def fetch_newsapi_articles(
    q: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    language: str,
    page: int = 1,
    page_size: int = 10,
) -> tuple[List[Dict[str, Any]], bool]:
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
            "page": page,
        }
    else:
        url = f"{NEWSAPI_BASE_URL}/everything"
        params = {
            "q": q,
            "language": language,
            "sortBy": "publishedAt",
            # Everything is always newest-first, so use a large page and paginate.
            "pageSize": 100,
        }
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()

    request_page = page

    async with httpx.AsyncClient(timeout=timeout) as client:
        if not q:
            resp = await client.get(url, params=params, headers=headers)
            articles, total_results = _handle_and_normalize(resp, query=q)
            has_next = (request_page * page_size) < total_results
            return articles, has_next

        collected: List[Dict[str, Any]] = []
        if from_date and to_date:
            # Fetch each day in the range so results naturally cover older dates first.
            cursor = from_date
            max_pages_per_day = 2
            stop_fetching = False
            while cursor <= to_date:
                day_params = dict(params)
                day_params["from"] = f"{cursor.isoformat()}T00:00:00"
                day_params["to"] = f"{cursor.isoformat()}T23:59:59"

                for provider_page in range(1, max_pages_per_day + 1):
                    paged_params = dict(day_params)
                    paged_params["page"] = provider_page
                    resp = await client.get(url, params=paged_params, headers=headers)
                    if resp.status_code in {426, 429}:
                        if collected:
                            stop_fetching = True
                            break
                        return [], False
                    if resp.status_code == 401:
                        raise httpx.HTTPStatusError(
                            "Unauthorized (401): API key rejected",
                            request=resp.request,
                            response=resp,
                        )
                    page_articles, total_results = _handle_and_normalize(resp, query=q)
                    if not page_articles:
                        break
                    collected.extend(page_articles)

                    fetched_count = provider_page * int(paged_params["pageSize"])
                    if fetched_count >= total_results:
                        break

                if stop_fetching:
                    break
                cursor = cursor + timedelta(days=1)
        else:
            max_pages = 5
            for provider_page in range(1, max_pages + 1):
                paged_params = dict(params)
                paged_params["page"] = provider_page
                resp = await client.get(url, params=paged_params, headers=headers)
                if resp.status_code in {426, 429}:
                    if collected:
                        break
                    return [], False
                if resp.status_code == 401:
                    raise httpx.HTTPStatusError(
                        "Unauthorized (401): API key rejected",
                        request=resp.request,
                        response=resp,
                    )
                page_articles, total_results = _handle_and_normalize(resp, query=q)
                if not page_articles:
                    break
                collected.extend(page_articles)

                fetched_count = provider_page * int(paged_params["pageSize"])
                if fetched_count >= total_results:
                    break

    deduped = {}
    for article in collected:
        key = article.get("url") or f"{article.get('title')}|{article.get('published_at')}"
        deduped[key] = article

    ordered = list(deduped.values())
    ordered.sort(key=lambda a: a.get("published_at") or "")
    start = (request_page - 1) * page_size
    end = start + page_size
    has_next = end < len(ordered)
    return ordered[start:end], has_next


def _query_tokens(query: Optional[str]) -> List[str]:
    if not query:
        return []
    return re.findall(r"[a-z0-9]+", query.lower())


def _matches_query(article: Dict[str, Any], tokens: List[str]) -> bool:
    if not tokens:
        return True

    haystack = " ".join(
        [
            article.get("title") or "",
            article.get("description") or "",
            article.get("source") or "",
        ]
    ).lower()

    return all(token in haystack for token in tokens)


def _handle_and_normalize(resp: httpx.Response, query: Optional[str]) -> tuple[List[Dict[str, Any]], int]:
    # Common error handling
    if resp.status_code == 401:
        raise httpx.HTTPStatusError("Unauthorized (401): API key rejected", request=resp.request, response=resp)
    if resp.status_code == 429:
        raise httpx.HTTPStatusError("Too Many Requests (429): rate limit hit", request=resp.request, response=resp)
    resp.raise_for_status()

    data = resp.json()
    raw_articles = data.get("articles", [])
    total_results = data.get("totalResults", 0)

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

    tokens = _query_tokens(query)
    filtered = [a for a in normalized if _matches_query(a, tokens)]
    filtered.sort(key=lambda a: a.get("published_at") or "")
    return filtered, int(total_results)
