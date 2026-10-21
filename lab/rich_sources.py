"""Provider-fallback source text with explicit attribution per source."""
from .cannalib_client import source_summary as cannalib, CREDIT as CANNALIB
from .strainapi_client import source_summary as strainapi

async def sourced_summary(session, quota, name: str) -> str:
    primary = await cannalib(session, quota, name)
    if primary.startswith("**"):
        return (primary[:880] + "\n" + CANNALIB)[:1024]
    # Do not bypass exhausted global safety allowances with another API.
    if "safety allowance" in primary.lower() or "rate limit reached" in primary.lower():
        return primary[:1024] + "\n" + CANNALIB
    fallback = await strainapi(session, quota, name)
    if fallback.startswith("**"):
        return fallback[:1024]
    return ((primary[:300] + "\n" + CANNALIB + "\n" + fallback[:300])[:1024])
