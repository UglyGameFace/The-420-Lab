"""Real cannabis flower photos, explicitly illustrative unless cultivar verified.

Pexels is an optional authenticated source for actual photographers' images.
Wikimedia Commons CC0 is an always-on, no-key public backup. Never invent
cultivar-specific photos, scrape providers, or generate misleading strain art.
"""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
import os
import re
import time
from urllib.parse import urlsplit
import aiohttp

logger = logging.getLogger(__name__)

COMMONS_PAGE = "https://commons.wikimedia.org/wiki/File:CannabisBud.jpg"
COMMONS_IMAGE = "https://commons.wikimedia.org/wiki/Special:FilePath/CannabisBud.jpg?width=960"


@dataclass(frozen=True)
class StrainPhoto:
    image_url: str
    source_page: str
    source: str
    photographer: str
    is_cultivar_verified: bool = False


def commons_fallback() -> StrainPhoto:
    # Wikimedia Commons lists Thomas Elliott's real cannabis-bud photo as CC0.
    return StrainPhoto(COMMONS_IMAGE, COMMONS_PAGE, "Wikimedia Commons • CC0",
                       "Thomas Elliott", False)


def _safe_pexels_photo(data: dict) -> StrainPhoto | None:
    """Reject unrelated search images and remote URLs from unexpected hosts."""
    if not isinstance(data, dict):
        return None
    alt = str(data.get("alt") or "").lower()
    if not (re.search(r"\b(cannabis|marijuana|marihuana)\b", alt)
            and re.search(r"\b(bud|buds|flower|flowers|nug|nugs|inflorescence)\b", alt)):
        return None
    src = data.get("src")
    if not isinstance(src, dict):
        return None
    url, page = src.get("large") or src.get("medium"), data.get("url")
    if not isinstance(url, str) or not isinstance(page, str):
        return None
    try:
        if (urlsplit(url).scheme != "https"
                or urlsplit(url).hostname != "images.pexels.com"
                or urlsplit(page).scheme != "https"
                or urlsplit(page).hostname not in {"www.pexels.com", "pexels.com"}):
            return None
    except ValueError:
        return None
    author = re.sub(r"[^A-Za-z0-9 .,'-]", "", str(data.get("photographer") or "Unknown"))[:65]
    return StrainPhoto(url, page, "Pexels", author)


class StrainPhotoService:
    def __init__(self, session: aiohttp.ClientSession, quota=None):
        self.session = session
        self.quota = quota
        self._photo = commons_fallback()
        self._until = 0.0
        self._lock = asyncio.Lock()

    async def photo(self) -> StrainPhoto:
        """Same generic query for everyone: no per-user queries or API exhaustion."""
        token = os.getenv("PEXELS_API_KEY", "").strip()
        if not token:
            return commons_fallback()
        if time.monotonic() < self._until:
            return self._photo
        async with self._lock:
            if time.monotonic() < self._until:
                return self._photo
            photo = commons_fallback()
            try:
                if self.quota:
                    self.quota.take_provider()
                async with self.session.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": "cannabis flower bud", "orientation": "landscape",
                            "per_page": 8, "page": 1},
                    headers={"Authorization": token},
                    timeout=aiohttp.ClientTimeout(total=4),
                ) as response:
                    if response.status == 200:
                        payload = await response.json(content_type=None)
                        if isinstance(payload, dict):
                            for candidate in payload.get("photos", [])[:8]:
                                found = _safe_pexels_photo(candidate)
                                if found:
                                    photo = found
                                    break
                    else:
                        logger.info("Pexels image service returned status %s", response.status)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
                logger.info("Pexels photo unavailable, using credited Wikimedia Commons backup")
            except Exception as exc:
                # Includes the project's own global provider quota guard.
                logger.info("Pexels photo skipped: %s", type(exc).__name__)
            self._photo = photo
            # Cache failures, too: prevent repeated requests after outages or 429.
            self._until = time.monotonic() + (21600 if photo.source == "Pexels" else 3600)
            return photo
