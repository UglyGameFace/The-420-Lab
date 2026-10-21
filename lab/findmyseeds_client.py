"""Attributed on-demand Find My Seeds public profile lookup."""
from __future__ import annotations
from collections import OrderedDict
import html
import json
import os
import re
import time
from urllib.parse import urlsplit
import aiohttp
from .quotas import QuotaExceeded
from .strains import compact

URL = "https://www.findmyseeds.com/wp-json/strain-compass/v1/strains"
SOURCE = "https://www.findmyseeds.com/find-my-seeds-public-api/"
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_TTL = 3600
_MISS_TTL = 300


def safe(value: object, limit: int = 100) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    value = html.unescape(str(value))
    return re.sub(r"[\x00-\x1f<>@]", " ", value).replace(chr(96), "")[:limit].strip()


def safe_items(value: object, limit: int = 4) -> str:
    if not isinstance(value, list):
        return ""
    values = [safe(item, 29) for item in value[:limit] if isinstance(item, str)]
    return ", ".join(x for x in values if x)[:125]


def exact_record(payload: object, query: str) -> dict | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    wanted = compact(query)
    for row in payload["items"][:10]:
        if not isinstance(row, dict):
            continue
        names = (row.get("name"), row.get("aka"))
        if any(isinstance(name, str) and compact(name) == wanted for name in names):
            return row
    return None


def format_record(payload: object, requested: str) -> str:
    row = exact_record(payload, requested)
    if row is None:
        return "No exact Find My Seeds profile confirmed."
    url = row.get("url")
    if not isinstance(url, str):
        return "No verified Find My Seeds profile URL."
    parts = urlsplit(url)
    if not (parts.scheme == "https" and parts.hostname in
            {"www.findmyseeds.com", "findmyseeds.com"} and
            re.fullmatch(r"/strains/[a-z0-9-]+/", parts.path)
            and not parts.username and not parts.password
            and not parts.query and not parts.fragment):
        return "No verified Find My Seeds profile URL."
    lines = ["**Find My Seeds:** " + safe(row.get("name"), 72)]
    excerpt = safe(row.get("excerpt"), 160)
    if excerpt:
        lines.append("**Source overview:** " + excerpt)
    for field, label in (
        ("breeder", "Listed breeder"), ("type", "Catalog type"),
        ("effects", "Reported effects"), ("flavors", "Reported flavors"),
        ("terpenes", "Reported terpenes"),
    ):
        raw = row.get(field)
        value = safe_items(raw) if isinstance(raw, list) else safe(raw, 75)
        if value:
            lines.append(f"**{label}:** {value}")
    rating, count = row.get("rating"), row.get("rating_count")
    if (type(count) is int and 0 < count <= 10000000 and
            type(rating) in (int, float) and 0 <= rating <= 5):
        lines.append(f"**Find My Seeds community score:** {rating:.1f}/5 ({count} reports)")
    lines.append("**Original photos and full profile:** " + url)
    lines.append("Data provided by Find My Seeds • " + SOURCE)
    lines.append("Community reports are subjective, not verified health or potency results.")
    return "\n".join(lines)[:890]


async def source_summary(session: aiohttp.ClientSession | None, quota, name: str) -> str:
    if os.getenv("FINDMYSEEDS_ENABLED", "true").strip().lower() in ("0", "off", "false", "no"):
        return "Find My Seeds lookup disabled."
    if session is None or not 2 <= len(name.strip()) <= 60 or len(compact(name)) < 2:
        return "Find My Seeds lookup unavailable."
    if any(char in name for char in ("@", "<", ">", "\n", "\r", chr(96))) or "://" in name:
        return "Invalid strain name."
    key = compact(name)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < (_TTL if cached[1].startswith("**") else _MISS_TTL):
        _CACHE.move_to_end(key)
        return cached[1]
    try:
        quota.take_provider()
    except QuotaExceeded:
        return "Research safety allowance reached; try again later."
    try:
        async with session.get(
            URL, params={"q": name, "per_page": 5},
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=8)
        ) as response:
            if response.status == 429:
                return "Provider rate limit reached."
            if response.status != 200:
                return "Find My Seeds temporarily unavailable."
            body = await response.content.read(150001)
            if len(body) > 150000:
                return "Provider response too large."
            data = json.loads(body)
    except (aiohttp.ClientError, TimeoutError, ValueError, UnicodeError, OSError):
        return "Find My Seeds temporarily unavailable."
    result = format_record(data, name)
    if result.startswith("**") or result.startswith("No exact"):
        _CACHE[key] = (now, result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return result
