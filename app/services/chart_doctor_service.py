from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple


@dataclass
class DetectionResult:
    symbol: str
    timeframe: str
    pattern: str
    notes: str
    confidence: Dict[str, float]
    from_date: date
    to_date: date


def _safe_import_cv2():
    try:
        import cv2  # type: ignore

        return cv2
    except Exception:
        return None


def _safe_import_numpy():
    try:
        import numpy as np  # type: ignore

        return np
    except Exception:
        return None


def _safe_import_tesseract():
    try:
        import pytesseract  # type: ignore

        return pytesseract
    except Exception:
        return None


def _clamp_conf(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 2)


def _extract_symbol(text: str) -> Optional[str]:
    if not text:
        return None
    candidates = re.findall(r"\b[A-Z]{1,5}\b", text.upper())
    blocked = {"USD", "OPEN", "HIGH", "LOW", "CLOSE", "VOL", "DATE", "TIME", "CHART", "THE"}
    for c in candidates:
        if c not in blocked:
            return c
    return None


def _extract_timeframe(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [r"\b(1M|5M|15M|30M|1H|4H|1D|1W|1MO)\b", r"\b(DAILY|WEEKLY|MONTHLY|HOURLY)\b"]
    upper = text.upper()
    for p in patterns:
        hit = re.search(p, upper)
        if hit:
            return hit.group(1)
    return None


def _guess_pattern_with_cv(cv2: Any, gray_img: Any) -> Tuple[str, float]:
    try:
        edges = cv2.Canny(gray_img, 60, 150)
        lines = cv2.HoughLinesP(edges, 1, 3.14159 / 180, threshold=60, minLineLength=30, maxLineGap=10)
        if lines is None:
            return "Trend review needed", 0.35

        up = 0
        down = 0
        flat = 0
        for line in lines[:120]:
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 3:
                flat += 1
                continue
            slope = dy / dx
            if slope > 0.3:
                up += 1
            elif slope < -0.3:
                down += 1
            else:
                flat += 1

        if up > down * 1.4:
            return "Uptrend", 0.66
        if down > up * 1.4:
            return "Downtrend", 0.66
        if up > 0 and down > 0:
            return "Range / consolidation", 0.58
        return "Trend review needed", 0.4
    except Exception:
        return "Trend review needed", 0.3


def _ocr_best_effort(img_bgr: Any) -> str:
    cv2 = _safe_import_cv2()
    pytesseract = _safe_import_tesseract()
    if cv2 is None or pytesseract is None:
        return ""

    h, w = img_bgr.shape[:2]
    top_roi = img_bgr[0 : max(1, int(h * 0.28)), 0:w]
    gray_top = cv2.cvtColor(top_roi, cv2.COLOR_BGR2GRAY)
    gray_all = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    text_parts = []
    for chunk in (gray_top, gray_all):
        try:
            txt = pytesseract.image_to_string(chunk)
        except Exception:
            txt = ""
        if txt:
            text_parts.append(txt)
    return "\n".join(text_parts)


def _defaults() -> DetectionResult:
    today = date.today()
    return DetectionResult(
        symbol="",
        timeframe="1D",
        pattern="Trend review needed",
        notes="Could not confidently detect fields. Please review and edit before searching news.",
        confidence={"symbol": 0.2, "timeframe": 0.2, "pattern": 0.3},
        from_date=today - timedelta(days=7),
        to_date=today,
    )


async def detect_chart_from_upload(file_bytes: bytes, filename: str) -> DetectionResult:
    result = _defaults()
    if not file_bytes:
        result.notes = "No file uploaded. Please upload a chart image (PNG/JPG)."
        return result

    cv2 = _safe_import_cv2()
    np = _safe_import_numpy()
    if cv2 is None or np is None:
        result.symbol = _extract_symbol(filename) or ""
        result.confidence["symbol"] = 0.35 if result.symbol else 0.2
        result.notes = (
            "OpenCV/Numpy not available in this environment. "
            "Used filename-only detection; please review fields manually."
        )
        return result

    try:
        arr = np.frombuffer(file_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            result.notes = "Uploaded file could not be decoded as an image."
            return result

        ocr_text = _ocr_best_effort(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        symbol = _extract_symbol(ocr_text) or _extract_symbol(filename) or ""
        timeframe = _extract_timeframe(ocr_text) or "1D"
        pattern, pattern_conf = _guess_pattern_with_cv(cv2, gray)

        symbol_conf = 0.82 if _extract_symbol(ocr_text) else (0.45 if symbol else 0.2)
        timeframe_conf = 0.75 if _extract_timeframe(ocr_text) else 0.4

        notes = "Detection completed with best-effort OCR and chart-shape heuristics."
        if not _safe_import_tesseract():
            notes = "Tesseract not available; OCR confidence is reduced."

        return DetectionResult(
            symbol=symbol,
            timeframe=timeframe,
            pattern=pattern,
            notes=notes,
            confidence={
                "symbol": _clamp_conf(symbol_conf),
                "timeframe": _clamp_conf(timeframe_conf),
                "pattern": _clamp_conf(pattern_conf),
            },
            from_date=date.today() - timedelta(days=7),
            to_date=date.today(),
        )
    except Exception as exc:
        result.notes = f"Detection failed unexpectedly ({type(exc).__name__}). Please fill fields manually."
        return result


def confidence_pct(confidence: float) -> int:
    return int(round(_clamp_conf(confidence) * 100))
