"""Attributed, no-cache CannaLib source lookup for educational strain profiles.

Only one user's requested record is looked up. The API response is not used to
populate the local catalog or serve bulk datasets. Images are not embedded,
because the underlying rights of a photo may be unverified.
"""
from __future__ import annotations

import json
import os
import re
import aiohttp

from .quotas import QuotaExceeded
from .strains import compact

URL = "https://api.cannalib.org/v1/catalogs/strains"
CREDIT = "Data by CannaLib: https://cannalib.org"


def safe(value: object, length: int = 80) -> str:
    return re.sub(r"[<>\x00-\x1f@]", " ", str(value or "")).replace(chr(96), "")[:length].strip()


def brief(value: object) -> str:
    if isinstance(value, (str, int, float)):
        return safe(value)
    if isinstance(value, (list, tuple)):
        parts = []
        for x in value[:4]:
            if isinstance(x, dict):
                x = x.get("name") or x.get("terpene") or x.get("compound")
            if isinstance(x, (str, float, int)):
                parts.append(safe(x, 22))
        return ", ".join(x for x in parts if x)[:90]
    return ""


def record_for(data: object, name: str) -> dict | None:
    if isinstance(data, dict):
        for key in ("data", "results", "strains", "items"):
            rows = data.get(key)
            if isinstance(rows, dict):
                rows = next((rows[k] for k in ("items", "results", "data", "strains")
                             if isinstance(rows.get(k), list)), None)
            if isinstance(rows, list):
                data = rows
                break
    if not isinstance(data, list):
        return None
    wanted = compact(name)
    for row in data[:3]:
        if isinstance(row, dict) and (
            compact(str(row.get("name") or "")) == wanted or
            compact(str(row.get("name_norm") or "")) == wanted
        ):
            return row
    return None


async def source_summary(session: aiohttp.ClientSession | None, quota, name: str) -> str:
    """Return bounded researched claims or clear unavailable notice, never guess."""
    if os.getenv("CANNALIB_ENABLED", "true").strip().lower() in ("0", "false", "off", "no"):
        return "Live provider lookup disabled."
    if session is None:
        return "Live provider connection unavailable."
    if not 2 <= len(name) <= 60 or len(compact(name)) < 2:
        return "Invalid strain name."
    try:
        quota.take_cannalib()
        quota.take_provider()
    except QuotaExceeded:
        return "Provider's bot-wide safety allowance reached; try again later."
    key = os.getenv("CANNALIB_API_KEY", "").strip()
    headers = {"User-Agent": "The Weed Doctor educational bot/1.0"}
    if key:
        headers["X-Cannalib-Key"] = key
    try:
        async with session.get(
            URL, params={"q": name, "limit": 3}, headers=headers,
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=8)
        ) as response:
            if response.status == 429:
                return "Provider rate limit reached."
            if response.status != 200:
                return "Provider currently unavailable for this query."
            # Free-plan responses must not be cached beyond this display.
            body = await response.content.read(131073)
            if len(body) > 131072:
                return "Provider response too large for safe display."
            data = json.loads(body)
    except (aiohttp.ClientError, TimeoutError, ValueError, UnicodeError, OSError):
        return "Provider temporarily unavailable."

    item = record_for(data, name)
    if item is None:
        return "No exact-name source record confirmed for this query."
    fields = (
        ("type", "Catalog label"),
        ("breeder", "Listed breeder"),
        ("thc_range", "THC range claimed by sources (not your batch)"),
        ("cbd_range", "CBD range claimed by sources (not your batch)"),
        ("top_terpenes", "Source-reported terpenes"),
        ("flowering_days", "Listed flowering days"),
    )
    statements = ["**" + label + ":** " + brief(item.get(key))
                  for key, label in fields if brief(item.get(key))]
    return "\n".join(statements)[:920] if statements else "Source record returned without displayable facts."
