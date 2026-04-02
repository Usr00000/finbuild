from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.learning_service import (
    LearningContentError,
    get_related_concepts_for_text,
    link_finance_terms_in_text,
)
from app.services.news_service import get_news_payload

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "FinBuild • News Explorer"},
    )


@router.get("/article", response_class=HTMLResponse)
async def article_page(
    request: Request,
    title: Optional[str] = None,
    source: Optional[str] = None,
    published_at: Optional[str] = None,
    description: Optional[str] = None,
    url: Optional[str] = None,
):
    related_concepts = []
    linked_snippet_html = description or "No description available."
    snippet_matched_concepts = []
    try:
        related_concepts = get_related_concepts_for_text(
            title=title or "",
            description=description or "",
            limit=5,
        )
        linked_snippet_html, snippet_matched_concepts = await link_finance_terms_in_text(
            text=description or "",
            panel_target_id="#article-learning-panel",
            context_text=f"{title or ''} {description or ''}",
        )
        if not linked_snippet_html:
            linked_snippet_html = "No description available."
    except LearningContentError:
        related_concepts = []
        linked_snippet_html = description or "No description available."
        snippet_matched_concepts = []

    # Merge concept sources (inline matches + scored related concepts) without duplicates.
    merged_by_key = {c["key"]: c for c in related_concepts if c.get("key")}
    for c in snippet_matched_concepts:
        if c.get("key") and c["key"] not in merged_by_key:
            merged_by_key[c["key"]] = {"key": c["key"], "term": c["term"], "score": 0, "matches": []}
    merged_related_concepts = list(merged_by_key.values())

    return templates.TemplateResponse(
        "article.html",
        {
            "request": request,
            "title": "FinBuild • Article",
            "article_title": title or "Untitled",
            "article_source": source or "Unknown source",
            "article_published_at": published_at or "Unknown date",
            "article_linked_snippet_html": linked_snippet_html,
            "article_url": url or "",
            "related_concepts": merged_related_concepts,
        },
    )


@router.get("/partials/news-results", response_class=HTMLResponse)
async def news_results_partial(
    request: Request,
    q: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    language: str = "en",
    page: int = 1,
):
    # Parse date inputs from the form.
    parsed_from_date: Optional[date] = None
    parsed_to_date: Optional[date] = None

    if from_date:
        try:
            parsed_from_date = date.fromisoformat(from_date)
        except ValueError:
            return templates.TemplateResponse(
                "partials/news_results.html",
                {
                    "request": request,
                    "payload": None,
                    "error": "Invalid date format. Please use YYYY-MM-DD.",
                },
            )
    if to_date:
        try:
            parsed_to_date = date.fromisoformat(to_date)
        except ValueError:
            return templates.TemplateResponse(
                "partials/news_results.html",
                {
                    "request": request,
                    "payload": None,
                    "error": "Invalid date format. Please use YYYY-MM-DD.",
                },
            )

    if parsed_from_date and parsed_to_date and parsed_from_date > parsed_to_date:
        return templates.TemplateResponse(
            "partials/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "From date must be earlier than or equal to To date.",
            },
        )
    if page < 1:
        return templates.TemplateResponse(
            "partials/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "Invalid page number.",
            },
        )

    try:
        payload = await get_news_payload(
            q=q,
            from_date=parsed_from_date,
            to_date=parsed_to_date,
            language=language,
            page=page,
        )
        return templates.TemplateResponse(
            "partials/news_results.html",
            {"request": request, "payload": payload, "error": None},
        )
    except HTTPException as e:
        return templates.TemplateResponse(
            "partials/news_results.html",
            {"request": request, "payload": None, "error": e.detail},
        )
    except Exception:
        return templates.TemplateResponse(
            "partials/news_results.html",
            {"request": request, "payload": None, "error": "Failed to load news. Please try again."},
        )
