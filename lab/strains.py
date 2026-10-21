"""Offline cannabis name catalog. No estimates of medical effects or potency."""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

DATA = Path(__file__).resolve().parent.parent / "data"
SOURCE = "https://github.com/kushyapp/cannabis-dataset"
NEW_SOURCE = "https://github.com/Shannon-Goddard/ci-strains-pro"
SCIENCE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9119530/"

@dataclass(frozen=True)
class StrainMatch:
    name: str
    kind: str
    breeder: str
    sources: tuple[str, ...]
    approximate: bool = False

def compact(value: str) -> str:
    text = unicodedata.normalize("NFKC", value.casefold())
    return re.sub(r"[^a-z0-9]", "", text)

@lru_cache(maxsize=1)
def load_catalog() -> tuple[tuple[str, str, str], ...]:
    with (DATA / "strains.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    if payload.get("license") != "MIT" or payload.get("snapshot") != "2017-11-14":
        raise ValueError("Legacy provenance mismatch")
    return tuple(tuple(item) for item in payload["records"])

@lru_cache(maxsize=1)
def load_modern_catalog() -> tuple[tuple[str, str, str], ...]:
    with (DATA / "strains_2026.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    if payload.get("license") != "CC BY 4.0" or payload.get("release") != "2026":
        raise ValueError("New catalog provenance mismatch")
    return tuple(tuple(item) for item in payload["records"])

@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, StrainMatch], dict[str, str]]:
    results: dict[str, StrainMatch] = {}
    aliases: dict[str, str] = {}
    for name, kind, breeder in load_catalog():
        key = compact(name)
        if key and key not in results:
            results[key] = StrainMatch(name, kind, breeder, ("Kushy 2017",))
    for name, breeder, alias in load_modern_catalog():
        key = compact(name)
        if not key:
            continue
        previous = results.get(key)
        if previous:
            results[key] = StrainMatch(
                name, previous.kind, breeder or previous.breeder,
                ("CI-Strains-Pro 2026", "Kushy 2017"))
        else:
            results[key] = StrainMatch(
                name, "Catalog listing", breeder, ("CI-Strains-Pro 2026",))
        aka = compact(alias)
        if aka and aka != key and len(aka) >= 3:
            aliases.setdefault(aka, key)
    return results, aliases

def find_matches(query: str, *, limit: int = 5) -> list[StrainMatch]:
    query = query.strip()
    if (len(query) < 2 or len(query) > 60 or
        any(char in query for char in ("@", "<", ">", "\n", "\r", chr(96))) or
        "://" in query):
        return []
    term = compact(query)
    if len(term) < 2:
        return []
    records, aliases = _index()
    key = aliases.get(term, term)
    if key in records:
        return [records[key]]
    begins, contains = [], []
    for candidate, entry in records.items():
        if candidate.startswith(term):
            begins.append(entry)
        elif term in candidate:
            contains.append(entry)
    if begins or contains:
        # A short name is normally a closer search hit than a long vendor SKU.
        # Prefer beginning-of-name matches; display entries without inventing
        # that a marketing strain name guarantees a distinct genetic cultivar.
        begins.sort(key=lambda item: (abs(len(compact(item.name)) - len(term)),
                                      item.name.casefold()))
        contains.sort(key=lambda item: (abs(len(compact(item.name)) - len(term)),
                                        item.name.casefold()))
        return (begins + contains)[:limit]
    if len(term) < 4:
        return []
    shortlist = ((key, match) for key, match in records.items()
                 if key[:2] == term[:2] and abs(len(key) - len(term)) <= 4)
    scored = sorted(
        ((SequenceMatcher(None, term, key).ratio(), value)
         for key, value in shortlist), key=lambda row: row[0], reverse=True)
    return [StrainMatch(value.name, value.kind, value.breeder,
                        value.sources, True)
            for score, value in scored[:limit] if score >= 0.75]

def lookup(query: str, *, limit: int = 5) -> list[tuple[str, str, str]]:
    """Keep compatibility with the earlier lookup API."""
    return [(item.name, item.kind, item.breeder)
            for item in find_matches(query, limit=limit)]

def _safe(value: str, maximum: int = 95) -> str:
    return re.sub(r"[^a-zA-Z0-9 #()&/+.,'-]", "", value)[:maximum]

def result_text(query: str) -> str:
    matches = find_matches(query)
    lines = ["**The Weed Doctor | Strain Name Finder**",
             "Catalog name references from 2017 and 2026, not lab-tested products."]
    if not matches:
        lines.append("No name found in either catalog. Try another spelling, "
                     "an abbreviated name or a breeder's listing name.")
    else:
        lines.append("**Possible spelling suggestions (not exact matches):**"
                     if matches[0].approximate else "**Catalog matches:**")
        for entry in matches:
            kind = _safe(entry.kind, 28)
            breeder = _safe(entry.breeder, 50)
            if breeder and breeder.lower() not in ("unknown breeder", "none", "null"):
                kind += " • listed breeder: " + breeder
            lines.append("• **" + _safe(entry.name) + "** — " + kind)
            lines.append("  Source: " + ", ".join(entry.sources))
    lines.extend([
        "",
        "**Limitations:** Names, breeders, and indica/sativa labels do not reliably predict "
        "chemical composition, THC potency, effects, or medical benefits. Catalog listings "
        "may represent multiple products rather than unique verified cultivars.",
        "2017 MIT data: " + SOURCE,
        "2026 CC BY 4.0 data: " + NEW_SOURCE,
        "Research on label reliability: " + SCIENCE,
    ])
    return "\n".join(lines)
