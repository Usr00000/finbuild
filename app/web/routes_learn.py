from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.learn_service import LearnServiceError, get_popular_terms, get_related_terms, lookup_term

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/learn", response_class=HTMLResponse)
async def learn_page(request: Request):
    return templates.TemplateResponse(
        "learn/learn.html",
        {
            "request": request,
            "title": "FinBuild • Educational Hub",
        },
    )


@router.get("/partials/learn/popular", response_class=HTMLResponse)
async def learn_popular_partial(request: Request):
    try:
        terms = get_popular_terms(limit=10)
        return templates.TemplateResponse(
            "partials/learn/popular.html",
            {
                "request": request,
                "terms": terms,
                "error": None,
            },
        )
    except LearnServiceError as e:
        return templates.TemplateResponse(
            "partials/learn/popular.html",
            {
                "request": request,
                "terms": [],
                "error": str(e),
            },
        )


@router.get("/partials/learn/term", response_class=HTMLResponse)
async def learn_term_partial(request: Request, q: Optional[str] = None):
    query = (q or "").strip()
    if not query:
        return templates.TemplateResponse(
            "partials/learn/term.html",
            {
                "request": request,
                "term": None,
                "related": [],
                "error": "Type a term to search the glossary.",
            },
        )

    try:
        term = lookup_term(query)
        if not term:
            return templates.TemplateResponse(
                "partials/learn/term.html",
                {
                    "request": request,
                    "term": None,
                    "related": [],
                    "error": f"No glossary match found for '{query}'.",
                },
            )

        related = get_related_terms(term)
        return templates.TemplateResponse(
            "partials/learn/term.html",
            {
                "request": request,
                "term": term,
                "related": related,
                "error": None,
            },
        )
    except LearnServiceError as e:
        return templates.TemplateResponse(
            "partials/learn/term.html",
            {
                "request": request,
                "term": None,
                "related": [],
                "error": str(e),
            },
        )
