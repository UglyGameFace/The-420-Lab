"""Safe, credited, sequential provider fallback for a requested cultivar."""
from .flower_freedom_client import source_summary as flower
from .cannalib_client import source_summary as cannalib, CREDIT as CANNALIB
from .strainapi_client import source_summary as strainapi
from .findmyseeds_client import source_summary as findmyseeds


async def sourced_summary(session, quota, name: str) -> str:
    """One result, short-lived provider caching and no bulk dataset harvesting."""
    first = await flower(session, quota, name)
    if "safety allowance" in first.lower() or "rate limit reached" in first.lower():
        return first[:1024]

    # Independent, publicly documented review-count source complements the
    # smaller original-summary provider. Ratings are *not* Leafly ratings.
    community = await findmyseeds(session, quota, name)
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
    return (first[:180] + "\n" + community[:180] + "\n" +
            second[:180] + "\n" + fallback[:180])[:1024]
