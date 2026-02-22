from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.news_service import get_news_payload

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "FinBuild • News Explorer"},
    )


@router.get("/partials/news-results", response_class=HTMLResponse)
async def news_results_partial(
    request: Request,
    q: Optional[str] = None,
    from_date: Optional[str] = None,   # 👈 accept raw string
    language: str = "en",
):
    # Convert from_date safely:
    parsed_date: Optional[date] = None

    # from_date will be "" when user leaves the date input empty
    if from_date:
        try:
            parsed_date = date.fromisoformat(from_date)  # expects "YYYY-MM-DD"
        except ValueError:
            return templates.TemplateResponse(
                "partials/news_results.html",
                {
                    "request": request,
                    "payload": None,
                    "error": "Invalid date format. Please use YYYY-MM-DD.",
                },
            )

    try:
        payload = await get_news_payload(q=q, from_date=parsed_date, language=language)
        return templates.TemplateResponse(
            "partials/news_results.html",
            {"request": request, "payload": payload, "error": None},
        )
    except Exception:
        return templates.TemplateResponse(
            "partials/news_results.html",
            {"request": request, "payload": None, "error": "Failed to load news. Please try again."},
        )
