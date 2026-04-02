from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.web.routes_pages import router as pages_router
from app.web.routes_chart_doctor import router as chart_doctor_router
from app.api.routes_learning import router as learning_router

from app.api.routes_news import router as news_router

app = FastAPI(title="FinBuild API", version="0.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages_router)
app.include_router(chart_doctor_router)
# Learning Hub routes (concept + quiz partials).
app.include_router(learning_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "finbuild-backend"}


app.include_router(news_router)
