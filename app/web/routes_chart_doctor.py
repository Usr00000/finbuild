from datetime import date
from typing import Optional

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.chart_doctor_service import confidence_pct, detect_chart_from_upload
from app.services.news_service import get_news_payload

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/chart-doctor", response_class=HTMLResponse)
async def chart_doctor_page(request: Request):
    return templates.TemplateResponse(
        "chart_doctor/chart_doctor.html",
        {"request": request, "title": "FinBuild • Chart Doctor"},
    )


@router.post("/chart-doctor/detect", response_class=HTMLResponse)
async def chart_doctor_detect(request: Request, image: UploadFile):
    if not image:
        return templates.TemplateResponse(
            "partials/chart_doctor/detect_result.html",
            {
                "request": request,
                "detection": None,
                "error": "Please upload a chart image first.",
                "confidence_pct": confidence_pct,
            },
        )

    try:
        file_bytes = await image.read()
        detection = await detect_chart_from_upload(file_bytes=file_bytes, filename=image.filename or "")
        return templates.TemplateResponse(
            "partials/chart_doctor/detect_result.html",
            {
                "request": request,
                "detection": detection,
                "error": None,
                "confidence_pct": confidence_pct,
            },
        )
    except Exception:
        return templates.TemplateResponse(
            "partials/chart_doctor/detect_result.html",
            {
                "request": request,
                "detection": None,
                "error": "Could not process that file. Please try another PNG/JPG image.",
                "confidence_pct": confidence_pct,
            },
        )


@router.post("/chart-doctor/news", response_class=HTMLResponse)
async def chart_doctor_news(
    request: Request,
    symbol: str = Form(default=""),
    timeframe: str = Form(default=""),
    pattern: str = Form(default=""),
    notes: str = Form(default=""),
    from_date: Optional[str] = Form(default=None),
    to_date: Optional[str] = Form(default=None),
    language: str = Form(default="en"),
):
    query = symbol.strip()
    if not query:
        return templates.TemplateResponse(
            "partials/chart_doctor/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "Ticker/symbol is required before fetching related news.",
                "review": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "pattern": pattern,
                    "notes": notes,
                    "from_date": from_date,
                    "to_date": to_date,
                    "language": language,
                },
            },
        )

    parsed_from: Optional[date] = None
    parsed_to: Optional[date] = None

    try:
        if from_date:
            parsed_from = date.fromisoformat(from_date)
        if to_date:
            parsed_to = date.fromisoformat(to_date)
    except ValueError:
        return templates.TemplateResponse(
            "partials/chart_doctor/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "Invalid date. Please use YYYY-MM-DD.",
                "review": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "pattern": pattern,
                    "notes": notes,
                    "from_date": from_date,
                    "to_date": to_date,
                    "language": language,
                },
            },
        )

    if parsed_from and parsed_to and parsed_from > parsed_to:
        return templates.TemplateResponse(
            "partials/chart_doctor/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "From date must be earlier than or equal to To date.",
                "review": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "pattern": pattern,
                    "notes": notes,
                    "from_date": from_date,
                    "to_date": to_date,
                    "language": language,
                },
            },
        )

    try:
        payload = await get_news_payload(
            q=query,
            from_date=parsed_from,
            to_date=parsed_to,
            language=language,
            page=1,
        )
        return templates.TemplateResponse(
            "partials/chart_doctor/news_results.html",
            {
                "request": request,
                "payload": payload,
                "error": None,
                "review": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "pattern": pattern,
                    "notes": notes,
                    "from_date": from_date,
                    "to_date": to_date,
                    "language": language,
                },
            },
        )
    except Exception:
        return templates.TemplateResponse(
            "partials/chart_doctor/news_results.html",
            {
                "request": request,
                "payload": None,
                "error": "Could not load related news right now. Please try again.",
                "review": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "pattern": pattern,
                    "notes": notes,
                    "from_date": from_date,
                    "to_date": to_date,
                    "language": language,
                },
            },
        )
