from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.learning_service import (
    LearningContentError,
    get_concept,
    get_popular_concepts,
    get_related_news_for_concept,
    mark_quiz,
    suggest_similar_terms,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/learn", response_class=HTMLResponse)
async def learn_page(request: Request):
    return templates.TemplateResponse(
        "learn.html",
        {
            "request": request,
            "title": "FinBuild Learn",
        },
    )


@router.get("/partials/learn/popular", response_class=HTMLResponse)
async def learn_popular_partial(request: Request):
    try:
        popular = get_popular_concepts()
        return templates.TemplateResponse(
            "partials/learn_popular.html",
            {
                "request": request,
                "popular": popular,
                "error": None,
            },
        )
    except LearningContentError as e:
        return templates.TemplateResponse(
            "partials/learn_popular.html",
            {
                "request": request,
                "popular": [],
                "error": str(e),
            },
        )


@router.get("/partials/learn/concept", response_class=HTMLResponse)
async def learn_concept_partial(request: Request, q: Optional[str] = None):
    query = (q or "").strip()
    if not query:
        return templates.TemplateResponse(
            "partials/learn_concept.html",
            {
                "request": request,
                "concept": None,
                "news_examples": [],
                "suggestions": [],
                "error": "Type a concept to begin (for example: inflation or stock).",
            },
        )

    try:
        concept = get_concept(query)
        if not concept:
            suggestions = suggest_similar_terms(query)
            return templates.TemplateResponse(
                "partials/learn_concept.html",
                {
                    "request": request,
                    "concept": None,
                    "news_examples": [],
                    "suggestions": suggestions,
                    "error": f"Concept not found for '{query}'.",
                },
            )

        news_examples = await get_related_news_for_concept(concept)
        return templates.TemplateResponse(
            "partials/learn_concept.html",
            {
                "request": request,
                "concept": concept,
                "news_examples": news_examples,
                "suggestions": [],
                "error": None,
            },
        )
    except LearningContentError as e:
        return templates.TemplateResponse(
            "partials/learn_concept.html",
            {
                "request": request,
                "concept": None,
                "news_examples": [],
                "suggestions": [],
                "error": str(e),
            },
        )


@router.post("/partials/learn/quiz/mark", response_class=HTMLResponse)
async def mark_quiz_partial(request: Request):
    form = await request.form()
    concept_key = (form.get("concept_key") or "").strip()
    if not concept_key:
        return templates.TemplateResponse(
            "partials/learn_quiz_results.html",
            {
                "request": request,
                "result": None,
                "error": "Missing concept key. Please reload the concept and try again.",
            },
        )

    submitted_answers = {k: v for k, v in form.items() if k.startswith("answer_")}

    try:
        result = mark_quiz(concept_key=concept_key, submitted_answers=submitted_answers)
        return templates.TemplateResponse(
            "partials/learn_quiz_results.html",
            {
                "request": request,
                "result": result,
                "error": None,
            },
        )
    except LearningContentError as e:
        return templates.TemplateResponse(
            "partials/learn_quiz_results.html",
            {
                "request": request,
                "result": None,
                "error": str(e),
            },
        )
