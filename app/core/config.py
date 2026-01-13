import os
from dotenv import load_dotenv

load_dotenv()

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSAPI_BASE_URL = os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2")

if not NEWSAPI_KEY:
    raise RuntimeError(
        "NEWSAPI_KEY is missing. Add it to backend/.env as NEWSAPI_KEY=YOUR_KEY_HERE"
    )

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "120"))
