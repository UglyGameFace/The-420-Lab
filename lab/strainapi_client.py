"""One-record, no-cache read-only StrainAPI lookup with attribution."""
from __future__ import annotations
import json
import os
import re
import aiohttp
from .quotas import QuotaExceeded
from .strains import compact

BASE = "https://www.strainapi.com/wp-json/strainapi/v1"
CREDIT = "StrainAPI reference: https://www.strainapi.com/docs/ (claims are not batch testing)"
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


def clean(value: object, limit: int = 90) -> str:
    if not isinstance(value, (str, float, int)):
        return ""
    return re.sub(r"[<>@\x00-\x1f]", " ", str(value)).replace(chr(96), "")[:limit].strip()


def short_list(value: object) -> str:
    if isinstance(value, list):
        terms = [clean(v.get("name") if isinstance(v, dict) else v, 27)
                 for v in value[:5]]
        return ", ".join(v for v in terms if v)
    return clean(value, 130)


def exact_record(payload: object, name: str) -> dict | None:
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "strains"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return None
    for row in payload[:12]:
        if isinstance(row, dict) and compact(str(row.get("name") or "")) == compact(name):
            return row
    return None


def format_record(row: dict, name: str) -> str:
    if compact(str(row.get("name") or "")) != compact(name):
        return "No exact StrainAPI match confirmed."
    lines = []
    for key, label in (
        ("breeder", "Listed breeder"), ("genetics", "Reported lineage"),
        ("type", "Catalog type"), ("terpenes", "Reported terpenes"),
        ("aroma", "Reported aroma"), ("flavor", "Reported flavor"),
    ):
        value = short_list(row.get(key))
        if value:
            lines.append(f"**{label}:** {value}")
    updated = clean(row.get("updated_at"), 28)
    if updated:
        lines.append("**Source last updated:** " + updated)
    page = row.get("url")
    if isinstance(page, str) and page.startswith("https://www.strainapi.com/"):
        lines.append("[Open full strain profile](" + page[:200] + ")")
    else:
        slug = row.get("slug")
        if isinstance(slug, str) and SLUG.fullmatch(slug):
            lines.append("[Open full strain profile](https://www.strainapi.com/" + slug + "/)")
    if not lines:
        return "No displayable source facts were returned."
    return "\n".join(lines)[:760] + "\n" + CREDIT


async def get_json(session, quota, url, params=None):
    quota.take_provider()
    async with session.get(
        url, params=params, allow_redirects=False,
        timeout=aiohttp.ClientTimeout(total=7)
    ) as response:
        if response.status != 200:
            return None
        data = await response.content.read(131073)
        return json.loads(data) if len(data) <= 131072 else None


async def source_summary(session, quota, name: str) -> str:
    if os.getenv("STRAINAPI_ENABLED", "true").lower() in ("false", "0", "no", "off"):
        return "Alternative source disabled."
    if session is None or not 2 <= len(name) <= 60 or len(compact(name)) < 2:
        return "Alternative source unavailable."
    if any(char in name for char in ("@", "<", ">", "\n", "\r", chr(96))) or "://" in name:
        return "Invalid strain search term."
    try:
        matches = await get_json(session, quota, BASE + "/search", {"q": name})
        match = exact_record(matches, name)
        if not match:
            return "No exact StrainAPI source record found."
        slug = match.get("slug")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            return "Invalid source identifier."
        details = await get_json(session, quota, BASE + "/strains/" + slug)
        return format_record(details, name) if isinstance(details, dict) else "Source detail unavailable."
    except QuotaExceeded:
        return "Research safety quota reached; try again later."
    except (aiohttp.ClientError, TimeoutError, ValueError, UnicodeError, OSError, TypeError):
        return "Alternative source temporarily unavailable."
