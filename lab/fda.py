"""Bounded openFDA drug-event report summaries, NOT estimates of drug risk."""
from __future__ import annotations

from dataclasses import dataclass
import re

# FDA-approved cannabinoid medicines, not general cannabis/retail products.
FDA_PRODUCTS = {
    "epidiolex": "EPIDIOLEX (prescription cannabidiol)",
    "marinol": "MARINOL (dronabinol)",
    "syndros": "SYNDROS (dronabinol)",
    "cesamet": "CESAMET (nabilone)",
}
FDA_SOURCE = "https://open.fda.gov/apis/drug/event/"
FDA_LIMITS = "https://www.fda.gov/safety/fda-adverse-event-monitoring-system-aems"
FDA_ENDPOINT = "https://api.fda.gov/drug/event.json"

@dataclass(frozen=True)
class FDAReportTerms:
    product: str
    reactions: tuple[tuple[str, int], ...]
    last_updated: str = ""

def parse_terms(payload: dict, product: str) -> FDAReportTerms:
    """Only product presets and aggregate reaction terms; no individual records."""
    if product not in FDA_PRODUCTS:
        raise ValueError("Unsupported medicine")
    rows = payload.get("results", [])
    if not isinstance(rows, list):
        raise ValueError("Malformed response")
    result = []
    for item in rows[:5]:
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        count = item.get("count")
        if not isinstance(term, str) or type(count) is not int or count < 0:
            continue
        # FDA data is external text: avoid markup, mentions, and arbitrary links.
        term = re.sub(r"[^A-Za-z0-9 ,()/.-]", "", term).strip()[:62]
        if term:
            result.append((term, count))
    meta = payload.get("meta", {})
    date = str(meta.get("last_updated", "")) if isinstance(meta, dict) else ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = ""
    return FDAReportTerms(product, tuple(result), date)

def report_message(data: FDAReportTerms) -> str:
    if data.product not in FDA_PRODUCTS:
        return "Unsupported FDA medicine."
    title = FDA_PRODUCTS[data.product]
    lines = [f"**FDA safety-report explorer | {title}**",
             "These are reaction terms appearing in openFDA reports that also name this medicine."]
    if data.reactions:
        lines.extend(["", "**Listed terms in matching reports (report mentions, NOT side-effect rates):**"])
        for reaction, count in data.reactions:
            lines.append(f"• {reaction.title()}: {count:,} matching report mentions")
    else:
        lines.extend(["", "No matching report terms were available for this exact name."])
    if data.last_updated:
        lines.append(f"Dataset last updated: {data.last_updated}")
    lines.extend(["", "**Critical limits:** Reports may be duplicate, incomplete, unverified, or "
                      "list several medicines. A listed reaction does NOT prove this medicine caused it. "
                      "Counts cannot estimate likelihood, safety, or compare products.",
                  "This searches an FDA-approved medicine name, **not** recreational cannabis or all THC/CBD use.",
                  f"Source: {FDA_SOURCE}",
                  f"FDA explanation: {FDA_LIMITS}"])
    return "\n".join(lines)
