"""Curated links to verified Leafly strain reference pages.

This directory deliberately does NOT crawl Leafly, invent URLs, download
their copyrighted reviews, or mislabel community feedback as clinical data.
More profiles can be added only after separately verifying their real URL.
"""
from __future__ import annotations

from urllib.parse import quote_plus
import re
import unicodedata

LEAFLY_TERMS = "https://www.leafly.com/info/terms-of-use"
LEAFLY_DIRECTORY = "https://www.leafly.com/strains"

# Checked against individual publicly accessible Leafly strain pages,
# October 2026. The right-hand values are fixed vetted paths, never
# constructed from arbitrary untrusted user-provided names.
VERIFIED_PROFILES = {
    "animalface": ("Animal Face", "animal-face"),
    "bluedream": ("Blue Dream", "blue-dream"),
    "gelato41": ("Gelato #41", "gelato-41"),
    "lemoncherrygelato": ("Lemon Cherry Gelato", "lemon-cherry-gelato"),
    "northernlights": ("Northern Lights", "northern-lights"),
    "permanentmarker": ("Permanent Marker", "permanent-marker"),
    "rs11": ("RS11", "rs11"),
    "runtz": ("Runtz", "runtz"),
    "superboof": ("Super Boof", "super-boof"),
    "weddingcake": ("Wedding Cake", "wedding-cake"),
}
# These are aliases stated on verified individual Leafly profile pages.
PROFILE_ALIASES = {
    "animalface10": "animalface",
    "blockberry": "superboof",
    "g41": "gelato41",
    "gelato#41": "gelato41",
    "pinkcookies": "weddingcake",
    "rainbowsherbert11": "rs11",
    "rs-11": "rs11",
    "superboof": "superboof",
    "triangle mints 23": "weddingcake",
}


def canonical(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.casefold())
    return re.sub(r"[^a-z0-9]", "", value)


def is_valid_query(value: str) -> bool:
    return (2 <= len(value.strip()) <= 60
            and not any(char in value for char in ("@", "<", ">", "\n", "\r", "\x00", chr(96)))
            and "://" not in value
            and bool(re.search(r"[A-Za-z0-9]", value)))


def profile_for(name: str) -> tuple[str, str] | None:
    if not is_valid_query(name):
        return None
    key = canonical(name)
    aliases = {canonical(alias): canonical(target)
               for alias, target in PROFILE_ALIASES.items()}
    key = aliases.get(key, key)
    entry = VERIFIED_PROFILES.get(key)
    if entry is None:
        return None
    return entry[0], "https://www.leafly.com/strains/" + entry[1]


def leafly_search_url(name: str) -> str | None:
    """Use public search engines for links, never automated requests to Leafly."""
    if not is_valid_query(name):
        return None
    term = "site:leafly.com/strains/ " + name.strip()
    return "https://www.google.com/search?q=" + quote_plus(term)


def leafly_reference(name: str) -> str:
    """A source pointer; does not pretend to fetch reviews or current ratings."""
    if not is_valid_query(name):
        return "Enter a valid strain name with 2–60 characters."
    match = profile_for(name)
    if match:
        display, url = match
        return (f"**Verified Leafly profile:** {display}\n{url}\n"
                "Leafly hosts its own community ratings, effects, flavors and reviews. "
                "Read those on the original page; they are **user reports, not clinical proof**.")
    link = leafly_search_url(name)
    return (f"**Find possible Leafly profiles for:** {name.strip()[:60]}\n"
            f"{link}\n"
            "No individual Leafly page has been verified for this name. "
            "This is a site-restricted external search, **not** a confirmed Leafly record. "
            f"Browse directly: {LEAFLY_DIRECTORY}")


def leafly_answer(name: str) -> str:
    from .strains import result_text
    from .leafly_csv import licensed_data_summary
    from .answers import clip_discord
    local = licensed_data_summary(name)
    extra = ("\n\n" + local) if local else ""
    result = "**Leafly reference:**\n" + leafly_reference(name) + "\n\n" + result_text(name) + extra
    return clip_discord(result)
