import time
from typing import Optional, Dict, Any, Tuple

# Key: (q, from_date, language)
CacheKey = Tuple[Optional[str], Optional[str], str]

_CACHE: Dict[CacheKey, Tuple[float, Dict[str, Any]]] = {}


def cache_get(key: CacheKey) -> Optional[Dict[str, Any]]:
    item = _CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.monotonic() > expires_at:
        _CACHE.pop(key, None)
        return None
    return payload


def cache_set(key: CacheKey, payload: Dict[str, Any], ttl_seconds: int) -> None:
    _CACHE[key] = (time.monotonic() + ttl_seconds, payload)
