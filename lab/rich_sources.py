"""Safe, credited, bounded concurrent lookups with sequential fallbacks."""
import asyncio
from .flower_freedom_client import source_summary as flower
from .cannalib_client import source_summary as cannalib, CREDIT as CANNALIB
from .strainapi_client import source_summary as strainapi
from .findmyseeds_client import source_summary as findmyseeds


async def sourced_summary(session, quota, name: str) -> str:
    """One result, short-lived provider caching and no bulk dataset harvesting."""
    first, community = await asyncio.gather(
        flower(session, quota, name), findmyseeds(session, quota, name),
        return_exceptions=True)
    if isinstance(first, Exception):
        first = "Flower & Freedom temporarily unavailable."
    if isinstance(community, Exception):
        community = "Find My Seeds temporarily unavailable."
    if "safety allowance" in first.lower() or "rate limit reached" in first.lower():
        return first[:1024]

    # Independent, publicly documented review-count source complements the
    # smaller original-summary provider. Ratings are *not* Leafly ratings.
    if "safety allowance" in community.lower() or "rate limit reached" in community.lower():
        return first[:1024] if first.startswith("**") else community[:1024]
    if first.startswith("**") and community.startswith("**"):
        return (first[:575] + "\n\n" + community[:430])[:1024]
    if first.startswith("**"):
        return first[:1024]
    if community.startswith("**"):
        return community[:1024]

    second = await cannalib(session, quota, name)
    if second.startswith("**"):
        return (second[:870] + "\n" + CANNALIB)[:1024]
    if "safety allowance" in second.lower() or "rate limit reached" in second.lower():
        return (second[:940] + "\n" + CANNALIB)[:1024]

    fallback = await strainapi(session, quota, name)
    if fallback.startswith("**"):
        return fallback[:1024]
    return "No additional independently confirmed source record available."
