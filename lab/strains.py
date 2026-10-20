"""Offline lookup in an attributed, historical MIT strain-name index.

Name, catalog classification and listed breeder are descriptors, not
verified chemical data, medical evidence, or a purchasing recommendation.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "strains.json"
SOURCE = "https://github.com/kushyapp/cannabis-dataset"
SCIENCE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9119530/"

@lru_cache(maxsize=1)
def load_catalog() -> tuple[tuple[str, str, str], ...]:
    with DATA_FILE.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("license") != "MIT" or payload.get("snapshot") != "2017-11-14":
        raise ValueError("Unexpected cannabis catalog provenance")
    return tuple(tuple(entry) for entry in payload["records"])

def lookup(query: str, *, limit: int = 5) -> list[tuple[str, str, str]]:
    term = re.sub(r"[^a-z0-9 ]", "", query.lower().strip())
    if len(term) < 2 or len(term) > 60:
        return []
    exact, begins, contains = [], [], []
    for name, kind, breeder in load_catalog():
        normalized = re.sub(r"[^a-z0-9 ]", "", name.lower())
        entry = (name, kind, breeder)
        if normalized == term:
            exact.append(entry)
        elif normalized.startswith(term):
            begins.append(entry)
        elif term in normalized:
            contains.append(entry)
    return (exact + begins + contains)[:limit]

def result_text(query: str) -> str:
    results = lookup(query)
    lines = ["**Historical strain-name reference (2017 dataset)**"]
    if not results:
        lines.append("No matching names in this historical index. Try a different spelling.")
    else:
        for name, kind, breeder in results:
            details = kind
            if breeder and breeder != "Unknown Breeder":
                details += f" • catalog breeder: {breeder}"
            lines.append(f"• **{name}** — {details}")
    lines.extend([
        "",
        "**Important:** These are legacy catalog names, not verified current products. "
        "Indica/sativa/hybrid names and strain labels do not reliably predict chemical "
        "composition, THC potency, effects, or medical benefits. Batch-specific laboratory "
        "testing is needed to assess actual contents. No marketing effect claims are imported.",
        f"Historical MIT data: {SOURCE}",
        f"Research on label reliability: {SCIENCE}",
    ])
    return "\n".join(lines)
