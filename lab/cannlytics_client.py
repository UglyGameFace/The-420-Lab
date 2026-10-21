"""Optional read-only Cannlytics per-strain profile lookup.

Results are provider aggregates, not specific-product potency guarantees.
No key = no network call. No scraping or bulk sync.
"""
from __future__ import annotations
from collections import OrderedDict
import json
import os
import re
import time
from urllib.parse import quote
import aiohttp
from .strains import compact
from .quotas import QuotaExceeded

API = "https://cannlytics.com/api/data/strains/"
INFO = "https://docs.cannlytics.com/api/data/strains/"
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()


def clean(value: object, limit: int = 90) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[<>@\x00-\x1f]", " ", value).replace(chr(96), "")[:limit].strip()


def _items(value: object) -> str:
    if isinstance(value, str):
        return clean(value, 110)
    if isinstance(value, list):
        return ", ".join(clean(v, 30) for v in value[:4] if isinstance(v, str))[:130]
    return ""


def parse_profile(payload: object, requested: str) -> str:
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, dict):
        return ""
    name = payload.get("strain_name") or payload.get("name")
    if not isinstance(name, str) or compact(name) != compact(requested):
        return ""
    parts = [f"**Cannlytics:** {clean(name, 65)}"]
    for field, title in (("aromas", "Reported aromas"),
                         ("effects", "Community-reported effects")):
        value = _items(payload.get(field))
        if value:
            parts.append(f"**{title}:** {value}")
    # Do not show an undocumented strain-wide THC % as though it were
    # measured in the member's exact product.
    if len(parts) == 1:
        parts.append("Exact-name catalog record found.")
    parts.append("Provider aggregate, not a lab certificate for your batch.")
    parts.append(INFO)
    return "\n".join(parts)[:650]


async def strain_summary(session, quota, name: str) -> str:
    key = os.getenv("CANNLYTICS_API_KEY", "").strip()
    if not key or session is None:
        return ""
    if (not 2 <= len(name.strip()) <= 60 or len(compact(name)) < 2
            or any(ch in name for ch in ("@", "<", ">", "\n", "\r", chr(96)))
            or "://" in name):
        return ""
    ident = compact(name)
    now = time.monotonic()
    stored = _CACHE.get(ident)
    if stored and now - stored[0] < 3600:
        _CACHE.move_to_end(ident)
        return stored[1]
    try:
        quota.take_provider()
    except QuotaExceeded:
        return ""
    try:
        async with session.get(
            API + quote(name.strip(), safe=""),
            headers={"Authorization": "Bearer " + key},
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=5)
        ) as response:
            if response.status != 200:
                return ""
            raw = await response.content.read(131073)
            if len(raw) > 131072:
                return ""
            data = json.loads(raw)
    except (aiohttp.ClientError, TimeoutError, UnicodeError, ValueError, OSError):
        return ""
    summary = parse_profile(data, name)
    _CACHE[ident] = (now, summary)
    _CACHE.move_to_end(ident)
    while len(_CACHE) > 100:
        _CACHE.popitem(last=False)
    return summary
