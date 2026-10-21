"""Transparent strain-index counts and source freshness, no network calls."""
from __future__ import annotations

from functools import lru_cache

from .strains import load_catalog, load_modern_catalog, load_leafly_name_mirror, _index
from .leafly import VERIFIED_PROFILES


@lru_cache(maxsize=1)
def catalog_stats() -> dict[str, int]:
    """Counts actual bundled data, never claims a live upstream refresh."""
    records, _ = _index()
    return {
        "distinct_names": len(records),
        "kushy_rows": len(load_catalog()),
        "ci_rows": len(load_modern_catalog()),
        "leafly_added": len(load_leafly_name_mirror()),
        "leafly_profiles": len(VERIFIED_PROFILES),
    }


def status_text() -> str:
    stats = catalog_stats()
    return (
        "**🌱 The Weed Doctor | Database Coverage**\n"
        f"**{stats['distinct_names']:,}** distinct searchable strain-name entries.\n"
        f"• Kushy legacy source: **{stats['kushy_rows']:,}** records, snapshot **2017-11-14** (MIT).\n"
        f"• Cannabis Intelligence Database: **{stats['ci_rows']:,}** entries, released **2026** (CC BY 4.0).\n"
        f"• Historical third-party Leafly-name mirror: **{stats['leafly_added']:,}** extra names "
        "(mirror age not established; not an official Leafly feed).\n"
        f"• Individually curated Leafly profile links: **{stats['leafly_profiles']}**.\n\n"
        "**Freshness:** These counts describe packaged snapshots. "
        "They do **not** imply live synchronization or that every strain is current.\n"
        "**What we don't automatically provide:** Leafly-owned images, proprietary descriptions, "
        "review counts or current THC percentages. Those require lawful source access.\n"
        "**Measured batch chemistry:** Cannlytics publishes COA results; see /strainsources. "
        "A batch result cannot be generalized to every product sold under that name.\n"
        "**Sources:** https://github.com/kushyapp/cannabis-dataset | "
        "https://github.com/Shannon-Goddard/ci-strains-pro | "
        "https://github.com/cannlytics/cannabis_results"
    )


def other_sources_text() -> str:
    return (
        "**🔬 The Weed Doctor | Strain Data Sources**\n"
        "**1. Cannlytics Cannabis Results:** public laboratory CoAs, source/batch dates, "
        "measured cannabinoid and terpene profiles where reported. Dataset license: CC BY 4.0; "
        "individual source rights and results still need review. "
        "https://github.com/cannlytics/cannabis_results\n"
        "**2. Cannlytics API:** authenticated /data, strains and certificates features; "
        "requires a separate account/API key, not configured automatically. "
        "https://cannlytics.com/api\n"
        "**3. OpenTHC:** common product, variety and lab-result schemas, "
        "**not** a downloadable universal strain database. "
        "https://api.openthc.org/\n"
        "**4. Leafly:** community profiles, images and reviews at the original website; "
        "full in-bot reuse requires authorization. "
        "https://www.leafly.com/strains\n"
        "**5. Our name catalogs:** 2017 Kushy MIT + 2026 CI-Strains-Pro CC BY + "
        "historical Leafly-name mirror. See /strainstats for counts.\n\n"
        "**Evidence note:** A cultivar name does not reliably predict product THC, "
        "medical outcomes, effects or batch purity. For those, prefer a specific "
        "tested batch COA and peer-reviewed research."
    )
