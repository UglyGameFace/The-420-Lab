"""Public API smoke checks. No bot token or AI key required.

Run with: python -m tools.live_source_probe
Performs one read-only request series per source and prints no user information.
"""
from __future__ import annotations
import asyncio
import sys
import aiohttp
from lab.sources import ScienceSources

async def probe():
    timeout = aiohttp.ClientTimeout(total=18)
    failures = []
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": "TheWeedDoctor-public-smoke/1.0 (github.com/UglyGameFace/The-420-Lab)"}
    ) as session:
        client = ScienceSources(session)
        checks = (
            ("PubMed", lambda: client.pubmed("cannabis anxiety")),
            ("PubChem", lambda: client.compound("CBD")),
            ("ClinicalTrials.gov", lambda: client.trials("sleep")),
            ("openFDA", lambda: client.fda_reports("epidiolex")),
        )
        for name, action in checks:
            try:
                result = await action()
                if result is None:
                    raise ValueError("Empty provider response")
                if name == "PubMed" and not result:
                    raise ValueError("No papers returned")
                print(f"PASS {name}: response parsed successfully")
            except Exception as exc:
                print(f"FAIL {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                failures.append(name)
    if failures:
        raise SystemExit("Public provider smoke failures: " + ", ".join(failures))


if __name__ == "__main__":
    asyncio.run(probe())
