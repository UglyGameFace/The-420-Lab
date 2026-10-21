"""Small independently checked, source-specific cultivar references.

A named cannabis cultivar may have numerous seed-bank variants. These notes
describe a specific public source's record, never a laboratory confirmation
of whatever flower a person has.
"""
from __future__ import annotations

from .strains import compact

# Each case must have independently checked source URLs and must not claim
# product sample potency, photo authenticity or an originating breeder.
REFERENCES = {
    "northernlights": {
        "label": "Indica / indica-dominant",
        "classification_sources": (
            ("Leafly listing", "https://www.leafly.com/strains/northern-lights"),
            ("Sensi Seeds Northern Lights line",
             "https://sensiseeds.com/en/regular/northern-lights-3"),
        ),
        "note": ("Northern Lights is sold in multiple breeder-specific versions. "
                 "These sources do not authenticate a member's particular plant."),
    }
}


def reference_for(name: str) -> dict | None:
    return REFERENCES.get(compact(name))


def reference_lines(name: str) -> list[str]:
    ref = reference_for(name)
    if not ref:
        return []
    sources = " • ".join(
        f"[{label}]({link})" for label, link in ref["classification_sources"])
    return [
        f"**Source-reported classification:** {ref['label']} ({sources})",
        f"**Cultivar variants:** {ref['note']}",
    ]
