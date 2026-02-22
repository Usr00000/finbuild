from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional, Literal

from pydantic import BaseModel


class Article(BaseModel):
    title: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None
    url: Optional[str] = None
    description: Optional[str] = None


class CacheInfo(BaseModel):
    hit: bool
    ttl_seconds: int


class NewsResponse(BaseModel):
    mode: Literal["default", "search"]
    query: Optional[str] = None
    from_date: Optional[date] = None
    language: str = "en"
    count: int
    articles: List[Article]
    cache: CacheInfo
