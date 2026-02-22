from typing import Optional
from app.schemas.news import NewsResponse
from fastapi import APIRouter
from datetime import date

from app.services.news_service import get_news_payload

router = APIRouter()


@router.get("/news",response_model=NewsResponse)
async def news(
    q: Optional[str] = None,
    from_date: Optional[date] = None,
    language: str = "en",
):
    return await get_news_payload(q=q, from_date=from_date, language=language)
