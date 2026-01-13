from typing import Optional

from fastapi import APIRouter

from app.services.news_service import get_news_payload

router = APIRouter()


@router.get("/news")
async def news(
    q: Optional[str] = None,
    from_date: Optional[str] = None,
    language: str = "en",
):
    return await get_news_payload(q=q, from_date=from_date, language=language)
