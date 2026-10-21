"""Attributed Flower & Freedom cultivar summaries; no bulk mirroring."""
from __future__ import annotations

from collections import OrderedDict
import json
import os
import re
import time
import aiohttp
from .quotas import QuotaExceeded
from .strains import compact

BASE = "https://flowerandfreedom.com/api/v1/strains/"
CREDIT = "Flower & Freedom: https://flowerandfreedom.com/api/"
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_TTL = 3600


def _safe(value: object, size: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[<>@\x00-\x1f]", " ", value).replace(chr(96), "")[:size].strip()


def _slug(name: str) -> str:
    if not 2 <= len(name.strip()) <= 60:
        return ""
    if any(ch in name for ch in ("@", "<", ">", "\n", "\r", chr(96))) or "://" in name:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug if len(slug) <= 75 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) else ""


def format_record(payload: object, requested: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return "No Flower & Freedom record confirmed."
    row = payload["data"]
    name = row.get("name")
    aliases = row.get("aliases")
    aliases = aliases[:12] if isinstance(aliases, list) else []
    if not isinstance(name, str) or compact(requested) not in {
        compact(v) for v in [name, *aliases] if isinstance(v, str)
    }:
        return "No exact Flower & Freedom match confirmed."
    link = row.get("url")
    if not isinstance(link, str) or not re.fullmatch(
        r"https://flowerandfreedom\.com/strains/[a-z0-9-]+/", link
    ):
        return "No verified Flower & Freedom profile URL."
    lines = ["**Flower & Freedom:** " + _safe(name, 65)]
    summary = _safe(row.get("summary"), 220)
    if summary:
        lines.append("**Source description:** " + summary)
    genetics = row.get("genetics")
    if isinstance(genetics, dict):
        lineage = _safe(genetics.get("description"), 95)
        if lineage:
            lines.append("**Reported genetics:** " + lineage)
    for key, title in (
        ("reported_effects", "Reported effects"),
        ("aroma_descriptions", "Reported aromas"),
    ):
        items = row.get(key)
        if isinstance(items, list):
            selected = [_safe(x, 28) for x in items[:5]]
            selected = [x for x in selected if x]
            if selected:
                lines.append("**" + title + ":** " + ", ".join(selected))
    changed = _safe(row.get("updated_at"), 10)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", changed):
        lines.append("**Source updated:** " + changed)
    chemistry = row.get("chemistry")
    if isinstance(chemistry, dict) and chemistry.get("samples"):
        lines.append("**Lab testing:** Source contains batch-specific reports, not universal potency.")
    lines.append("**Read original profile:** " + link)
    lines.append(CREDIT)
    lines.append("Reported claims are not clinical or personal medical evidence.")
    return "\n".join(lines)[:900]


async def source_summary(session: aiohttp.ClientSession | None, quota, name: str) -> str:
    if os.getenv("FLOWER_FREEDOM_ENABLED", "true").lower() in ("false", "0", "no", "off"):
        return "Flower & Freedom lookup disabled."
    slug = _slug(name)
    if not slug or session is None:
        return "Flower & Freedom lookup unavailable."
    now = time.monotonic()
    found = _CACHE.get(slug)
    if found and now - found[0] < _TTL:
        _CACHE.move_to_end(slug)
        return found[1]
    try:
        quota.take_provider()
    except QuotaExceeded:
        return "Research safety allowance reached; try again later."
    try:
        async with session.get(
            BASE + slug + ".json",
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=8)
        ) as response:
            if response.status == 404:
                return "No Flower & Freedom profile confirmed."
            if response.status == 429:
                return "Provider rate limit reached."
            if response.status != 200:
                return "Flower & Freedom temporarily unavailable."
            body = await response.content.read(180001)
            if len(body) > 180000:
                return "Provider response too large."
            payload = json.loads(body)
    except (aiohttp.ClientError, TimeoutError, ValueError, UnicodeError, OSError):
        return "Flower & Freedom temporarily unavailable."
    result = format_record(payload, name)
    if result.startswith("**"):
        _CACHE[slug] = (now, result)
        _CACHE.move_to_end(slug)
        while len(_CACHE) > 64:
            _CACHE.popitem(last=False)
    return result
